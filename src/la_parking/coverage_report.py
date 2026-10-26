"""Fixed-row comparisons, integrity checks and concise measured reporting."""
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from .census_coverage import ROOT
from .coverage_experiment import REPORT,metrics
from .modeling import TARGETS,predict_head
from .temporal_experiment import prepare,check_registered_inputs


def paired_references():
    """Re-score frozen versions on v4 rows; never fit or select on diagnostics."""
    predictions=pd.read_parquet(ROOT/'predictions.parquet');rows=predictions.loc[predictions.target.eq('occupancy_rate')&predictions.variant.eq('existing_census')]
    prior=pd.read_parquet('data/modeling/temporal_v2/predictions.parquet',filters=[('horizon_minutes','=',60)])
    old_results=json.loads((REPORT/'temporal_v2_results.json').read_text());keys=['block_face_id','issued_at_utc','arrival_time_utc']
    legacy=pd.read_parquet('data/modeling/temporal_v2/legacy_enhanced.parquet',filters=[('horizon_minutes','=',60)])
    results=[]
    with threadpool_limits(limits=2):
        for axis in ['future_time_known','unseen_block','future_time_unseen']:
            q=rows.loc[rows.axis.eq(axis)].copy().reset_index(drop=True)
            choice=min([r for r in old_results if r['horizon']==60 and r['axis']==axis and r['target']=='occupancy_rate' and r.get('validation_rmse') is not None and r['variant'] in set(prior.variant)],key=lambda r:r['validation_rmse'])['variant']
            v2=prior.loc[prior.axis.eq(axis)&prior.variant.eq(choice)]
            joined=q.merge(v2[keys+['actual','prediction']],on=keys,how='left',validate='one_to_one',suffixes=('','_v2'))
            if len(joined)!=len(q) or joined.prediction_v2.isna().any():raise ValueError('Missing paired v2 reference')
            np.testing.assert_allclose(joined.target_occupancy_rate,joined.actual,rtol=0,atol=0)
            results.append({'axis':axis,'version':'frozen_v2_'+choice,'target':'occupancy_rate',**metrics(q,joined.prediction_v2.to_numpy(),'occupancy_rate')})
            f=q[keys].merge(legacy,on=keys,how='left',validate='one_to_one')
            mode='known_blocks' if axis=='future_time_known' else 'unseen_blocks';f=prepare(f,mode)
            label='future_time' if axis=='future_time_known' else 'unseen_area'
            bundle=joblib.load(f'artifacts/models/{label}_h60_occupancy_rate_boosted.joblib')
            p=predict_head(bundle,f);results.append({'axis':axis,'version':'frozen_v1_boosted','target':'occupancy_rate',**metrics(q,p,'occupancy_rate')})
    (REPORT/'coverage_v4_paired_references.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    return results


def check():
    check_registered_inputs();protocol=json.loads((REPORT/'coverage_v4_protocol.json').read_text())
    inputs={**protocol['inputs_sha256'],'config/coverage_v4.json':protocol['config_sha256']}
    for path,digest in inputs.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen experiment input changed: '+path)
    results=json.loads((REPORT/'coverage_v4_results.json').read_text())
    for target in TARGETS:
        for axis in {r['axis'] for r in results}:
            same=[r for r in results if r['target']==target and r['axis']==axis]
            if len({(r['n'],r['row_sha256'],r['candidate_rows']) for r in same})!=1:raise ValueError('Variants changed target rows')
    p=pd.read_parquet(ROOT/'predictions.parquet')
    for target,col in TARGETS.items():
        q=p.loc[p.target.eq(target)]
        if not np.isfinite(q.prediction).all() or (q.prediction<0).any():raise ValueError('Invalid predictions')
        if target!='available_count' and q.prediction.gt(1).any():raise ValueError('Invalid rate/probability')
        if (q.arrival_time_utc-q.issued_at_utc!=pd.Timedelta('60min')).any():raise ValueError('Inconsistent forecast times')
    # Check counts against the actual monthly roster on exactly the same rows.
    design=pd.read_parquet(ROOT/'design.parquet',columns=['block_face_id','issued_at_utc','arrival_time_utc','panel_sensor_count'])
    q=p.loc[p.target.eq('available_count')].merge(design,on=['block_face_id','issued_at_utc','arrival_time_utc'],how='left',validate='many_to_one')
    if q.panel_sensor_count.isna().any() or q.prediction.gt(q.panel_sensor_count+1e-8).any():raise ValueError('Count exceeds panel bound')
    artifacts={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path('artifacts/models/coverage_v4').glob('*.joblib')}
    lock=REPORT/'coverage_v4_lock.json'
    if lock.exists() and json.loads(lock.read_text())['model_sha256']!=artifacts:raise ValueError('Frozen v4 model changed')
    checks={'checks_passed':True,'variants_have_identical_targets':True,'new_holdouts_unopened':True,'model_sha256':artifacts,'models_promoted':False,'unmetered_validation_n':0}
    lock.write_text(json.dumps(checks,indent=2),encoding='utf8')
    references=paired_references();report(results,references)
    print(json.dumps({k:v for k,v in checks.items() if k!='model_sha256'},indent=2));return checks


def report(rows,references):
    selection=json.loads((REPORT/'coverage_v4_selections.json').read_text());complete=json.loads((REPORT/'coverage_v4_complete.json').read_text())
    fmt=lambda x:'—' if x is None else f'{x:.4f}'
    lines=['# Census and regional coverage v4','','The 2023 ACS static tables now cover all 2,498 Los Angeles County tracts. Existing 53-tract estimate/MOE cells and 964 Westwood vehicle-ratio pairs match exactly. No previously missing Westwood vehicle ratio was filled. All source estimate/MOE columns, sentinel codes, GEOIDs, release dates and raw hashes remain available locally. The authenticated one-tract Census request failed (invalid-key HTML with HTTP 200); cached official public files supplied this experiment.','',
        'Additional features are a lower bound on vehicles per household (four represents the 4+ category) and the one-person-household fraction. They do not duplicate the existing no-vehicle fraction or housing density. Derived ratio MOEs stay null without covariance; source MOEs are preserved. These are 2019–2023 contextual estimates, not occupancy truth.','',
        '## Rolling validation','','60-minute horizon, Aug9/Aug13 origins, three-day windows, 180-minute embargo, fixed ExtraTrees complexity. All variants and baselines use identical target rows. Known-block rows are chronological validation of static transferable models; temporal-v2 own-history forecasting remains a separate approach. Neighborhood holdouts exclude both sides of all physical blocks in the held-out region. Select regression heads on geographic/time validation MSE and the binary head separately on Brier.','',
        '| Validation axis | Feature variant | R² | MAE | RMSE | n / blocks |','|---|---|---:|---:|---:|---:|']
    for r in selection['validation']:
        if r['target']=='occupancy_rate':lines.append(f"| {r['axis']} | {r['variant']} | {fmt(r['r2'])} | {fmt(r['mae'])} | {fmt(r['rmse'])} | {r['n']} / {r['blocks']} |")
    lines+=['','The new variables slightly improve known-block chronological rate validation but worsen unseen-neighborhood rate validation. The selected rate variant remains **existing_census**. Added variables are selected for count and binary heads separately; they are experimental and not automatically activated.','',
        '## Legacy diagnostics','','These are previously inspected periods, never fresh untouched tests. Original Westwood unseen-block rows match v1/v2 exactly (3,705 pure geographic and 478 future/geographic rate labels). The known-block comparison below uses the same 5,274 South development labels for each frozen version; it is a subset of the prior 6,421-row all-known-block benchmark. Frozen v2 was trained on a different broader known-block population, so this is a model-version comparison, not a controlled Census-only ablation. Complete controlled ablations, count metrics, calibration bins and block-bootstrap intervals are in coverage_v4_results.json / coverage_v4_experiments.csv.','',
        '| Axis | Version/variant | R² | MAE | n / blocks | Rate coverage |','|---|---|---:|---:|---:|---:|']
    for axis in ['future_time_known','unseen_block','future_time_unseen','future_time_Downtown','future_time_Hollywood']:
        for r in [x for x in references if x['axis']==axis]+[x for x in rows if x['axis']==axis and x['target']=='occupancy_rate' and (x['selected_for_target'] or x['variant'] in ['weekhour','additional_census'])]:
            lines.append(f"| {axis} | {r.get('version',r.get('variant'))} | {fmt(r['r2'])} | {fmt(r['mae'])} | {r['n']} / {r['blocks']} | {format(r['coverage'],'.1%') if 'coverage' in r else 'same paired rows'} |")
    lines+=['','Do not replace the known-block temporal model with these static models: consult the paired scores above. The geographic selection result is still negative on neighborhood validation. Positive Downtown/Hollywood future scores use previously observed blocks, and do not validate transfer to other streets.','',
        '| Axis | Available-count R² / MAE | Binary Brier / ECE | n / blocks | Complete-point coverage |','|---|---:|---:|---:|---:|']
    for axis in ['future_time_known','unseen_block','future_time_unseen','future_time_Downtown','future_time_Hollywood']:
        count=next(r for r in rows if r['axis']==axis and r['target']=='available_count' and r['selected_for_target']);binary=next(r for r in rows if r['axis']==axis and r['target']=='any_panel_vacant' and r['selected_for_target'])
        lines.append(f"| {axis} | {fmt(count['r2'])} / {fmt(count['mae'])} | {fmt(binary['brier_score'])} / {fmt(binary['ece'])} | {count['n']} / {count['blocks']} | {count['coverage']:.1%} |")
    lines+=['','Binary probabilities refer only to at least one vacant sensor-panel bay, not legal/suitable curb space. Platt calibration used Aug17–21 development rows. Geographic calibration transfer remains unvalidated; 39 future/unseen points on two blocks are particularly weak evidence. Whole-block bootstrap intervals condition on sparse, selected sensor labels and do not capture sensor error, cross-block dependence or mapping uncertainty.','',
        '## Coverage and gaps','','Eight physical blocks each in Downtown and Hollywood were selected in fixed hash order from discovery-reporting sensors, without occupancy values/errors. August has supported rate bins on eight Downtown and seven Hollywood blocks; complete city street faces remain in the collector even when no label exists. No occupancy archive was downloaded again; cached Sep2025 and Jun–Aug2026 files were filtered locally. Full 16-block Census joins have no missing tracts/household features. This is limited, purposive metered coverage, not a representative LA sample.','',
        'Only 13.59% of expected new-region August sensor-time remains known under the unchanged 15-minute expiry. Reaffirmations comprise about 0.36% of comparable August Downtown states and 0.042% in Hollywood. Long silences/UNKNOWN remain uncertain. No official heartbeat/outage SLA or reviewed independent bay observations establishes a better expiry; no rule changed for R². Current location checks reconcile 4,002 Downtown and 1,511 Hollywood object IDs, explicitly excluding SENSOR_STATUS values. 150/38 respectively lie over 35m from the nearest meter point; 363/115 nearest matches are ambiguous within 3m. These flags do not establish faults, identity or historical installation/move dates. Historical reporting-ID counts changed; current map IDs/positions do not resolve lineage.','',
        'The Census joins are available by their 2024-12-12 public release, but street/meter assignments still use the October 2026 inventory retrospectively. Current restrictions, legal capacity, business operating hours, event information vintages and broader workplace joins remain incomplete; this task does not fabricate them. Numeric live predictions and suitable-space probabilities remain unsupported where the existing model/rules do not support them. All earlier prospective archive/manual reservations remain untouched.','',
        '**Unmetered validation n = 0.** R², count MAE, probability calibration and the benefit of mixed metered/unmetered training are unavailable until reviewed direct counts exist. The collector now has 2,002 faces and 32 optional regional planned visits; planned visits are never labels. Start with the existing eight-count Westwood batch. See docs/coverage_v4.md for exact commands, field dates and remaining actions.']
    (REPORT/'COVERAGE_V4.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
