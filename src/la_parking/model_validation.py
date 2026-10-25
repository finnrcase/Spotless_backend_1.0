"""Sensor-policy sensitivity and executable validation beyond estimator metrics."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .labels import interval_panel
from .evaluation import regression_metrics


def sensitivity():
    cfg=json.loads(Path('config/modeling.json').read_text())
    events=pd.read_parquet('data/processed/pilot_history_2026_08.parquet')
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet')
    predictions=pd.read_parquet('data/modeling/test_predictions.parquet')
    predictions=predictions.loc[(predictions.axis=='future_time')&(predictions.model=='boosted')&(predictions.target=='occupancy_rate')]
    labels=[]
    for cap in cfg['persistence_caps_minutes']:
        frame,_=interval_panel(events,mapping,pd.Timestamp('2026-08-08',tz='America/Los_Angeles'),pd.Timestamp('2026-09-01',tz='America/Los_Angeles'),cfg['interval_minutes'],cap,pd.Timestamp('2026-08-08',tz='America/Los_Angeles'))
        frame=frame.loc[frame.coverage_fraction.ge(cfg['minimum_known_sensor_time_fraction'])]
        labels.append(frame[['block_face_id','interval_start_utc','occupancy_rate']].rename(columns={'occupancy_rate':f'rate_{cap}'}))
    common=labels[0]
    for label in labels[1:]: common=common.merge(label,on=['block_face_id','interval_start_utc'],how='inner',validate='one_to_one')
    joined=predictions.merge(common,left_on=['block_face_id','arrival_time_utc'],right_on=['block_face_id','interval_start_utc'],how='inner',validate='many_to_one')
    metrics=[]
    for horizon,g in joined.groupby('horizon_minutes'):
        for cap in cfg['persistence_caps_minutes']:
            metrics.append({'horizon_minutes':int(horizon),'persistence_minutes':cap,'scope':'common labeled test rows; fixed primary model, no retuning',**regression_metrics(g[f'rate_{cap}'],g.prediction)})
    Path('reports/modeling/persistence_sensitivity.json').write_text(json.dumps(metrics,indent=2))
    return metrics


def audit_artifacts():
    cfg=json.loads(Path('config/modeling.json').read_text());d=pd.read_parquet('data/modeling/design.parquet')
    p=pd.read_parquet('data/modeling/test_predictions.parquet')
    protocol=json.loads(Path('reports/modeling/experiment_protocol.json').read_text())
    import hashlib
    assert hashlib.sha256(Path('data/modeling/design.parquet').read_bytes()).hexdigest()==protocol['design_sha256']
    assert (d.feature_available_at_utc<=d.issued_at_utc).all()
    assert (d.roster_available_at_utc<=d.issued_at_utc).all()
    assert not d.full_curb_label.any()
    for horizon,g in p.loc[p.axis=='future_time'].groupby('horizon_minutes'):
        assert g.issued_at_utc.min()>=pd.Timestamp(cfg['final_test_start_local'],tz='America/Los_Angeles').tz_convert('UTC')
    split=json.loads(Path('reports/modeling/spatial_split.json').read_text())
    assert not set(split['train_blocks'])&set(split['test_blocks'])
    spatial=p.loc[p.axis=='unseen_area']
    assert set(spatial.block_id).issubset(set(split['test_blocks']))
    examples=[json.loads(s) for s in Path('reports/modeling/forecast_examples.jsonl').read_text().splitlines()]
    assert all(r['probability_at_least_one'] is None and r['expected_available_spaces'] is None for r in examples)
    catalog=json.loads(Path('artifacts/models/catalog.json').read_text())
    from .model_features import CONTEXT
    assert all(not set(r['features'])&set(CONTEXT) for r in catalog)
    audit={'source_fingerprint_matched':True,'event_feature_asof_checks_passed':True,'historical_geometry_verified':False,'event_delivery_latency_verified':False,'retrospective_only':True,'spatial_overlap_blocks':0,'full_curb_labels':0,
        'model_files':len(list(Path('artifacts/models').glob('*.joblib'))),'forecast_examples':len(examples),'user_facing_suitability_values':0,'population':'metered sensor panels only','unmetered_test_r2':None}
    Path('reports/modeling/validation.json').write_text(json.dumps(audit,indent=2))
    baseline=Path('reports/modeling/initial_rate_results.json')
    if baseline.exists():
        old=json.loads(baseline.read_text());new=json.loads(Path('reports/modeling/results.json').read_text())
        def keyed(rows):return {(r['axis'],r['horizon'],r['model']):(r.get('r2'),r.get('mae')) for r in rows if r['target']=='occupancy_rate'}
        assert keyed(old)==keyed(new),'Rate specifications/results changed after the preliminary inspection'
        audit['rate_results_unchanged_after_count_correction']=True
        Path('reports/modeling/validation.json').write_text(json.dumps(audit,indent=2))
    return audit
