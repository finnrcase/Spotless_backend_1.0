"""Synthetic fixtures only; these values are never measured product performance."""
import copy
import json
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pytest
from la_parking.product_contracts import ProductForecast,PilotTrial
from la_parking.contracts import ManualObservation
from la_parking.product_evaluation import evaluate,reviewed_outcomes,guard_manifest
from la_parking.product_pilot import assignments,trial_metrics,intake,capacity_audit


def observation(oid,face='fixture-a:left',day=5,vacant=0):
    t=datetime(2026,10,day,12,tzinfo=timezone.utc)
    return dict(source_id='synthetic-test',source_record_id=oid,source_version='test-only',retrieved_at_utc=(t+timedelta(minutes=2)).isoformat(),
        field_provenance={},confidence=.3,observation_id=oid,block_face_id=face,observer_pseudonym='fixture',survey_session_id=f'fixture-{day}',
        survey_start_utc=t.isoformat(),survey_end_utc=(t+timedelta(minutes=2)).isoformat(),occupied=2,vacant_legal=vacant,unsuitable=2-vacant,surveyed_capacity=4,
        complete_face=True,location_method='confirmed_map_pin',gps_accuracy_m=None,latitude=34.06,longitude=-118.44,
        parking_type='unmetered',rules_checked=True,intended_duration_minutes=60,vehicle_class='standard_passenger',permit_class=None,capacity_basis='estimated_positions')


def review(o,**changes):
    t=datetime.fromisoformat(o['survey_start_utc'])
    return dict(observation_id=o['observation_id'],reviewed_by='fixture-reviewer',reviewed_at_utc=(t+timedelta(hours=2)).isoformat(),
        counts_verified=True,complete_face_visibility_verified=True,location_verified=True,full_stay_rules_verified=True,posted_sign_coverage_verified=True,official_rule_coverage_verified=False,
        capacity_verified=True,vehicle_class='standard_passenger',permit_class=None,intended_duration_minutes=60,
        rules_valid_from_utc=t.isoformat(),rules_valid_to_utc=(t+timedelta(hours=3)).isoformat(),eligibility_status='allowed',**changes)


def forecast(o,p=.2):
    t=datetime.fromisoformat(o['survey_start_utc'])
    return dict(prediction_id='pred-'+o['observation_id'],observation_id=o['observation_id'],block_face_id=o['block_face_id'],issued_at_utc=(t-timedelta(hours=1)).isoformat(),
        arrival_at_utc=(t+timedelta(minutes=1)).isoformat(),feature_available_at_utc=(t-timedelta(hours=1)).isoformat(),training_cutoff_utc='2026-10-02T00:00Z',evidence_at_utc=(t-timedelta(hours=3)).isoformat(),
        vehicle_class='standard_passenger',permit_class=None,intended_duration_minutes=60,model_version='synthetic-v1',evidence_scope='direct_suitable_model',
        probability_suitable=p,predicted_occupancy_rate=.5,predicted_suitable_count=p)


def fixture():
    train=[observation('synthetic-tr-a',day=1),observation('synthetic-tr-b','fixture-b:left',1,1)]
    test=[observation('synthetic-te-a'),observation('synthetic-te-b','fixture-b:left',5,1)]
    obs=train+test;pred=[forecast(test[0],.1),forecast(test[1],.8)]
    manifest=dict(axis='future_time',data_kind='synthetic_demo',train_ids=[o['observation_id'] for o in train],evaluation_ids=[o['observation_id'] for o in test],evaluation_start_utc='2026-10-05T00:00Z',evaluation_end_utc='2026-10-06T00:00Z')
    candidates=[dict(block_face_id=o['block_face_id'],observation_id=o['observation_id'],prediction_id=p['prediction_id'],walking_distance_m=50+index*50,parking_type='unmetered',
        eligibility_status='allowed',eligibility_checked_at_utc='2026-10-05T10:00Z',rules_valid_from_utc='2026-10-05T00:00Z',rules_valid_to_utc='2026-10-06T00:00Z',posted_sign_coverage_verified=True) for index,(o,p) in enumerate(zip(test,pred))]
    decision=dict(decision_id='synthetic-decision',issued_at_utc=pred[0]['issued_at_utc'],arrival_at_utc=pred[0]['arrival_at_utc'],intended_duration_minutes=60,vehicle_class='standard_passenger',permit_class=None,maximum_walking_distance_m=400,candidate_set_complete=True,candidates=candidates)
    return obs,[review(o) for o in obs],pred,[decision],manifest


def test_direct_suitability_and_regression_evaluation_preserves_matched_rows():
    report=evaluate(*fixture());m=report['metrics']['unmetered']
    assert report['status']=='synthetic_demonstration' and report['data_kind']=='synthetic_demo'
    assert m['suitable_probability']['n']==2 and m['occupancy_regression']['n']==2
    assert m['evidence_age_minutes']==[120.,120.]
    assert report['metrics']['metered']['suitable_probability']['n']==0 and report['search_time_reduction'] is None
    rank=report['ranking'];assert rank['fully_paired_complete_candidate_decisions']==1
    assert rank['policies']['app_policy']['top1_observed_success']==1
    assert rank['policies']['nearest_eligible']['top1_observed_success']==0
    assert rank['policies']['historical']['top1_observed_success']==1


