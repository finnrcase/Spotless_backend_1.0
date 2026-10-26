"""Synthetic fixtures exercise isolation; never write real occupancy labels."""
import numpy as np
import pandas as pd
import pytest
from la_parking.spatial_experiment import NeighborHistory,folds,columns,predict
from la_parking.sensor_capture import Capture,protected_period,poll,compare_manual
from la_parking.contracts import MeterBayObservation,ManualObservation


def test_heldout_and_future_neighbors_cannot_enter_transfer_features():
    times=pd.to_datetime(['2026-08-01T00:00Z','2026-08-01T00:15Z']);rows=[]
    for face,value in [('a:left',.2),('b:left',.9),('c:left',.4)]:
        for t in times:rows.append({'block_face_id':face,'interval_start_utc':t,'roster_available_at_utc':times[0],'history_rate':value})
    history=pd.DataFrame(rows);ctx=pd.DataFrame({'segment_id':['a','b','c'],'x':[0.,10.,20.],'y':[0.,0.,0.]});q=pd.DataFrame({'block_face_id':['c:left'],'issued_at_utc':[times[1]]})
    a=NeighborHistory(history,ctx).transform(q,{'a'})
    history.loc[history.block_face_id.eq('b:left')|(history.interval_start_utc>=times[1]),'history_rate']=0
    b=NeighborHistory(history,ctx).transform(q,{'a'})
    assert a.transfer_neighbor_300.iloc[0]==.2 and a.transfer_neighbor_count_300.iloc[0]==1
    pd.testing.assert_frame_equal(a,b)


def test_inner_folds_hold_whole_blocks_and_respect_chronology():
    assignment={'a':0,'b':0,'c':1,'d':1};rows=[]
    for block in assignment:
        for side in ['left','right']:
            for t in ['2026-08-08T00:00Z','2026-08-09T15:00Z']:rows.append({'block_id':block,'block_face_id':block+':'+side,'issued_at_utc':pd.Timestamp(t),'arrival_time_utc':pd.Timestamp(t)+pd.Timedelta('60min')})
    cfg={'rolling_origins_local':['2026-08-09'],'validation_days':3,'embargo_minutes':180}
    for _,held,tr,va in folds(pd.DataFrame(rows),assignment,cfg):
        assert set(tr.block_id).isdisjoint(va.block_id) and set(va.block_id)==held
        assert all(set(va.loc[va.block_id.eq(b),'block_face_id'])=={b+':left',b+':right'} for b in held)
        assert (tr.arrival_time_utc+pd.Timedelta('15min')<pd.Timestamp('2026-08-09',tz='America/Los_Angeles')-pd.Timedelta('180min')).all()
    for v in ['calendar','plus_neighbors','plus_housing','plus_workplaces','plus_geometry','minus_neighbors','minus_housing','minus_workplaces']:
        assert not any(c.startswith(('own_','hist_face')) or c in ['block_id','block_face_id'] for c in columns(v))


def test_prediction_bounds_retain_all_rows():
    f=pd.DataFrame({'panel_sensor_count':[2,4]});b={'kind':'constant','model':8.,'target':'available_count'}
    np.testing.assert_array_equal(predict(b,f),[2,4]);b['target']='occupancy_rate';np.testing.assert_array_equal(predict(b,f),[1,1])


def test_repeated_polls_do_not_refresh_event_age(tmp_path):
    c=Capture(tmp_path);row={'spaceid':'fixture-A','eventtime':'2026-08-01T00:00Z','occupancystate':'OCCUPIED'}
    a=c.record([row],'2026-08-01T00:02Z');b=c.record([row],'2026-08-01T00:18Z')
    assert a['new_provider_transactions']==1 and b['unchanged_poll_rows']==1
    assert c.latest_asof('fixture-A','2026-08-01T00:01Z') is None
    assert c.latest_asof('fixture-A','2026-08-01T00:20Z')['event_time']==pd.Timestamp(row['eventtime']).isoformat()
    obs=[{'observation_id':'fixture','meter_bays':[{'space_id':'fixture-A','state':'VACANT','observed_at_utc':'2026-08-01T00:20Z','identity_verified':True}]}]
    r=compare_manual(c,obs,{('fixture','fixture-A')})
    assert r['policies'][1]['supported']==0 and r['policies'][2]['supported']==1 and r['policies'][2]['agreement']==0
    assert not r['expiry_changed'];c.close()


def test_unknown_and_conflicting_states_stay_unknown(tmp_path):
    c=Capture(tmp_path)
    for state in ['OCCUPIED','VACANT']:c.record([{'spaceid':'fixture-A','eventtime':'2026-08-01T00:00Z','occupancystate':state}],'2026-08-01T00:02Z')
    assert c.latest_asof('fixture-A','2026-08-01T00:03Z')['conflict']
    c.record([{'spaceid':'fixture-A','eventtime':'2026-08-01T00:04Z','occupancystate':'UNKNOWN'}],'2026-08-01T00:05Z')
    assert c.latest_asof('fixture-A','2026-08-01T00:06Z')['state']=='UNKNOWN';c.close()


