"""Measured reports, figures, coverage and executed notebook for modeling run."""
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
os.environ.setdefault('MPLCONFIGDIR',str(Path.cwd()/'.matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def report():
    out=Path('reports/modeling');out.mkdir(exist_ok=True)
    results=json.loads((out/'results.json').read_text());r=pd.DataFrame([{k:v for k,v in x.items() if k not in ['strata','reliability_bins']} for x in results])
    labels=json.loads((out/'label_manifest.json').read_text());ablations=pd.DataFrame(json.loads((out/'ablations.json').read_text()))
    d=pd.read_parquet('data/modeling/design.parquet')
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
    for axis,ax in zip(['future_time','unseen_area'],axes):
        for model in ['time_week','persistence','pooled','regularized','boosted']:
            q=r[(r.axis==axis)&(r.target=='occupancy_rate')&(r.model==model)].sort_values('horizon')
            ax.plot(q.horizon,q.r2,marker='o',label=model)
        ax.axhline(0,color='black',lw=.6);ax.set(xlabel='Forecast lead (minutes)',ylabel='Held-out test R²',title=axis.replace('_',' '))
    axes[1].legend(fontsize=8);fig.suptitle('Metered sensor-panel occupancy proxy — not full-curb suitability')
    fig.savefig(out/'test_r2.png',dpi=180);fig.savefig(out/'test_r2.svg');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    for axis,ax in zip(['future_time','unseen_area'],axes):
        for horizon in [0,30,60,120]:
            matches=[x for x in results if x['axis']==axis and x['target']=='any_panel_vacant' and x['model']=='boosted' and x['horizon']==horizon]
            if not matches or 'reliability_bins' not in matches[0]:continue
            bins=pd.DataFrame(matches[0]['reliability_bins']);bins=bins[bins.n>0]
            ax.plot(bins.mean_probability,bins.observed_frequency,'o-',label=f'{horizon} min (n={matches[0]["n"]})')
        ax.plot([0,1],[0,1],'--',color='gray');ax.set(xlim=(0,1),ylim=(0,1),xlabel='Predicted panel-vacancy proxy probability',ylabel='Reconstructed panel frequency',title=axis.replace('_',' '));ax.legend(fontsize=7)
    fig.suptitle('Calibration for complete sensor panels; legality and total curb coverage unknown')
    fig.savefig(out/'calibration.png',dpi=180);fig.savefig(out/'calibration.svg');plt.close(fig)
    # Actual support masks, never color unsupported geography with model predictions.
    faces=gpd.read_parquet('data/processed/pilot_block_faces.parquet')
    source=d.loc[d.horizon_minutes==0].groupby('block_face_id').agg(label_rows=('target_occupancy_rate','count'),candidate_rows=('target_occupancy_rate','size'),spatial_role=('spatial_role','first')).reset_index()
    support=faces[['block_face_id','segment_id','geometry']].merge(source,on='block_face_id',how='left',validate='one_to_one')
    support['has_sensor_labels']=support.label_rows.fillna(0)>0
    support['curb_eligible_label']=False
    support['support_status']=np.where(support.has_sensor_labels,'experimental_metered_panel','no_occupancy_label')
    support['label_fraction']=support.label_rows/support.candidate_rows
    support.to_parquet('data/modeling/face_support.parquet',index=False)
    city=pd.read_parquet('data/processed/block_faces.parquet',columns=['block_face_id','segment_id'])
    city=city.merge(source,on='block_face_id',how='left',validate='one_to_one')
    city['support_status']=np.where(city.label_rows.fillna(0)>0,'experimental_metered_panel','insufficient_data')
    city['validated_suitable_space_prediction']=False
    city.to_parquet('data/modeling/city_support.parquet',index=False)
    city_summary={'city_faces':len(city),'faces_with_experimental_panel_labels':int(city.label_rows.fillna(0).gt(0).sum()),'faces_without_occupancy_labels':int(city.label_rows.fillna(0).eq(0).sum()),'validated_suitable_space_faces':0,'unmetered_test_labels':0,'citywide_numerical_suitability_abstention_rate':1.0}
    (out/'geographic_support.json').write_text(json.dumps(city_summary,indent=2))
    boundary=gpd.read_parquet('data/processed/city_boundary.parquet')
    fig,axes=plt.subplots(1,2,figsize=(11,6),layout='constrained')
    boundary.plot(ax=axes[0],color='#eeeeea',edgecolor='#62665d',linewidth=.8);support.plot(ax=axes[0],color='#d17343',linewidth=1)
    axes[0].set_title('City of Los Angeles: pilot location');axes[0].set_axis_off()
    support.plot(ax=axes[1],color='#d5d7d0',linewidth=.8)
    support.loc[support.has_sensor_labels].plot(ax=axes[1],color='#176c59',linewidth=2)
    support.loc[support.has_sensor_labels&support.spatial_role.eq('test')].plot(ax=axes[1],color='#d17638',linewidth=2)
    axes[1].set_title('Green: sensor panels · orange: held-out area\nGray: no occupancy labels');axes[1].set_axis_off()
    fig.suptitle('All eligible-curb suitability predictions remain unsupported')
    fig.savefig(out/'coverage.png',dpi=180);fig.savefig(out/'coverage.svg');plt.close(fig)
    # Link to exact sensor-time quality; report missing target windows alongside conditional metrics.
    lines=['# Time-specific prediction: measured results','','This run trains and evaluates metered **sensor-panel proxies**, not total or legally eligible curb parking. All user-facing numerical suitable-space predictions abstain.','',
           f"Geography: {city_summary['faces_with_experimental_panel_labels']} city faces have experimental panel labels; {city_summary['faces_without_occupancy_labels']:,} have no occupancy labels. No verified unmetered labels exist.",'',
           'The final chronological test is August 25–31, 2026. Model parameters use earlier rolling origins, with calibration August 18–23 and a gap before the final test. The primary unseen-area experiment withholds the north pilot area plus a 150 m training buffer at overlapping historical periods, so it measures spatial generalization, not prospective forecasting. The combined future/unseen-area experiment is separate.','',
           '| Test | Horizon | Model | Proxy rate R² | MAE | Labeled test rows | Target coverage |','|---|---:|---|---:|---:|---:|---:|']
    def fmt(v):return 'unavailable' if pd.isna(v) else f'{v:.3f}'
    for axis in ['future_time','unseen_area','future_unseen_area']:
        for horizon in [0,15,30,60,120]:
            for model in ['time_week','boosted']:
                q=r[(r.axis==axis)&(r.horizon==horizon)&(r.target=='occupancy_rate')&(r.model==model)]
                if len(q):
                    q=q.iloc[0];lines.append(f"| {axis} | {horizon} | {model} | {fmt(q.get('r2'))} | {fmt(q.get('mae'))} | {q['n']} | {fmt(q.get('label_coverage_fraction'))} |")
    lines+=['','MAE is in occupancy-fraction units. Target coverage is the fraction of candidate face-times with sufficient reconstructed sensor-time; scores are conditional on those labels. Unknown intervals are not vacant intervals. No fixed R² target applies; earlier rough ranges were speculative, not measured benchmarks.','',
        '| Test | Lead | Complete panel N | Panel count R² | Panel count MAE | Panel vacancy Brier | Log loss | Regression range coverage | Mean range width |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for axis in ['future_time','unseen_area','future_unseen_area']:
        for h in [0,15,30,60,120]:
            q=r[(r.axis==axis)&(r.horizon==h)&(r.model=='boosted')].set_index('target')
            if 'available_count' not in q.index:continue
            c=q.loc['available_count'];p=q.loc['any_panel_vacant']
            lines.append(f"| {axis} | {h} | {c['n']} | {fmt(c.get('r2'))} | {fmt(c.get('mae'))} | {fmt(p.get('brier_score'))} | {fmt(p.get('log_loss'))} | {fmt(c.get('interval_coverage'))} | {fmt(c.get('interval_mean_width'))} |")
    lines+=['','Count labels require every member of the fixed sensor panel to be reconstructed as known at the target point. They are **not** full-block counts. The binary target is any vacant member of that panel, fit directly, without an independence assumption or conversion from expected occupancy. It is a derived sensor-state proxy, not a verified suitable-space outcome.','',
        'Prediction ranges use calibration-period absolute residuals (nominal 90%). Empirical coverage/width are reported; temporal dependence, missingness selection and domain shift mean nominal coverage is not guaranteed. Probability calibration uses separate calibration labels; reliability plots include bin counts in results.json.','',
        '## Feature-family ablations','', '| Test | Lead | Feature set | Rate R² | MAE |','|---|---:|---|---:|---:|']
    for _,a in ablations.iterrows():lines.append(f"| {a['axis']} | {a['horizon']} | {a['family_variant']} | {fmt(a.get('r2'))} | {fmt(a.get('mae'))} |")
    lines+=['','The retrospective context ablation uses October 2026 building/business/curb/meter snapshots. It is explicitly excluded from historically available feature claims. Housing/vehicles, fine-grained employment, opening hours, historical weather forecasts, reliable event attendance, complete restrictions, transit and closures remain unavailable or lack verified as-of joins. No zero-valued substitutes were used.','',
        '## Supported claims and limits','',
        '- Reproducible time-weighted sensor-panel reconstruction, causal recent-state features, trained models and held-out diagnostics are supported.',
        '- Absolute performance on the reconstructed metered panel is conditional on freshness/coverage assumptions. It is not independently verified sensor accuracy.',
        '- Sensor identity and block assignment use October 2026 meter/geometry snapshots, and historical ingestion times are absent. All experiments are retrospective; immediate event delivery is an explicit assumption.',
        '- No unmetered/residential occupancy accuracy, legal duration suitability, total eligible capacity, or validated citywide accuracy is supported.',
        '- Advanced transition/state-space models are deferred: the large unknown gaps and unverified event delivery do not yet establish reliable transitions that would resolve the demonstrated geographic transfer gap.',
        '- Before numerical user predictions: verify historical/current mapping, inventory capacity and full-stay rules, collect random/repeated independent counts, validate sensor assumptions, improve missing source vintages, and repeat prospective time/area validation.','',
        'Artifacts: metrics.csv, results.json (strata/reliability), rolling_validation.json, ablations.json, label_manifest.json, feature_catalog.json, forecast_examples.jsonl and artifacts/models/*.joblib. No purchase or public deployment.']
    sensitivity_path=out/'persistence_sensitivity.json'
    if sensitivity_path.exists():
        lines+=['','## Persistence-policy sensitivity','','Same fixed model, common labelled final-test rows; changing the label reconstruction is not independent sensor validation.','', '| Horizon | Cap (min) | Paired N | Proxy rate R² | MAE |','|---|---:|---:|---:|---:|']
        for s in json.loads(sensitivity_path.read_text()):lines.append(f"| {s['horizon_minutes']} | {s['persistence_minutes']} | {s['n']} | {fmt(s.get('r2'))} | {fmt(s.get('mae'))} |")
    (out/'results_report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return city_summary
