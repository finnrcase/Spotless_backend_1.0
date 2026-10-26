"""Observed suitable-space calibration and matched recommendation comparisons.

This module does not train, select models, open default observation stores or
estimate counterfactual search times. Simulation/fixture reports remain labeled.
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
import numpy as np
import pandas as pd
from .contracts import ManualObservation
from .product_contracts import SuitabilityReview,ProductForecast,RankingDecision,EvaluationManifest
from .evaluation import probability_metrics,regression_metrics

PROFILE=['vehicle_class','permit_class','intended_duration_minutes']


def settings():return json.loads(Path('config/product_pilot.json').read_text())
def stamp(value):
    t=pd.Timestamp(value)
    if pd.isna(t) or t.tzinfo is None:raise ValueError('Aware UTC/offset timestamps required')
    return t.tz_convert('UTC')
def profile(row):return tuple(row.get(k) for k in PROFILE)
def block(face):return face.rsplit(':',1)[0]


def guard_manifest(manifest,now=None):
    m=EvaluationManifest.model_validate(manifest);now=stamp(now or datetime.now(timezone.utc))
    if m.data_kind=='synthetic_demo':return m
    from .sensor_capture import reservation_windows
    windows=reservation_windows()+[{'start_local':settings()['start_local'],'end_local':settings()['end_local']}]
    if m.phase=='development':
        for w in windows:
            a=pd.Timestamp(w['start_local'],tz='America/Los_Angeles');b=pd.Timestamp(w['end_local'],tz='America/Los_Angeles')
            if m.evaluation_start_utc<b and m.evaluation_end_utc>a:raise ValueError('Reserved outcomes cannot be opened for development')
    else:
        if now<stamp(m.evaluation_end_utc):raise ValueError('Prospective evaluation period has not ended')
        lock=json.loads(Path(m.freeze_file).read_text())
        if stamp(lock['frozen_at_utc'])>=stamp(m.evaluation_start_utc):raise ValueError('Models must be frozen before evaluation starts')
        if hashlib.sha256(Path('config/product_pilot.json').read_bytes()).hexdigest()!=lock['config_sha256']:raise ValueError('Pilot protocol changed after freeze')
        if not lock.get('artifacts_sha256'):raise ValueError('No model/policy artifacts frozen')
        for p,digest in lock['artifacts_sha256'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen model/policy artifact changed')
    return m


def reserved_development(row):
    for name in ['config/field_holdouts.json','config/coverage_v4_field_holdouts.json']:
        p=Path(name)
        if p.exists():
            r=json.loads(p.read_text())
            if block(row['block_face_id']) in r['unseen_physical_blocks'] or row.get('survey_session_id') in r['reserved_session_ids'] or row.get('assignment_id') in r['reserved_assignment_ids']:return True
    from .sensor_capture import protected_period
    return protected_period(row['survey_start_utc'])


def reviewed_outcomes(observations,reviews,data_kind='observed'):
    """A positive can be witnessed on a partial face; zero needs full coverage.

    Binary evidence needs no invented capacity denominator. Regression remains
    gated on complete counts and separately reviewed capacity.
    """
    by_id={};rejected=[]
    for raw in reviews:
        r=SuitabilityReview.model_validate(raw)
        if r.observation_id in by_id:raise ValueError('Duplicate product review ID')
        by_id[r.observation_id]=r
    output={};seen=set();cfg=settings()
    for raw in observations:
        intake_fields={'location_review_required','label_review_required','bay_review_required','previous_link_review_required'}
        if set(raw)-set(ManualObservation.model_fields)-intake_fields:raise ValueError('Unexpected observation fields; preserve the documented intake schema')
        payload={k:v for k,v in raw.items() if k in ManualObservation.model_fields}
        if isinstance(payload.get('field_provenance'),str):payload['field_provenance']=json.loads(payload['field_provenance'])
        o=ManualObservation.model_validate(payload);oid=o.observation_id
        if oid in seen:raise ValueError('Duplicate direct observation ID')
        seen.add(oid);r=by_id.get(oid);reason=None
        if data_kind=='observed' and o.source_id not in ['manual_phone','manual_field','manual_map_ui','reviewed_survey']:reason='Only direct human observations may supply suitable-space truth'
        elif not r:reason='No independent suitability review'
        elif not (r.counts_verified and r.location_verified and r.full_stay_rules_verified):reason='Count/location/full-stay review incomplete'
        elif not (r.posted_sign_coverage_verified or r.official_rule_coverage_verified):reason='Rule evidence source unverified'
        elif r.eligibility_status in ['unknown','conflict']:reason='Eligibility unresolved'
        elif tuple(getattr(o,k) for k in PROFILE)!=tuple(getattr(r,k) for k in PROFILE):reason='Review profile/stay mismatch'
        elif not o.rules_checked:reason='Observer did not check rules'
        elif o.parking_type not in ['metered','unmetered']:reason='Parking population unknown/mixed'
        elif o.vacant_legal is None:reason='Suitable vacancy count missing'
        elif o.vacant_legal==0 and (not o.complete_face or not r.complete_face_visibility_verified or (o.obstructed_curb_length_m or 0)>0):reason='Partial/unverified visibility cannot prove no suitable space'
        elif r.eligibility_status=='prohibited' and o.vacant_legal>0:reason='Prohibited profile conflicts with positive suitable count'
        elif r.reviewed_at_utc<max(o.retrieved_at_utc,o.survey_end_utc):reason='Review precedes actual receipt/observation'
        elif r.rules_valid_from_utc>o.survey_start_utc or r.rules_valid_to_utc<o.survey_end_utc+timedelta(minutes=o.intended_duration_minutes):reason='Restrictions not verified for the full intended stay'
        elif (o.survey_end_utc-o.survey_start_utc).total_seconds()>cfg['maximum_label_sweep_minutes']*60:reason='Arrival label sweep too long; temporal uncertainty retained'
        if reason:rejected.append({'observation_id':oid,'reason':reason});continue
        row=o.model_dump(mode='json');row.update(block_id=block(o.block_face_id),at_least_one=int(o.vacant_legal>0),
            occupancy_rate=o.occupied/o.surveyed_capacity if r.capacity_verified and r.complete_face_visibility_verified and o.complete_face and o.surveyed_capacity else None,
            suitable_count=o.vacant_legal if o.complete_face and r.complete_face_visibility_verified else None,label_available_at_utc=r.reviewed_at_utc.isoformat(),label_scope='direct_reviewed_block_face',
            capacity_reviewed=r.capacity_verified,eligibility_status=r.eligibility_status,official_rule_coverage_verified=r.official_rule_coverage_verified,posted_sign_coverage_verified=r.posted_sign_coverage_verified)
        row['complete_visibility_reviewed']=r.complete_face_visibility_verified
        output[oid]=row
    if set(by_id)-seen:raise ValueError('Review refers to unknown observation IDs')
    return output,rejected


def matches_arrival(row,arrival,context):
    if profile(row)!=profile(context):return False
    a=stamp(row['survey_start_utc']);b=stamp(row['survey_end_utc']);t=stamp(arrival)
    return abs((t-(a+(b-a)/2)).total_seconds())<=settings()['arrival_tolerance_minutes']*60


def historical_probability(train,context,arrival,issue,face=None):
    local=stamp(arrival).tz_convert('America/Los_Angeles');same=[];pool=[];face_values=[]
    for r in train:
        if profile(r)!=profile(context) or r['parking_type']!=context['parking_type'] or stamp(r['label_available_at_utc'])>=stamp(issue):continue
        pool.append(r['at_least_one']);t=stamp(r['survey_start_utc']).tz_convert('America/Los_Angeles')
        if face==r['block_face_id']:face_values.append(r['at_least_one'])
        if t.dayofweek==local.dayofweek and t.hour==local.hour and (face is None or face==r['block_face_id']):same.append(r['at_least_one'])
    if not pool:return None
    prior=float(np.mean(pool))
    if face_values:prior=(sum(face_values)+5*prior)/(len(face_values)+5)
    return (sum(same)+5*prior)/(len(same)+5)


def evaluate(observations,reviews,forecasts,decisions,manifest,now=None):
    m=guard_manifest(manifest,now);allowed=set(m.train_ids+m.evaluation_ids)
    if {r['observation_id'] for r in observations}-allowed:raise ValueError('Only explicitly declared observation IDs may be opened')
    outcomes,rejected=reviewed_outcomes(observations,reviews,m.data_kind)
    train=[outcomes[i] for i in m.train_ids if i in outcomes];test=[outcomes[i] for i in m.evaluation_ids if i in outcomes]
    if m.data_kind=='observed':
        for row in list(outcomes.values()):
            if (row['observation_id'] in m.train_ids or m.phase=='development') and reserved_development(row):raise ValueError('Reserved block/session/period entered model development')
    for row in test:
        if not stamp(m.evaluation_start_utc)<=stamp(row['survey_start_utc'])<stamp(m.evaluation_end_utc):raise ValueError('Outcome outside declared evaluation period')
    if train and max(stamp(r['label_available_at_utc']) for r in train)+pd.Timedelta(minutes=settings()['historical_embargo_minutes'])>=stamp(m.evaluation_start_utc):raise ValueError('Training review availability crosses evaluation embargo')
    if m.axis=='unseen_block' and {r['block_id'] for r in train}&{r['block_id'] for r in test}:raise ValueError('Whole physical blocks leak into unseen-block evaluation')
    if m.axis=='future_time' and not {r['block_id'] for r in test}.issubset({r['block_id'] for r in train}):raise ValueError('Future-time evaluation must revisit known blocks')
    fs={};seen_obs=set()
    for raw in forecasts:
        f=ProductForecast.model_validate(raw)
        if f.prediction_id in fs or f.observation_id in seen_obs:raise ValueError('Duplicate forecast ID/target; compare model versions in separate runs')
        if f.observation_id not in m.evaluation_ids:raise ValueError('Forecast target is not declared for evaluation')
        fs[f.prediction_id]=f;seen_obs.add(f.observation_id)
    forecast_by_obs={f.observation_id:f for f in fs.values()};metrics={};unmatched=[]
    if len({f.model_version for f in fs.values()})>1:raise ValueError('Compare model versions in separate runs on identical targets')
    for population in ['metered','unmetered']:
        group=[r for r in test if r['parking_type']==population];paired=[];reg=[];counts=[]
        for r in group:
            f=forecast_by_obs.get(r['observation_id'])
            if not f:continue
            if f.block_face_id!=r['block_face_id'] or not matches_arrival(r,f.arrival_at_utc,f.model_dump()):unmatched.append(r['observation_id']);continue
            if f.issued_at_utc>stamp(r['survey_start_utc']):raise ValueError('Forecast issued after target observation began')
            if f.evidence_scope=='direct_suitable_model' and f.probability_suitable is not None:paired.append((r,f))
            if f.evidence_scope=='direct_suitable_model' and f.predicted_occupancy_rate is not None and r['occupancy_rate'] is not None:reg.append((r,f))
            if f.evidence_scope=='direct_suitable_model' and f.predicted_suitable_count is not None and r['suitable_count'] is not None:counts.append((r,f))
        y=[r['at_least_one'] for r,f in paired];p=[f.probability_suitable for r,f in paired]
        hist=[historical_probability(train,r,f.arrival_at_utc,f.issued_at_utc) for r,f in paired];common=[i for i,v in enumerate(hist) if v is not None]
        reg_means=[];reg_actual=[];reg_model=[]
        for r,f in reg:
            historical=[t['occupancy_rate'] for t in train if t['parking_type']==population and profile(t)==profile(r) and t['occupancy_rate'] is not None and stamp(t['label_available_at_utc'])<stamp(f.issued_at_utc)]
            if historical:reg_means.append(float(np.mean(historical)));reg_actual.append(r['occupancy_rate']);reg_model.append(f.predicted_occupancy_rate)
        metrics[population]={'reviewed_targets':len(group),'declared_targets_all_populations':len(m.evaluation_ids),'suitable_probability':probability_metrics(y,p),
            'prediction_coverage':len(paired)/len(group) if group else None,'historical_baseline':probability_metrics([y[i] for i in common],[hist[i] for i in common]),
            'model_on_historical_common_rows':probability_metrics([y[i] for i in common],[p[i] for i in common]),
            'historical_baseline_coverage':len(common)/len(paired) if paired else None,
            'occupancy_regression':regression_metrics([r['occupancy_rate'] for r,f in reg],[f.predicted_occupancy_rate for r,f in reg]),
            'occupancy_historical_mean_baseline':regression_metrics(reg_actual,reg_means),'occupancy_model_on_baseline_common_rows':regression_metrics(reg_actual,reg_model),
            'suitable_count_regression':regression_metrics([r['suitable_count'] for r,f in counts],[f.predicted_suitable_count for r,f in counts]),
            'blocks':len({r['block_id'] for r in group}),'sessions':len({r.get('survey_session_id') for r in group}),
            'evidence_age_minutes':[float((stamp(f.issued_at_utc)-stamp(f.evidence_at_utc)).total_seconds()/60) for r,f in paired if f.evidence_at_utc]}
    for raw in decisions:
        d=RankingDecision.model_validate(raw)
        if not m.evaluation_start_utc<=d.arrival_at_utc<m.evaluation_end_utc:raise ValueError('Ranking decision outside declared evaluation period')
    rank=ranking_evaluation(decisions,fs,outcomes,train,set(m.evaluation_ids))
    return {'status':'synthetic_demonstration' if m.data_kind=='synthetic_demo' else 'observed_exploratory' if test else 'unavailable',
        'data_kind':m.data_kind,'axis':m.axis,'phase':m.phase,'metrics':metrics,'ranking':rank,'rejected_labels':rejected,'unmatched_forecast_targets':unmatched,
        'declared_evaluation_rows':len(m.evaluation_ids),'missing_or_unreviewed_rows':len(m.evaluation_ids)-len(test),
        'capacity_diagnostics':{'reviewed_targets':len(test),'physical_capacity_unknown':sum(r.get('physical_capacity') is None for r in test),
            'eligible_capacity_unknown':sum(r.get('eligible_capacity') is None for r in test),'regression_capacity_unreviewed':sum(not r['capacity_reviewed'] for r in test),
            'physical_vs_surveyed_disagreements':sum(r.get('physical_capacity') is not None and r.get('surveyed_capacity') is not None and r['physical_capacity']!=r['surveyed_capacity'] for r in test)},
        'occupancy_models_retrained':False,'search_time_reduction':None,'search_time_note':'Offline matched face outcomes cannot identify actual search-time effects.',
        'uncertainty_note':'Repeated snapshots and selected routes are dependent; calibration bins/counts are descriptive. No citywide or unmetered transfer claim.'}


def eligible(candidate,decision):
    c=candidate;d=decision;end=d.arrival_at_utc+timedelta(minutes=d.intended_duration_minutes)
    return (c.eligibility_status=='allowed' and c.walking_distance_m<=d.maximum_walking_distance_m and
        c.eligibility_checked_at_utc is not None and c.eligibility_checked_at_utc<=d.issued_at_utc and
        (c.official_rule_coverage_verified or c.posted_sign_coverage_verified) and
        c.rules_valid_from_utc is not None and c.rules_valid_from_utc<=d.arrival_at_utc and c.rules_valid_to_utc is not None and c.rules_valid_to_utc>=end and
        (d.maximum_price_per_hour is None or c.price_per_hour is not None and c.price_per_hour<=d.maximum_price_per_hour))


def ranking_evaluation(decisions,forecasts,outcomes,train,evaluation_ids):
    policies=['app_policy','nearest_eligible','historical'];rows=[];seen=set();counts={p:0 for p in policies};supported_decisions=0
    for raw in decisions:
        d=RankingDecision.model_validate(raw)
        if d.decision_id in seen:raise ValueError('Duplicate ranking decision ID')
        seen.add(d.decision_id);candidates=[c for c in d.candidates if eligible(c,d)]
        def price(c):return c.price_per_hour if d.prefer_lower_price and c.price_per_hour is not None else float('inf') if d.prefer_lower_price else 0
        def distance(c):return c.walking_distance_m,price(c),c.block_face_id
        supported=[];history=[]
        for c in candidates:
            f=forecasts.get(c.prediction_id)
            if f and (f.block_face_id!=c.block_face_id or f.observation_id!=c.observation_id or f.arrival_at_utc!=d.arrival_at_utc or f.issued_at_utc>d.issued_at_utc or profile(f.model_dump())!=profile(d.model_dump())):raise ValueError('Ranking forecast face/time/profile mismatch')
            if f and f.evidence_scope=='direct_suitable_model' and f.probability_suitable is not None:supported.append((c,f.probability_suitable))
            context={**d.model_dump(),'parking_type':c.parking_type}
            probability=historical_probability(train,context,d.arrival_at_utc,d.issued_at_utc,c.block_face_id)
            if probability is not None:history.append((c,probability))
        nearest=min(candidates,key=distance) if candidates else None
        if supported:supported_decisions+=1
        selected={'nearest_eligible':nearest,
            'app_policy':min(supported,key=lambda pair:(-pair[1],*distance(pair[0])))[0] if supported else nearest,
            'historical':min(history,key=lambda pair:(-pair[1],*distance(pair[0])))[0] if history else None}
        row={'decision_id':d.decision_id,'candidate_set_complete':d.candidate_set_complete,'candidate_faces':len(d.candidates),'eligible_faces':len(candidates),
            'app_ranking_basis':'supported_suitable_probability' if supported else 'nearest_eligible_fallback_no_probability','policies':{}}
        for name,c in selected.items():
            if c is not None:counts[name]+=1
            outcome=outcomes.get(c.observation_id) if c else None
            if c and c.observation_id and c.observation_id not in evaluation_ids:raise ValueError('Ranking references non-evaluation outcome')
            valid=bool(outcome and outcome['block_face_id']==c.block_face_id and matches_arrival(outcome,d.arrival_at_utc,d.model_dump()))
            row['policies'][name]={'face_id':c.block_face_id if c else None,'success':outcome['at_least_one'] if valid else None,'walking_distance_m':c.walking_distance_m if c else None,'observed_outcome':valid}
        rows.append(row)
    common=[r for r in rows if all(v['observed_outcome'] for v in r['policies'].values()) and r['candidate_set_complete']]
    summary={}
    for policy in policies:
        y=[r['policies'][policy]['success'] for r in common]
        summary[policy]={'paired_decisions':len(common),'top1_observed_success':float(np.mean(y)) if y else None,
            'mean_walking_distance_m':float(np.mean([r['policies'][policy]['walking_distance_m'] for r in common])) if common else None,
            'recommendation_coverage':counts[policy]/len(rows) if rows else None}
    return {'decisions':len(rows),'supported_probability_decisions':supported_decisions,'fully_paired_complete_candidate_decisions':len(common),'unpaired_or_incomplete_decisions':len(rows)-len(common),'policies':summary,
        'decision_audit':rows,'search_time_reduction':None,'note':'Same candidate sets and observed selected outcomes only. Missing counterfactual labels remain missing; walking distance is an input estimate, not measured walking time.'}


def write_report(report,output):
    p=Path(output);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8')
    return report


def run(manifest_path,observations_path,reviews_path,forecasts_path,decisions_path=None,output='reports/product/evaluation.json'):
    manifest=json.loads(Path(manifest_path).read_text());m=guard_manifest(manifest) # Before opening any outcome file.
    def jsonl(path):
        if not path:return []
        p=Path(path)
        if p.stat().st_size>5_000_000:raise ValueError('Product evaluation import exceeds 5 MB; use a bounded explicit cohort')
        return [json.loads(line) for line in p.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    ids=set(m.train_ids+m.evaluation_ids)
    if str(observations_path).endswith('.parquet'):
        if m.data_kind=='observed':
            metadata=pd.read_parquet(observations_path,columns=['observation_id','block_face_id','survey_start_utc','survey_session_id','assignment_id'],filters=[('observation_id','in',list(ids))])
            for r in metadata.to_dict('records'):
                if (r['observation_id'] in m.train_ids or m.phase=='development') and reserved_development(r):raise ValueError('Reserved cohort rejected before loading occupancy outcomes')
        frame=pd.read_parquet(observations_path,filters=[('observation_id','in',list(ids))]);observations=json.loads(frame.to_json(orient='records',date_format='iso'))
        # New optional fields may be null on older rows after a Parquet union.
        defaults=ManualObservation.model_fields
        observations=[{k:v for k,v in r.items() if v is not None or k not in defaults or defaults[k].default is None} for r in observations]
    else:observations=jsonl(observations_path)
    if any(r['observation_id'] not in ids for r in observations):raise ValueError('Export only the frozen declared cohort; do not open unrelated holdouts')
    return write_report(evaluate(observations,jsonl(reviews_path),jsonl(forecasts_path),jsonl(decisions_path),manifest),output)