def test_quarantine_and_feed_failure_never_create_evidence(tmp_path):
    c=Capture(tmp_path);r=c.record([None,None],'2026-10-25T12:00Z',quarantined=True)
    assert r['quarantined_outcomes'] and c.status()['parsed_provider_transactions']==0;c.close()
    class FailedStore:
        def json(self,*a,**kw):raise RuntimeError('fixture feed unavailable')
    r=poll(tmp_path,store=FailedStore(),clock=lambda:pd.Timestamp('2026-08-01T00:00Z'))
    assert r['status']=='unavailable' and 'fixture feed unavailable' in r['error']
    with pytest.raises(ValueError,match='reserved holdout'):poll(tmp_path,store=FailedStore(),clock=lambda:pd.Timestamp('2026-10-25T12:00Z'))


def test_protected_periods_use_la_timezone_and_preserve_prior_holds():
    assert not protected_period('2026-10-25T06:59Z') and protected_period('2026-10-25T07:00Z')
    assert not protected_period('2026-11-01T07:00Z') and protected_period('2026-11-08T12:00Z') and protected_period('2026-11-16T12:00Z')


def test_bay_contract_requires_aware_window_and_unique_ids():
    with pytest.raises(ValueError):MeterBayObservation(space_id='fixture',state='VACANT',observed_at_utc='2026-08-01T12:00')
    base=dict(source_id='synthetic-test',source_record_id='fixture',source_version='test',retrieved_at_utc='2026-08-01T12:05Z',confidence=.4,field_provenance={},observation_id='fixture',block_face_id='fixture:left',observer_pseudonym='fixture',survey_start_utc='2026-08-01T12:00Z',survey_end_utc='2026-08-01T12:05Z',complete_face=False,location_method='confirmed_map_pin',latitude=34.06,longitude=-118.44)
    bay=dict(space_id='fixture-A',state='VACANT',observed_at_utc='2026-08-01T12:02Z',identity_verified=False)
    r=ManualObservation(**base,meter_bays=[bay]);assert r.surveyed_capacity is None and r.occupied is None
    with pytest.raises(ValueError,match='Duplicate'):ManualObservation(**base,meter_bays=[bay,bay])
    with pytest.raises(ValueError,match='outside'):ManualObservation(**base,meter_bays=[{**bay,'observed_at_utc':'2026-08-01T12:10Z'}])


def test_quarantine_release_waits_for_end_and_frozen_model_hashes(tmp_path):
    import hashlib,json
    raw=tmp_path/'synthetic-snapshot.json';raw.write_text(json.dumps([{'spaceid':'fixture-A','eventtime':'2026-10-25T11:59Z','occupancystate':'VACANT'}]))
    c=Capture(tmp_path/'capture');r=c.record([None],'2026-10-25T12:00Z',raw,True)
    with pytest.raises(ValueError,match='has not ended'):c.release_for_locked_evaluation(r['poll_id'],now='2026-10-26T12:00Z')
    model=tmp_path/'synthetic-model-fixture';model.write_bytes(b'not-a-trained-model-test-only')
    lock=tmp_path/'lock.json';lock.write_text(json.dumps({'checks_passed':True,'new_holdouts_unopened':True,'models_sha256':{str(model):hashlib.sha256(model.read_bytes()).hexdigest()}}))
    result=c.release_for_locked_evaluation(r['poll_id'],lock,now='2026-11-02T12:00Z')
    assert result['purpose']=='locked_evaluation_only' and c.status()['parsed_provider_transactions']==0
    evaluation=Capture(result['evaluation_directory']);assert evaluation.latest_asof('fixture-A','2026-10-25T12:01Z')['state']=='VACANT';evaluation.close()
    model.write_bytes(b'changed-test-only')
    with pytest.raises(ValueError,match='Locked model changed'):c.release_for_locked_evaluation(r['poll_id'],lock,now='2026-11-02T12:00Z')
    c.close()


def test_field_holdouts_materialize_reserved_blocks_sessions_and_repeats():
    import json
    from pathlib import Path
    p=Path('reports/field_route.json')
    if not p.exists():pytest.skip('Generate route for integration check')
    plan=json.loads(p.read_text());reserved=plan['reserved_evaluation_assignments'];audit=plan['optional_sensor_assignments']
    assert len(reserved)==60 and len(audit)==8
    assert len({r['block_id'] for r in reserved if r['evaluation_role']=='unseen_block_holdout'})==3
    assert {r['repeat_offset_minutes'] for r in audit}=={0,15,30,60}
    assert all(r['visit_status']=='planned_not_observed' for r in reserved+audit)
