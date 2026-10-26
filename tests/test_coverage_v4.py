"""Synthetic fixtures test privacy, missingness and fold isolation, not accuracy."""
import json
import os
from urllib.parse import quote
import numpy as np
import pandas as pd
import pytest
from la_parking.environment import load_local_env
from la_parking.census_auth import verify
from la_parking.http import Store
from la_parking.connectors import socrata,arcgis
from la_parking.census_coverage import derive
from la_parking.coverage_experiment import columns,folds,regional_design,legacy_masks


def test_env_allowlist_precedence_and_no_execution(tmp_path,monkeypatch):
    monkeypatch.delenv('CENSUS_API_KEY',raising=False)
    p=tmp_path/'.env';p.write_text('\ufeff# fixture only\nexport CENSUS_API_KEY="$(never execute)"\nSOCRATA_APP_TOKEN=ignored\n',encoding='utf8')
    monkeypatch.delenv('SOCRATA_APP_TOKEN',raising=False)
    result=load_local_env(p)
    assert os.environ['CENSUS_API_KEY']=='$(never execute)' and 'SOCRATA_APP_TOKEN' not in os.environ
    assert result=={'CENSUS_API_KEY':{'loaded':True,'source':'local_env'}}
    monkeypatch.setenv('CENSUS_API_KEY','process-fixture');assert load_local_env(p)['CENSUS_API_KEY']['source']=='process_environment'
    assert os.environ['CENSUS_API_KEY']=='process-fixture'


def test_invalid_key_redirect_is_failure_despite_http_200(tmp_path,monkeypatch):
    monkeypatch.setenv('CENSUS_API_KEY','synthetic-secret')
    class Fake:
        last_record={'status':200,'final_url':'https://api.census.gov/data/invalid_key.html'}
        def json(self,url,params,**kw):
            assert 'key' not in params and kw['secret_params']['key']=='synthetic-secret'
            raise RuntimeError('fixture response includes synthetic-secret')
    r=verify(Fake(),tmp_path/'absent',output=None)
    assert r['credential']['loaded'] and r['status']=='authentication_failed' and not r['authenticated_request_succeeded']
    assert 'synthetic-secret' not in json.dumps(r)


def test_anonymous_socrata_does_not_send_configured_token(monkeypatch):
    monkeypatch.setenv('SOCRATA_APP_TOKEN','synthetic-secret')
    class Fake:
        def json(self,url,params,**kw):
            assert kw['headers']=={}
            return ([{'count':'1'}] if '$select' in params else [{'id':'fixture'}]),{}
    assert len(socrata(Fake(),'fixture'))==1


def test_http_failures_redact_secret_url_headers_and_exception(tmp_path,monkeypatch):
    secret='fixture-secret&x';store=Store(tmp_path);monkeypatch.setattr('la_parking.http.time.sleep',lambda x:None)
    class Response:
        status_code=403;url='https://fixture.invalid/?key='+quote(secret,safe='');headers={'Location':url}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):raise RuntimeError(self.url)
    monkeypatch.setattr(store.session,'get',lambda *a,**k:Response())
    with pytest.raises(RuntimeError) as error:store.get('https://fixture.invalid',secret_params={'key':secret})
    manifest=(tmp_path/'manifest.jsonl').read_text();assert secret not in manifest and quote(secret,safe='') not in manifest
    assert secret not in str(error.value) and 'REDACTED' in manifest and store.last_record['status']==403


def test_http_cache_has_no_credentials_and_skips_second_request(tmp_path,monkeypatch):
    store=Store(tmp_path);calls=[];monkeypatch.setattr('la_parking.http.time.sleep',lambda x:None)
    class Response:
        status_code=200;url='https://fixture.invalid/?key=synthetic-secret';headers={'Content-Type':'application/json','Content-Length':'2'}
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def raise_for_status(self):pass
        def iter_content(self,*a):yield b'[]'
    def get(*a,**kw):calls.append(kw);return Response()
    monkeypatch.setattr(store.session,'get',get)
    a=store.get('https://fixture.invalid',secret_params={'key':'synthetic-secret'});b=store.get('https://fixture.invalid')
    assert a==b and len(calls)==1
    assert 'synthetic-secret' not in (tmp_path/'manifest.jsonl').read_text()
    assert store.session.adapters['https://'].max_retries.total==4
    assert store.session.adapters['https://'].max_retries.respect_retry_after_header


def test_network_calls_are_host_rate_limited(tmp_path,monkeypatch):
    store=Store(tmp_path);delays=[];monkeypatch.setattr('la_parking.http.time.sleep',delays.append)
    monkeypatch.setattr('la_parking.http.time.monotonic',lambda:10.)
    monkeypatch.setattr(Store,'_host_times',{'data.lacity.org':9.75})
    def fail(*a,**kw):raise RuntimeError('fixture offline')
    monkeypatch.setattr(store.session,'get',fail)
    with pytest.raises(RuntimeError):store.get('https://data.lacity.org/resource/fixture.json')
    assert delays[0]==.75


def test_census_ratios_preserve_moe_zero_denominator_and_censoring():
    f=pd.DataFrame({'B08201_E001':['10','0','-666666666'],'B08201_E002':['2','0','0'],
        'B08201_E003':['3','0','0'],'B08201_E004':['2','0','0'],'B08201_E005':['1','0','0'],
        'B08201_E006':['2','0','0'],'B08201_E007':['4','0','0'],'B08201_M001':['5','0','-222222222']})
    r=derive(f);assert r.no_vehicle_fraction.iloc[0]==.2 and r.vehicle_lower_bound_per_household.iloc[0]==1.8
    assert r.one_person_household_fraction.iloc[0]==.4 and r.iloc[1:][['no_vehicle_fraction','vehicle_lower_bound_per_household']].isna().all().all()
    assert r.B08201_M001.tolist()==f.B08201_M001.tolist() and r.derived_ratio_moe.isna().all()
    assert 'vehicle_ownership_fraction' not in r and 'block_id' not in columns('additional_census')


