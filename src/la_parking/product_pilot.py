"""Local prospective trial ledger and capacity audit; no performance invented."""
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from .product_contracts import PilotTrial,PRODUCT_MODELS
from .product_evaluation import settings,stamp,reviewed_outcomes,matches_arrival,write_report
from .evaluation import probability_metrics


def assignments():
    cfg=settings();rng=np.random.default_rng(cfg['allocation_seed']);rows=[]
    for day in ['2026-11-23','2026-11-25','2026-11-27','2026-11-30','2026-12-02','2026-12-04']:
        for hour in [9,14]:
            arms=list(rng.permutation(cfg['arms']));session=f'product-{day}-{hour:02d}'
            for index,arm in enumerate(arms):
                t=pd.Timestamp(f'{day} {hour:02d}:00',tz='America/Los_Angeles')+pd.Timedelta(minutes=index*30)
                rows.append({'trial_id':f'product-v1-{len(rows)+1:03d}','assigned_arm':str(arm),'session_id':session,'planned_local':t.isoformat(),
                    'planned_utc':t.tz_convert('UTC').isoformat(),'status':'planned_not_observed'})
    return rows


def prepare(output='reports/product'):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);plan=assignments()
    (out/'pilot_assignments.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf8');pd.DataFrame(plan).to_csv(out/'pilot_assignments.csv',index=False)
    template=Path('web/product_pilot.html').read_text(encoding='utf8');(out/'pilot.html').write_text(template.replace('/*__PLAN__*/',json.dumps(plan).replace('<','\\u003c')),encoding='utf8')
    for cls in PRODUCT_MODELS:
        target=Path('schemas')/f'{cls.__name__}.schema.json';target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(cls.model_json_schema(),indent=2)+'\n',encoding='utf8')
    return readiness(out)


def capacity_audit(output='reports/product/capacity_audit.json'):
    path=Path('data/processed/curb_inventory.parquet');audit={'status':'unavailable','occupancy_labels_read':0,'historic_curb_polygons_are_stalls':False}
    if path.exists():
        f=pd.read_parquet(path);physical=pd.to_numeric(f.physical_capacity,errors='coerce');eligible=pd.to_numeric(f.eligible_capacity,errors='coerce')
        audit.update(status='audited_local_inventory',faces=len(f),physical_capacity_known=int(physical.notna().sum()),eligible_capacity_known=int(eligible.notna().sum()),
            invalid_capacity_rows=int((physical.lt(0)|eligible.lt(0)|(eligible.gt(physical)&physical.notna())).sum()),
            complete_exclusions=int(f.exclusions_complete.eq(True).sum()),methods=f.capacity_method.value_counts().to_dict(),
            supply_note='Surveyed positions are an observation denominator, not automatically physical or time/profile-eligible capacity. Meter roster size is partial instrument coverage, not curb supply. Historic curb polygons and centerline length do not establish legal stalls.')
    return write_report(audit,output)


def readiness(output='reports/product'):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    report={'status':'awaiting_direct_reviewed_suitability_outcomes_and_frozen_product_model','observed_suitable_test_rows_scored':0,'observed_trials_scored':0,
        'occupancy_r2':None,'occupancy_mae':None,'suitable_probability_brier':None,'suitable_probability_ece':None,'ranking_top1_success':None,
        'arrival_success':None,'search_minutes':None,'search_time_reduction':None,'walking_minutes':None,
        'planned_trials':len(assignments()),'planned_snapshots_are_labels':False,'planning_goals_only':settings()['planning_goals_only'],
        'planning_goals_are_results_or_thresholds':False,'untouched_outcomes_opened':False,'production_models_changed':False,
        'reason':'Readiness does not open local observation/trial stores. Use explicit reviewed cohorts and locked prospective release; no suitable-space model or product outcome is validated.'}
    write_report(report,out/'readiness.json')
    (out/'readiness.md').write_text('# Product pilot readiness\n\nAll product outcome metrics are **unavailable**. No direct reviewed suitability outcomes or trials were scored, no prospective data opened, and no occupancy model changed.\n\nThe local phone route supports 0/15/30/60 counts and observed movements. The pilot ledger has 24 planned randomized slots; planned slots are not outcomes. See docs/product_evaluation.md for review gates, matched ranking evaluation, clocks, censoring and locked release. Occupancy R² 0.50–0.70 and search-time reduction 20–30% are planning goals only.\n',encoding='utf8')
    capacity_audit(out/'capacity_audit.json');return report