def test_meter_proxy_cannot_become_whole_face_suitable_probability():
    o=observation('synthetic');p=forecast(o);p['evidence_scope']='meter_panel_proxy'
    with pytest.raises(ValueError,match='Meter-panel'):ProductForecast.model_validate(p)
    p['probability_suitable']=None;p['predicted_suitable_count']=None
    assert ProductForecast.model_validate(p).probability_suitable is None


def test_partial_positive_is_evidence_but_partial_zero_is_unknown():
    positive=observation('synthetic-positive',vacant=1);positive['complete_face']=False;positive['surveyed_capacity']=None
    zero=observation('synthetic-zero');zero['complete_face']=False
    reviews=[review(positive),review(zero)];reviews[0]['capacity_verified']=False
    labels,reject=reviewed_outcomes([positive,zero],reviews,'synthetic_demo')
    assert labels['synthetic-positive']['at_least_one']==1 and labels['synthetic-positive']['occupancy_rate'] is None
    assert len(reject)==1 and 'Partial' in reject[0]['reason']


@pytest.mark.parametrize('change',[{'vehicle_class':'commercial'},{'permit_class':'different-permit'},{'intended_duration_minutes':30},{'rules_valid_to_utc':'2026-10-05T12:30Z'},{'eligibility_status':'unknown'},{'eligibility_status':'conflict'},{'full_stay_rules_verified':False}])
def test_suitability_requires_profile_and_whole_stay_rule_evidence(change):
    o=observation('synthetic');r=review(o);r.update(change)
    labels,reject=reviewed_outcomes([o],[r],'synthetic_demo');assert not labels and len(reject)==1


def test_unseen_block_holdout_rejects_opposite_side_or_known_block_leakage():
    obs,reviews,pred,decisions,m=fixture();m['axis']='unseen_block'
    with pytest.raises(ValueError,match='physical blocks'):evaluate(obs,reviews,pred,decisions,m)


def test_missing_counterfactual_labels_and_unknown_rules_do_not_become_failures():
    obs,reviews,pred,decisions,m=fixture();decisions[0]['candidates'][1]['observation_id']=None;decisions[0]['candidates'][1]['prediction_id']=None
    result=evaluate(obs,reviews,pred,decisions,m)
    assert result['ranking']['fully_paired_complete_candidate_decisions']==0
    assert result['ranking']['policies']['app_policy']['top1_observed_success'] is None
    obs,reviews,pred,decisions,m=fixture();decisions[0]['candidates'][0]['eligibility_status']='unknown'
    result=evaluate(obs,reviews,pred,decisions,m);assert result['ranking']['decision_audit'][0]['eligible_faces']==1


def test_forecast_profile_time_leakage_and_duplicate_versions_rejected():
    obs,reviews,pred,decisions,m=fixture();pred[0]['feature_available_at_utc']='2026-10-05T12:00Z'
    with pytest.raises(ValueError,match='leakage'):evaluate(obs,reviews,pred,decisions,m)
    obs,reviews,pred,decisions,m=fixture();pred[1]['model_version']='synthetic-v2'
    with pytest.raises(ValueError,match='versions'):evaluate(obs,reviews,pred,decisions,m)


def test_reserved_period_blocked_before_outcome_files_open(tmp_path):
    from la_parking.product_evaluation import run
    manifest={'axis':'future_time','train_ids':[],'evaluation_ids':[],'evaluation_start_utc':'2026-11-24T08:00Z','evaluation_end_utc':'2026-11-25T08:00Z'}
    p=tmp_path/'manifest.json';p.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='Reserved'):run(p,'absent-observations','absent-reviews','absent-forecasts')
    manifest.update(phase='locked_test',freeze_file=str(tmp_path/'absent'))
    with pytest.raises(ValueError,match='not ended'):guard_manifest(manifest,now='2026-11-24T12:00Z')


def test_movements_require_actual_coverage_and_never_derive_from_count_difference():
    o=observation('synthetic');o.update(arrivals_observed=0)
    with pytest.raises(ValueError,match='Unobserved'):ManualObservation.model_validate(o)
    o.update(movement_coverage='continuous',movement_start_utc='2026-10-05T11:45Z',movement_end_utc='2026-10-05T12:00Z',departures_observed=2,repeat_group_id='synthetic-group',repeat_offset_minutes=15)
    assert ManualObservation.model_validate(o).arrivals_observed==0
    o['eligible_capacity']=5;o['physical_capacity']=4
    with pytest.raises(ValueError,match='physical supply'):ManualObservation.model_validate(o)


