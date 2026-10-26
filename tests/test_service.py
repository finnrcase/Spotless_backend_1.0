"""Real-data integration plus isolated synthetic rule/observation fixtures."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import copy
import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from la_parking.service.api import create_app
from la_parking.service.repository import Repository
from la_parking.service.schemas import PredictionRequest,PanelEstimate
from la_parking.service.eligibility import evaluate,resolve_local

UTC=timezone.utc
ISSUE=datetime(2026,8,25,17,tzinfo=UTC)
NOW=datetime(2026,10,25,6,tzinfo=UTC)


def query(replay=True):
    r={'destination':{'latitude':34.0608,'longitude':-118.4465},'arrival_time':(ISSUE if replay else NOW+timedelta(hours=1)).isoformat(),
        'intended_stay_minutes':60,'maximum_walking_distance_m':400,'eligibility':{'vehicle_class':'standard_passenger','permit_class':None},'mode':'historical_replay' if replay else 'live','include_experimental':False}
    if replay:r['replay_issue_time']=ISSUE.isoformat()
    return r


@pytest.fixture(scope='module')
def integration(tmp_path_factory):
    root=Path(__file__).resolve().parents[1]
    if not (root/'data/processed/street_segments.parquet').exists():pytest.skip('Real foundation artifacts required')
    directory=tmp_path_factory.mktemp('service-isolated-fixtures')
    repo=Repository(root,observations_dir=directory/'observations')
    repo.rules_path=directory/'rules.json';repo.reload_snapshots()
    with TestClient(create_app(repo,clock=lambda:NOW,background=False)) as client:
        yield repo,client


def test_real_destination_forecast_and_map_contract(integration):
    repo,client=integration
    assert client.get('/').status_code==200
    r=client.post('/api/predictions',json=query());assert r.status_code==200,r.text
    data=r.json();assert data['blocks'] and data['mode_label'].startswith('HISTORICAL REPLAY')
    assert any(b['panel_estimate'] is not None for b in data['blocks'])
    for b in data['blocks']:
        assert b['walking_distance_m']<=400
        assert b['geometry']['coordinates'] and b['geometry']['type']
        assert b['eligibility']['status']=='unknown'
        assert b['probability_at_least_one_suitable'] is None and b['expected_available_eligible_spaces'] is None
        p=b['panel_estimate']
        if p and p['expected_vacant_count'] is not None:
            assert 0<=p['expected_vacant_count']<=p['panel_sensor_count']
            assert 0<=p['probability_any_panel_vacant']<=1
    second=client.post('/api/predictions',json=query()).json()
    assert second['cache_hit'] and second['forecast_issued_at']==data['forecast_issued_at'] and second['computed_at']==data['computed_at']
    assert all(b['eligibility']['checked_from']==data['arrival_time'] for b in data['blocks'])
    assert client.get('/api/streets',params={'latitude':34.0608,'longitude':-118.4465,'radius_m':700}).json()['features']
    assert client.get('/api/destinations',params={'q':'WESTWOOD'}).json()['matches']


def test_live_stale_and_missing_feeds_do_not_activate_models(integration,monkeypatch):
    repo,client=integration
    service=client.app.state.service;service.cache.clear()
    live=client.post('/api/predictions',json=query(False)).json()
    assert live['blocks'] and all(b['panel_estimate'] is None for b in live['blocks'])
    assert client.get('/api/health').json()['status']=='degraded'
    with monkeypatch.context() as m:
        m.setattr(repo,'current',pd.DataFrame());service.cache.clear()
        result=client.post('/api/predictions',json=query(False)).json()
        assert all(b['evidence']['status']=='missing' for b in result['blocks'])
        assert all(b['visual_status']=='insufficient_data' for b in result['blocks'])
    service.cache.clear()


def rule(kind='no_parking',**kwargs):
    record={'restriction_id':'test-only-rule','block_face_id':'test-only-face','rule_type':kind,'effective_from':'2026-08-25T17:30:00Z','effective_to':'2026-08-25T19:00:00Z',
        'available_at':'2026-08-24T00:00:00Z','source_kind':'official','source_url':'https://example.invalid/test-only','raw_text':'SYNTHETIC TEST FIXTURE — not an actual LA restriction',
        'verification':'verified','verified_at':'2026-08-24T00:00:00Z','expires_at':'2026-08-30T00:00:00Z'}
    record.update(kwargs);return record


def coverage():return {'block_face_id':'test-only-face','effective_from':'2026-08-01T00:00:00Z','effective_to':'2026-09-01T00:00:00Z','available_at':'2026-08-24T00:00:00Z','source_kind':'posted_sign_review','complete':True,'verified_at':'2026-08-24T00:00:00Z','expires_at':'2026-08-30T00:00:00Z'}


def check(rules,stay=60,profile=None,cover=None):return evaluate('test-only-face',ISSUE,stay,profile or {},rules,cover or [],ISSUE)


def test_missing_rules_mid_stay_restriction_and_conflict():
    assert check([]).status=='unknown'
    assert check([rule()]).status=='prohibited'
    assert check([rule()],stay=15).status=='unknown'
    assert check([rule(),rule('allow',restriction_id='test-only-conflict')]).status=='conflict'
    assert check([rule('allow',verification='needs_review')],cover=[coverage()]).status=='unknown'


def test_permit_vehicle_and_source_coverage_stay_distinct():
    r=rule('permit',effective_from='2026-08-25T16:00:00Z',allowed_permits=['D1'])
    assert check([r],cover=[coverage()]).status=='prohibited'
    allowed=check([r],profile={'permit_class':'D1'},cover=[coverage()])
    assert allowed.status=='allowed' and allowed.posted_sign_coverage_complete and not allowed.official_coverage_complete
    assert check([r],profile={'permit_class':'D1'}).status=='unknown'
    v=rule('vehicle_only',allowed_vehicles=['commercial'])
    assert check([v],profile={'vehicle_class':'standard_passenger'}).status=='prohibited'


def test_stale_coverage_future_unavailable_rules_and_upcoming():
    c=coverage();c['expires_at']='2026-08-25T17:15:00Z'
    assert check([],cover=[c]).status=='unknown'
    late=rule(available_at='2026-08-26T00:00:00Z')
    assert check([late]).status=='unknown'
    future=rule(effective_from='2026-08-25T18:30:00Z')
    assert check([future]).status=='unknown' and len(check([future]).upcoming)==1


def test_dst_resolution_and_elapsed_stay():
    with pytest.raises(ValueError,match='Ambiguous'):resolve_local('2026-11-01T01:30')
    assert (resolve_local('2026-11-01T01:30',1)-resolve_local('2026-11-01T01:30',0)).total_seconds()==3600
    with pytest.raises(ValueError,match='does not exist'):resolve_local('2026-03-08T02:30')
    with pytest.raises(ValueError):PredictionRequest.model_validate({**query(),'arrival_time':'2026-08-25T10:00:00'})
    r=evaluate('test-only-face',resolve_local('2026-11-01T01:30',0),120,{},[],[],datetime(2026,11,1,7,tzinfo=UTC))
    assert (r.checked_to-r.checked_from).total_seconds()==7200


def test_unsupported_neighborhood_and_outside_jurisdiction(integration):
    _,client=integration
    q=query();q['destination']={'latitude':34.1,'longitude':-118.31};q['maximum_walking_distance_m']=200
    data=client.post('/api/predictions',json=q).json()
    assert data['coverage']['inside_city']
    assert all(b['panel_estimate'] is None and b['probability_at_least_one_suitable'] is None for b in data['blocks'])
    q['destination']={'latitude':37.77,'longitude':-122.42}
    data=client.post('/api/predictions',json=q).json();assert not data['blocks'] and not data['coverage']['inside_city']


def test_bounds_and_cross_origin_write(integration):
    _,client=integration
    with pytest.raises(ValueError):PanelEstimate(expected_vacant_count=3,panel_sensor_count=2)
    with pytest.raises(ValueError):PanelEstimate(probability_any_panel_vacant=1.1)
    r=client.post('/api/refresh',json={},headers={'Origin':'https://example.invalid'})
    assert r.status_code==403


def test_rule_revision_invalidates_cached_forecast(integration):
    repo,client=integration;service=client.app.state.service
    q=query();before=client.post('/api/predictions',json=q).json();face=before['blocks'][0]['block_face_id']
    r=rule(block_face_id=face)
    repo.rules_path.write_text(json.dumps({'rules':[r],'coverage':[]}),encoding='utf8')
    changed=client.post('/api/refresh',json={}).json();assert changed['changed']
    after=client.post('/api/predictions',json=q).json()
    assert after['data_revision']!=before['data_revision'] and not after['cache_hit']
    selected=next(b for b in after['blocks'] if b['block_face_id']==face)
    assert selected['visual_status']=='known_restriction' and selected['eligibility']['status']=='prohibited'
    repo.rules_path.write_text(json.dumps({'rules':[],'coverage':[]}),encoding='utf8');client.post('/api/refresh',json={})


def test_submission_import_and_manual_evidence_are_reviewable(integration):
    repo,client=integration
    face=client.post('/api/predictions',json=query()).json()['blocks'][0]['block_face_id']
    template=client.get('/api/observations/template',params={'face_id':face}).json()
    record={'schema_version':'1.0','source_id':'test-only','source_record_id':'test-only-1','source_version':'test-only','retrieved_at_utc':NOW.isoformat(),
        'field_provenance':{'latitude':'assumed','occupied':'observed'},'confidence':.5,'observation_id':'test-only-1','block_face_id':face,'observer_pseudonym':'fixture',
        'survey_start_utc':(NOW-timedelta(minutes=3)).isoformat(),'survey_end_utc':NOW.isoformat(),'occupied':2,'vacant_legal':1,'unsuitable':1,'surveyed_capacity':4,
        'complete_face':True,'location_method':'confirmed_map_pin','gps_accuracy_m':None,'latitude':template['latitude'],'longitude':template['longitude'],'parking_type':'unmetered'}
    imported=client.post('/api/observations',json={'records':[record]}).json();assert imported['accepted']==1 and not imported['automatic_training']
    live=client.post('/api/predictions',json=query(False)).json();selected=next(b for b in live['blocks'] if b['block_face_id']==face)
    assert selected['evidence']['status']=='recent' and selected['evidence']['location_review_required']
    assert selected['probability_at_least_one_suitable'] is None
    duplicate=client.post('/api/observations',json={'records':[record]}).json();assert duplicate['accepted']==0 and duplicate['rejected']
    assert repo.observations_dir!=repo.root/'data/observations'


def test_openapi_contract_includes_full_observation_schema(integration):
    _,client=integration
    contract=client.get('/openapi.json').json()
    assert '/api/predictions' in contract['paths'] and '/api/observations' in contract['paths']
    assert 'PredictionRequest' in contract['components']['schemas'] and 'ManualObservation' in contract['components']['schemas']
    assert 'gap_lengths_m' in contract['components']['schemas']['ManualObservation']['properties']


def test_field_route_imagery_and_collector_share_working_local_links(integration):
    _,client=integration
    assert client.get('/field-route').status_code==200
    assert client.get('/collector.html').status_code==200
    result=client.get('/imagery');assert result.status_code==200 and 'Historic imagery review' in result.text
    assert client.get('/imagery/failure_examples.html').status_code==200


def test_invalid_rule_snapshot_degrades_to_unknown(integration):
    repo,client=integration
    repo.rules_path.write_text('{malformed',encoding='utf8');client.post('/api/refresh',json={})
    assert client.get('/api/health').json()['rule_load_error']
    data=client.post('/api/predictions',json=query()).json()
    assert all(b['eligibility']['status']=='unknown' for b in data['blocks'])
    repo.rules_path.write_text(json.dumps({'rules':[],'coverage':[]}),encoding='utf8');client.post('/api/refresh',json={})


def test_poll_failure_retains_last_valid_snapshot(tmp_path,monkeypatch):
    from la_parking.service.refresh import ForecastCache,RefreshManager
    path=tmp_path/'data/processed/city_current_occupancy.parquet';path.parent.mkdir(parents=True)
    path.write_bytes(b'last-valid-snapshot-fixture')
    class Repo:
        root=tmp_path
        source_state={}
        revision='before'
        config={'snapshot_check_seconds':0}
        def fingerprint(self):return 'after'
        def reload_snapshots(self):self.revision='after'
    def failure(*args,**kwargs):raise RuntimeError('Isolated test feed unavailable')
    monkeypatch.setattr('la_parking.connectors.socrata',failure)
    monkeypatch.setattr('la_parking.sensor_capture.protected_period',lambda at:False)
    manager=RefreshManager(Repo(),ForecastCache())
    changed,cleared,status=manager.poll_source()
    assert status['last_poll_error'] and status['last_poll_success'] is None
    assert path.read_bytes()==b'last-valid-snapshot-fixture'


def test_model_evidence_keeps_experiments_and_unmetered_support_explicit(integration):
    _,client=integration;r=client.get('/api/model-evidence')
    assert r.status_code==200
    data=r.json();assert not data['citywide_accuracy_validated'] and not data['unseen_blocks']['production_numeric_predictions_enabled']
    assert data['unmetered']['reviewed_test_n']==0 and data['restrictions']['legal_capacity'] is None
    assert not data['restrictions']['unknown_rules_mean_unrestricted']


def test_holdout_guard_prevents_live_source_poll_and_cache_mutation(integration,monkeypatch):
    _,client=integration
    monkeypatch.setattr('la_parking.sensor_capture.protected_period',lambda at:True)
    def unexpected(*a,**kw):raise AssertionError('Reserved outcomes must not be requested')
    monkeypatch.setattr('la_parking.connectors.socrata',unexpected)
    result=client.post('/api/refresh?poll_source=true',json={}).json()
    assert not result['source_poll_performed'] and not result['changed'] and result['cache_entries_cleared']==0
    assert 'Reserved evaluation' in result['message']