def test_regional_target_keeps_difficult_rows_and_unknown_counts():
    f=pd.DataFrame({'block_face_id':['fixture:left']*6,'block_id':['fixture']*6,'region':['fixture']*6,'source_month':['2026_08']*6,
        'panel_sensor_count':[2]*6,'interval_start_utc':pd.date_range('2026-08-08T07:00Z',periods=6,freq='15min'),
        'occupancy_rate':[.5]*6,'coverage_fraction':[1,1,1,1,.2,1],'panel_available_count':[np.nan]*6,'panel_any_vacant':[np.nan]*6})
    r=regional_design(f);assert len(r)==6 and pd.isna(r.target_occupancy_rate.iloc[0]) and r.target_occupancy_rate.iloc[1]==.5
    assert r.target_available_count.isna().all() and r.target_occupancy_rate.iloc[2:].isna().all()
    assert ((r.arrival_time_utc-r.issued_at_utc)==pd.Timedelta('60min')).all()


def test_regional_folds_hold_both_sides_and_embargo_entire_windows():
    rows=[]
    for region in ['Westwood','Downtown','Hollywood']:
        for side in ['left','right']:
            for stamp in ['2026-08-08T00:00Z','2026-08-09T15:00Z']:
                t=pd.Timestamp(stamp);rows.append({'block_id':region,'block_face_id':region+':'+side,'region':region,'issued_at_utc':t,'arrival_time_utc':t+pd.Timedelta('60min')})
    cfg={'rolling_origins_local':['2026-08-09'],'validation_days':3,'embargo_minutes':180}
    for name,axis,tr,va in folds(pd.DataFrame(rows),cfg):
        assert tr.arrival_time_utc.max()+pd.Timedelta('15min')<pd.Timestamp('2026-08-09',tz='America/Los_Angeles')-pd.Timedelta('180min')
        if axis=='unseen_neighborhood':assert set(tr.block_id).isdisjoint(va.block_id) and len(va)==2


def test_sensor_location_query_excludes_reserved_status_values():
    calls=[]
    class Fake:
        def json(self,url,params):
            calls.append(params)
            if not url.endswith('/query'):return {'name':'fixture','objectIdField':'OBJECTID'},{}
            if 'returnIdsOnly' in params:return {'objectIds':[1]},{}
            assert 'SENSOR_STATUS' not in params['outFields']
            return {'features':[{'properties':{'OBJECTID':1},'geometry':{'type':'Point','coordinates':[-118,34]}}]},{}
    arcgis(Fake(),'https://fixture.invalid/layer',out_fields='OBJECTID,SENSOR_UNIQUE_ID,GPSX,GPSY')
    assert len(calls)==3


def test_regional_collection_plan_and_collector_have_stable_real_ids():
    from pathlib import Path
    p=Path('reports/field_route.json')
    if not p.exists():pytest.skip('Build local route first')
    plan=json.loads(p.read_text())
    if 'regional_assignments' not in plan:pytest.skip('Optional regional acquisition not present')
    rows=plan['regional_assignments'];assert len(rows)==32
    assert len({r['assignment_id'] for r in rows})==32
    assert all(r['visit_status']=='planned_not_observed' for r in rows)
    for session in {r['survey_session_id'] for r in rows}:
        subset=[r for r in rows if r['survey_session_id']==session]
        assert len({r['block_id'] for r in subset})==1 and len({r['block_face_id'] for r in subset})==2
        assert {r['repeat_offset_minutes'] for r in subset}=={0,15,30,60}
    held={r['block_id'] for r in rows if r['evaluation_role']=='unseen_block_holdout'}
    dev={r['block_id'] for r in rows if r['evaluation_role']=='development'}
    assert held.isdisjoint(dev) and len(held)==2
    html=Path('reports/collector.html').read_text(encoding='utf8')
    assert all(r['block_face_id'] in html for r in rows)


def test_regional_reserved_block_cannot_enter_unmetered_training(tmp_path,monkeypatch):
    from la_parking.unmetered import split_rows
    (tmp_path/'config').mkdir();monkeypatch.chdir(tmp_path)
    (tmp_path/'config/coverage_v4_field_holdouts.json').write_text(json.dumps({'unseen_physical_blocks':['reserved'],'reserved_session_ids':[],'reserved_assignment_ids':[]}))
    f=pd.DataFrame({'observation_id':['fixture'],'block_id':['reserved']})
    with pytest.raises(ValueError,match='Reserved physical blocks'):
        split_rows(f,'unseen_block',{'train_ids':['fixture'],'validation_ids':[],'calibration_ids':[],'test_ids':[]},{})


def test_consecutive_months_do_not_expand_original_geographic_benchmark():
    f=pd.DataFrame({'original_legacy_rows':[True,False,True],'spatial_role':['test']*3,'region':['Westwood']*3,
        'issued_at_utc':pd.to_datetime(['2025-09-10T12:00Z','2026-06-10T12:00Z','2026-08-25T12:00Z']),
        'arrival_time_utc':pd.to_datetime(['2025-09-10T13:00Z','2026-06-10T13:00Z','2026-08-25T13:00Z'])})
    cfg={'training_end_local':'2026-08-17','embargo_minutes':180,'legacy_test_start_local':'2026-08-25','legacy_test_end_local':'2026-09-01'}
    masks=legacy_masks(f,cfg)
    assert masks['unseen_block'].tolist()==[True,False,False] and masks['future_time_unseen'].tolist()==[False,False,True]
