"""Read-only evidence summaries; experimental validation never enables forecasts."""
import json
from pathlib import Path


def summary(root):
    root=Path(root)
    def read(name,default):
        path=root/name
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else default
    temporal=read('reports/modeling/temporal_v2_results.json',[])
    spatial=read('reports/modeling/spatial_v3_results.json',[])
    known=[r for r in temporal if r['horizon']==60 and r['axis']=='future_time_known' and r['target']=='occupancy_rate' and r.get('validation_rmse') is not None]
    best=min(known,key=lambda r:r['validation_rmse']) if known else None
    new=[r for r in spatial if r['axis']=='future_time_unseen' and r['target']=='occupancy_rate' and r['validation_selected_primary']]
    cfg=read('config/spatial_v3.json',{})
    unmetered=read('reports/unmetered/comparison.json',{})
    unmetered_n=int(unmetered.get('reviewed_unmetered_test_labels',0))
    if unmetered.get('status')=='evaluated_on_held_out_unmetered_only':
        unmetered_n=sum(int(v.get('unmetered_only',{}).get('occupancy_rate',{}).get('n',0)) for v in unmetered.get('comparisons',{}).values())
    return {'citywide_accuracy_validated':False,'known_blocks':{'status':'legacy_metered_panel_benchmark' if best else 'not_run','r2':best['r2'] if best else None,'n':best['n'] if best else 0,'blocks':best['blocks'] if best else 0},
        'unseen_blocks':{'status':'experimental_not_activated','r2':new[0]['r2'] if new else None,'n':new[0]['n'] if new else 0,'production_numeric_predictions_enabled':False},
        'unmetered':{'status':unmetered.get('status','awaiting_direct_reviewed_occupancy_labels'),'reviewed_test_n':unmetered_n,'r2':None,'mae':None,'suitable_space_probability_calibration':None},
        'restrictions':{'status':'posted_sign_and_full_stay_review_required','unknown_rules_mean_unrestricted':False,'legal_capacity':None},
        'holdouts':{k:v for k,v in cfg.items() if k in ['new_untouched_archive_holdout','new_untouched_manual_holdout']},
        'sensor_expiry_minutes':15,'sensor_semantics':'Change-event interpretation plausible; heartbeat cadence, outages and historical delivery remain unverified. Polling does not renew event evidence age.',
        'geographic_coverage':'Observed metered sensor panels in a small Westwood subset; other neighborhoods and unmetered forecasts unsupported.'}