def test_real_trial_metrics_include_missing_assignment_bounds_and_censoring():
    plan=assignments();assert len(plan)==24 and sum(r['assigned_arm']=='app' for r in plan)==12
    slot=plan[0];t=datetime.fromisoformat(slot['planned_utc'])
    row=dict(trial_id=slot['trial_id'],data_kind='synthetic_demo',assigned_arm=slot['assigned_arm'],received_recommendation_at_utc=t.isoformat(),
        search_started_at_utc=t.isoformat(),search_ended_at_utc=(t+timedelta(minutes=5)).isoformat(),abandoned=True,verified=True,reviewed_by='fixture',reviewed_at_utc=(t+timedelta(hours=1)).isoformat())
    report=trial_metrics([row],data_kind='synthetic_demo');arm=report['arms'][slot['assigned_arm']]
    assert report['status']=='synthetic_demonstration' and report['relative_restricted_search_reduction'] is None
    assert arm['restricted_search_measured_n']==0 and arm['censored_or_abandoned']==1
    assert arm['restricted_search_bounds_all_assigned_minutes']==[5/12,20]
    assert report['suitable_probability_calibration']['n']==0


def test_trial_timeline_and_meter_probabilities_cannot_fake_product_results():
    slot=assignments()[0];t=datetime.fromisoformat(slot['planned_utc']);row=dict(trial_id=slot['trial_id'],assigned_arm=slot['assigned_arm'],received_recommendation_at_utc=t.isoformat(),search_started_at_utc=t.isoformat())
    with pytest.raises(ValueError,match='supported'):PilotTrial.model_validate({**row,'predicted_probability_suitable':.9})
    with pytest.raises(ValueError,match='arrival'):PilotTrial.model_validate({**row,'arrival_success':True})


def test_capacity_audit_reads_inventory_without_outcome_files(tmp_path):
    report=capacity_audit(tmp_path/'audit.json')
    assert report['occupancy_labels_read']==0 and not report['historic_curb_polygons_are_stalls']
    if report['status']!='unavailable':assert report['faces']>0 and 0<=report['physical_capacity_known']<=report['faces']


def test_locked_release_rejects_changed_model_bytes(tmp_path):
    import hashlib
    model=tmp_path/'synthetic-model';model.write_bytes(b'synthetic-test-not-a-trained-model')
    lock={'frozen_at_utc':'2026-11-22T00:00Z','config_sha256':hashlib.sha256(Path('config/product_pilot.json').read_bytes()).hexdigest(),
        'artifacts_sha256':{str(model):hashlib.sha256(model.read_bytes()).hexdigest()}}
    p=tmp_path/'lock.json';p.write_text(json.dumps(lock));m=dict(axis='unseen_block',phase='locked_test',train_ids=[],evaluation_ids=[],
        evaluation_start_utc='2026-11-23T08:00Z',evaluation_end_utc='2026-12-07T08:00Z',freeze_file=str(p))
    assert guard_manifest(m,now='2026-12-08T00:00Z').phase=='locked_test'
    model.write_bytes(b'changed')
    with pytest.raises(ValueError,match='artifact changed'):guard_manifest(m,now='2026-12-08T00:00Z')


def test_recommendation_excludes_rules_expiring_mid_stay():
    obs,reviews,pred,decisions,m=fixture();decisions[0]['candidates'][1]['rules_valid_to_utc']='2026-10-05T12:30Z'
    r=evaluate(obs,reviews,pred,decisions,m)
    assert r['ranking']['decision_audit'][0]['eligible_faces']==1
    assert r['ranking']['decision_audit'][0]['policies']['app_policy']['face_id']=='fixture-a:left'


def test_intake_parquet_can_enter_explicit_synthetic_evaluation(tmp_path):
    import geopandas as gpd
    from shapely.geometry import LineString
    from la_parking.observations import ingest
    from la_parking.product_evaluation import run
    obs,reviews,pred,decisions,m=fixture()
    faces=gpd.GeoDataFrame({'block_face_id':['fixture-a:left','fixture-b:left']},geometry=[LineString([(-118.4401,34.06),(-118.4399,34.06)])]*2,crs=4326)
    inventory=tmp_path/'inventory.parquet';faces.to_parquet(inventory)
    # Verify links/ages from actual clocks, including intake columns and JSON provenance.
    obs[2].update(previous_observation_id=obs[0]['observation_id'],previous_observation_age_minutes=999)
    obs[2]['survey_session_id']=obs[0]['survey_session_id']
    def write(name,rows):
        p=tmp_path/name;p.write_text(''.join(json.dumps(r)+'\n' for r in rows));return p
    path=write('synthetic.jsonl',obs);result=ingest(path,inventory_path=inventory,output=tmp_path/'intake')
    assert result['accepted']==4
    table=tmp_path/'intake/manual_observations.parquet'
    import pandas as pd
    stored=pd.read_parquet(table);assert stored.loc[stored.observation_id.eq(obs[2]['observation_id']),'previous_observation_age_minutes'].iloc[0]!=999
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(m))
    report=run(manifest,table,write('reviews.jsonl',reviews),write('forecasts.jsonl',pred),write('decisions.jsonl',decisions),tmp_path/'report.json')
    assert report['status']=='synthetic_demonstration' and report['metrics']['unmetered']['suitable_probability']['n']==2
