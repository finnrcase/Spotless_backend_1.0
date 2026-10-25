"""Audit paired result identities, legacy preservation, bounds, and experiment scope."""
import hashlib
import json
from pathlib import Path
import pandas as pd
import numpy as np
import joblib
from la_parking.temporal_experiment import INPUT_COLUMNS,prepare,predict
from la_parking.temporal_predictors import asof_context
from la_parking.modeling import utc
from la_parking.evaluation import regression_metrics,probability_metrics

root=Path('reports/modeling')
rows=json.loads((root/'temporal_v2_results.json').read_text());frame=pd.DataFrame(rows)
protocol=json.loads((root/'temporal_v2_protocol.json').read_text())
for name,expected in protocol['legacy_fingerprints'].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==expected,name+' legacy content changed'
assert set(frame.horizon)=={0,15,30,60,120},'Missing horizon'
for keys,g in frame.groupby(['horizon','axis','target']):
    assert g.row_sha256.nunique()==1,(keys,'Different test identities/targets')
    assert g.n.nunique()==1,(keys,'Different evaluated sample size')
assert not frame.duplicated(['horizon','axis','variant','target']).any()
pred=pd.read_parquet('data/modeling/temporal_v2/predictions.parquet')
assert np.isfinite(pred.prediction).all() and pred.prediction.between(0,1).all()
assert pred.actual.between(0,1).all() and (pred.issued_at_utc<=pred.arrival_time_utc).all()
assert not pred.arrival_time_utc.between(pd.Timestamp('2026-09-21',tz='America/Los_Angeles'),pd.Timestamp('2026-10-01',tz='America/Los_Angeles')).any()
# Frozen v1 scores are reproduced on the same test rows. There is no new test claim.
old=json.loads((root/'results.json').read_text());lookup={('future_time_known' if r['axis']=='future_time' else 'unseen_block' if r['axis']=='unseen_area' else 'future_time_unseen',r['horizon'],r['target']):r for r in old if r['model']=='boosted'}
for r in rows:
    if r['variant']!='frozen_v1_boosted':continue
    previous=lookup[(r['axis'],r['horizon'],r['target'])]
    assert previous['n']==r['n']
    for field in ['r2','mae','rmse','brier_score','log_loss']:
        if field in r and r[field] is not None:assert np.isclose(previous[field],r[field],rtol=1e-8,atol=1e-10),(r['horizon'],r['axis'],field)
# Consume saved bundles through their inference interface: no fitting/re-selection.
source=pd.read_parquet('data/modeling/temporal_v2/legacy_enhanced.parquet',columns=INPUT_COLUMNS,filters=[('horizon_minutes','=',60)])
source=asof_context(source,pd.read_parquet('data/modeling/temporal_v2/context_asof.parquet'));source=prepare(source,'known_blocks')
ends=source.arrival_time_utc+pd.Timedelta('15min');known=set(source.loc[ends<utc('2026-08-17')-pd.Timedelta('180min'),'block_id'])
mask=(source.issued_at_utc>=utc('2026-08-25'))&(ends<utc('2026-09-01'))&source.block_id.isin(known)
consumed=[]
for head,target,column in [('broader_tuning','occupancy_rate','target_occupancy_rate'),('available_count','available_count','target_available_count'),('any_panel_vacant','any_panel_vacant','target_any_panel_vacant')]:
    bundle=joblib.load(Path('artifacts/models/temporal_v2')/f'known_blocks_h60_{head}.joblib')
    held=source.loc[mask&source[column].notna()].reset_index(drop=True);patterns=bundle['training_patterns'].transform(held)
    for col in patterns:held[col]=patterns[col].to_numpy()
    p=predict(bundle,held,calibrated=True)
    assert np.isfinite(p).all() and (p>=0).all()
    assert (p<=held.panel_sensor_count).all() if target=='available_count' else (p<=1).all()
    m=probability_metrics(held[column],p) if target=='any_panel_vacant' else regression_metrics(held[column],p)
    variant='broader_tuning' if target=='occupancy_rate' else 'asof_context_auxiliary'
    expected=next(r for r in rows if r['horizon']==60 and r['axis']=='future_time_known' and r['variant']==variant and r['target']==target)
    for key in ['r2','rmse','mae','brier_score','ece']:
        if key in m and m[key] is not None:assert np.isclose(m[key],expected[key],rtol=1e-8,atol=1e-10),(target,key)
    consumed.append(target)
report={'passed':True,'legacy_fingerprints_unchanged':True,'frozen_v1_metrics_reproduced':True,'identical_target_row_hashes_all_variants':True,'rate_predictions_bounded':True,'saved_bundle_inference_reproduced':consumed,'new_holdout_opened':False,'unmetered_validation_claimed':False,'result_rows':len(rows)}
(root/'temporal_v2_checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