def freeze(artifacts,output='data/product/pilot_freeze.json'):
    cfg=settings();start=pd.Timestamp(cfg['start_local'],tz='America/Los_Angeles');now=pd.Timestamp.now(tz='UTC')
    if now>=start:raise ValueError('Cannot retrospectively freeze this prospective period')
    p=Path(output)
    if p.exists():raise ValueError('Freeze already exists; do not overwrite a registered pilot')
    if not artifacts:raise ValueError('Freeze explicit model/policy artifacts before the trial period')
    hashes={str(path):hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in artifacts}
    plan=json.dumps(assignments(),sort_keys=True).encode()
    report={'version':cfg['version'],'frozen_at_utc':now.isoformat(),'config_sha256':hashlib.sha256(Path('config/product_pilot.json').read_bytes()).hexdigest(),
        'assignments_sha256':hashlib.sha256(plan).hexdigest(),'artifacts_sha256':hashes,'notes':'Locks policy/model bytes and allocation, not a claim of validated suitability performance.'}
    return write_report(report,p)


def read_jsonl(path):
    p=Path(path)
    if p.stat().st_size>5_000_000:raise ValueError('Trial batch exceeds 5 MB')
    return [json.loads(line) for line in p.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def intake(path,output='data/product/trials.jsonl'):
    p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);old=read_jsonl(p) if p.exists() else [];by_id={r['trial_id']:r for r in old};roster={r['trial_id']:r for r in assignments()}
    accepted=unchanged=0
    for raw in read_jsonl(path):
        t=PilotTrial.model_validate(raw);row=t.model_dump(mode='json')
        if t.trial_id not in roster or t.assigned_arm!=roster[t.trial_id]['assigned_arm']:raise ValueError('Trial ID/arm disagrees with frozen allocation')
        if t.data_kind!='observed':raise ValueError('Synthetic trials must remain isolated from the real local ledger')
        start=stamp(t.search_started_at_utc).tz_convert('America/Los_Angeles');cfg=settings()
        if not pd.Timestamp(cfg['start_local'],tz='America/Los_Angeles')<=start<pd.Timestamp(cfg['end_local'],tz='America/Los_Angeles'):raise ValueError('Actual trial is outside prospective period; preserve separately')
        if t.trial_id in by_id:
            if by_id[t.trial_id]!=row:raise ValueError('Conflicting trial ID; preserve both files and review explicitly')
            unchanged+=1;continue
        by_id[t.trial_id]=row;accepted+=1
    # All-or-nothing validation above; immutable originals remain on the device/export.
    temp=p.with_suffix('.partial');temp.write_text(''.join(json.dumps(r)+'\n' for r in by_id.values()),encoding='utf8');temp.replace(p)
    return {'accepted':accepted,'unchanged':unchanged,'review_required':True,'automatic_model_training':False}


def trial_metrics(trials,outcomes=None,data_kind='observed'):
    """Exploratory ITT with missing/censoring bounds; no success-only search mean."""
    roster={r['trial_id']:r for r in assignments()};parsed={};outcomes=outcomes or {};limit=settings()['search_limit_minutes']
    for raw in trials:
        t=PilotTrial.model_validate(raw)
        if t.data_kind!=data_kind:raise ValueError('Observed and synthetic trial results cannot be pooled')
        if t.trial_id in parsed or t.trial_id not in roster or t.assigned_arm!=roster[t.trial_id]['assigned_arm']:raise ValueError('Unknown/duplicate trial or altered random assignment')
        parsed[t.trial_id]=t
    arms={};calibration_pairs=[]
    for arm in settings()['arms']:
        slots=[r for r in roster.values() if r['assigned_arm']==arm];reviewed=[parsed[r['trial_id']] for r in slots if r['trial_id'] in parsed and parsed[r['trial_id']].verified]
        observed=[];lower=upper=0.;walk=[];success=[];censored=0
        for slot in slots:
            t=parsed.get(slot['trial_id'])
            if not t or not t.verified:upper+=limit;continue
            if t.arrival_success is not None:success.append(int(t.arrival_success))
            elapsed=(t.search_ended_at_utc-t.search_started_at_utc).total_seconds()/60
            if t.parked_at_utc:
                value=min(limit,(t.parked_at_utc-t.search_started_at_utc).total_seconds()/60);lower+=value;upper+=value;observed.append(value)
            elif elapsed>=limit:lower+=limit;upper+=limit;observed.append(float(limit));censored+=1
            else:lower+=elapsed;upper+=limit;censored+=1
            if t.destination_reached_at_utc:walk.append((t.destination_reached_at_utc-t.walk_started_at_utc).total_seconds()/60)
            outcome=outcomes.get(t.suitable_outcome_observation_id)
            if outcome and t.predicted_probability_suitable is not None and t.reached_recommended_face_at_utc and outcome['block_face_id']==t.recommended_face_id and matches_arrival(outcome,t.reached_recommended_face_at_utc,t.model_dump()):
                calibration_pairs.append((outcome['at_least_one'],t.predicted_probability_suitable))
        arms[arm]={'assigned_slots':len(slots),'reviewed_trials':len(reviewed),'missing_or_unreviewed':len(slots)-len(reviewed),'restricted_search_mean_minutes_observed':float(np.mean(observed)) if observed else None,
            'restricted_search_measured_n':len(observed),'censored_or_abandoned':censored,'restricted_search_bounds_all_assigned_minutes':[lower/len(slots),upper/len(slots)],
            'arrival_success_observed':float(np.mean(success)) if success else None,'arrival_success_n':len(success),
            'walking_mean_minutes_observed':float(np.mean(walk)) if walk else None,'walking_n':len(walk),
            'nonadherent_reviewed':sum(t.followed_assignment is False for t in reviewed),'adherence_unknown_reviewed':sum(t.followed_assignment is None for t in reviewed)}
    a,b=[arms[k] for k in ['app','nearest_eligible']];reduction=None
    if all(r['restricted_search_measured_n']==r['assigned_slots'] for r in [a,b]) and b['restricted_search_mean_minutes_observed']>0:
        reduction=1-a['restricted_search_mean_minutes_observed']/b['restricted_search_mean_minutes_observed']
    return {'status':'synthetic_demonstration' if data_kind=='synthetic_demo' else 'observed_exploratory' if parsed else 'unavailable',
        'data_kind':data_kind,'arms':arms,'relative_restricted_search_reduction':reduction,
        'suitable_probability_calibration':probability_metrics([y for y,p in calibration_pairs],[p for y,p in calibration_pairs]),
        'note':'Analyze assigned arms including nonadherence. Early abandonment is censored, not a completed successful search. Conditional means exclude missing followup and may be selected. Bounds include all 24 assigned slots; this exploratory sample cannot establish a 20–30% improvement.'}


def evaluate_trials(path,freeze_path,output='reports/product/trials_evaluation.json',observations=None,reviews=None):
    # Gate before reading any trial or direct-observation outcomes.
    from .product_contracts import EvaluationManifest
    from .product_evaluation import guard_manifest
    cfg=settings();manifest=EvaluationManifest(axis='future_time',phase='locked_test',train_ids=[],evaluation_ids=[],
        evaluation_start_utc=pd.Timestamp(cfg['start_local'],tz='America/Los_Angeles').to_pydatetime(),evaluation_end_utc=pd.Timestamp(cfg['end_local'],tz='America/Los_Angeles').to_pydatetime(),freeze_file=freeze_path)
    guard_manifest(manifest)
    lock=json.loads(Path(freeze_path).read_text())
    if hashlib.sha256(json.dumps(assignments(),sort_keys=True).encode()).hexdigest()!=lock['assignments_sha256']:raise ValueError('Random allocation changed after freeze')
    outcomes={}
    if observations or reviews:
        if not observations or not reviews:raise ValueError('Both direct outcomes and reviews are required for probability calibration')
        outcomes,_=reviewed_outcomes(read_jsonl(observations),read_jsonl(reviews))
    return write_report(trial_metrics(read_jsonl(path),outcomes),output)
