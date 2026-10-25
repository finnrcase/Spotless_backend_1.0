"""Causality and population safeguards; synthetic fixtures are not performance."""
import numpy as np
import pandas as pd
import pytest
from la_parking.temporal_features import history_grid,TrainingPatterns,previous_local_time,add_dynamic,OWN
from la_parking.labels import interval_panel
from la_parking.sensor_audit import event_patterns


def sensor_events():
    frame=pd.DataFrame({'space_id':['a']*5,'observed_at_utc':pd.to_datetime(['2026-08-01T00:00Z','2026-08-01T00:05Z','2026-08-01T00:12Z','2026-08-01T00:20Z','2026-08-01T00:40Z']),
        'state':['VACANT','OCCUPIED','UNKNOWN','VACANT','OCCUPIED']})
    mapping=pd.DataFrame({'space_id':['a'],'block_face_id':['block:left'],'join_status':['matched']})
    return frame,mapping


def test_feature_grid_matches_legacy_seconds_and_never_becomes_target():
    events,mapping=sensor_events();start=pd.Timestamp('2026-08-01T00:15Z');end=pd.Timestamp('2026-08-01T01:00Z')
    legacy,_=interval_panel(events,mapping,start,end,15,15,start)
    history=history_grid(events,mapping,start,end,start)
    np.testing.assert_allclose(history.known_seconds,legacy.known_seconds)
    np.testing.assert_allclose(history.history_rate,legacy.occupancy_rate,equal_nan=True)
    assert not history.usable_as_target.any()


def test_unknown_and_future_events_do_not_leak_into_completed_history():
    events,mapping=sensor_events();start=pd.Timestamp('2026-08-01T00:00Z');end=pd.Timestamp('2026-08-01T01:00Z');discovery=pd.Timestamp('2026-08-01T00:01Z')
    a=history_grid(events,mapping,start,end,discovery)
    altered=events.copy();altered.loc[altered.observed_at_utc>pd.Timestamp('2026-08-01T00:15Z'),'state']='OCCUPIED'
    b=history_grid(altered,mapping,start,end,discovery)
    assert a.iloc[0].known_seconds==12*60 and a.iloc[0].occupied_seconds==7*60
    assert a.iloc[0].own_fresh_sensor_fraction==0 # last report is UNKNOWN, not vacant.
    np.testing.assert_allclose(a.iloc[:1].select_dtypes('number'),b.iloc[:1].select_dtypes('number'),equal_nan=True)


def patterns_frame():
    times=pd.date_range('2026-08-01T12:00Z',periods=8,freq='D')
    return pd.DataFrame({'block_face_id':['b:left']*8,'arrival_time_utc':times,'issued_at_utc':times-pd.Timedelta('60min'),
        'target_occupancy_rate':[.1,.2,.3,.4,.5,.6,.7,.8]})


def test_pattern_encoding_training_rows_are_expanding_and_fold_local():
    f=patterns_frame();m=TrainingPatterns(10).fit(f)
    first=m.transform(f)
    assert first.hist_face_count.iloc[0]==0 and first.hist_global_mean.iloc[0]==.5
    assert first.hist_face_count.iloc[1]==1
    changed=f.copy();changed.loc[4:,'target_occupancy_rate']=0
    second=TrainingPatterns(10).fit(changed).transform(f)
    np.testing.assert_allclose(first.iloc[:5],second.iloc[:5],equal_nan=True)
    train=f.iloc[:4];held=f.iloc[4:].copy();before=TrainingPatterns(10).fit(train).transform(held)
    held['target_occupancy_rate']=1
    after=TrainingPatterns(10).fit(train).transform(held)
    np.testing.assert_allclose(before,after,equal_nan=True)
    unseen=TrainingPatterns(10).fit(train).transform(held,unseen=True)
    assert unseen.drop(columns='hist_global_mean').isna().all().all()


def test_previous_day_is_local_calendar_day_across_dst_and_ambiguous_is_unknown():
    times=pd.Series(pd.to_datetime(['2026-11-02T17:00Z','2026-11-02T09:30Z','2026-03-09T16:00Z']))
    previous=previous_local_time(times,1)
    assert previous.iloc[0]==pd.Timestamp('2026-11-01T17:00Z')
    assert pd.isna(previous.iloc[1])
    assert previous.iloc[2]==pd.Timestamp('2026-03-08T16:00Z')


def test_reaffirmations_are_not_automatically_classified_as_heartbeats():
    e,_=sensor_events();summary,days=event_patterns(e,pd.Timestamp('2026-07-31',tz='America/Los_Angeles'),pd.Timestamp('2026-08-02',tz='America/Los_Angeles'),{'a'})
    assert 'not proof' in summary['interpretation'] and summary['states']['UNKNOWN']==1


def test_context_information_availability_and_missing_values_are_preserved():
    from la_parking.temporal_predictors import asof_context,HOUSING,JOBS
    f=pd.DataFrame({'block_id':['a','a','unknown'],'issued_at_utc':pd.to_datetime(['2025-09-10T12:00Z','2026-08-10T12:00Z','2026-08-10T12:00Z'])})
    c=pd.DataFrame({'block_id':['a'],**{col:[2.] for col in HOUSING+JOBS}})
    result=asof_context(f,c)
    assert result.loc[0,JOBS].isna().all() and result.loc[1,JOBS].notna().all()
    assert result.loc[0,HOUSING].notna().all() and result.loc[2,HOUSING+JOBS].isna().all()


def test_unseen_models_cannot_use_heldout_own_history():
    from la_parking.temporal_experiment import prepare
    from la_parking.model_features import HISTORY
    from la_parking.temporal_features import OWN
    f=pd.DataFrame({col:[.8] for col in HISTORY+OWN})
    f['source_month']='2026_08'
    for radius in [300,600]:
        for name in ['neighbor_all','neighbor_train_only','v2_neighbor_all','v2_neighbor_train']:f[f'{name}_{radius}']=.2
    known=prepare(f,'known_blocks');unseen=prepare(f,'unseen_blocks')
    assert known.own_lag_rate.iloc[0]==.8
    assert unseen[OWN+[col for col in HISTORY if not col.startswith('neighbor')]].isna().all().all()
    assert unseen.v2_neighbor_300.iloc[0]==.2


def test_fixed_row_digest_includes_targets_and_bounds_are_enforced():
    from la_parking.temporal_experiment import digest_rows,predict
    f=patterns_frame();a=digest_rows(f,'target_occupancy_rate');f.loc[0,'target_occupancy_rate']=.99
    assert digest_rows(f,'target_occupancy_rate')!=a
    f['panel_sensor_count']=2
    b={'kind':'constant','model':8.,'target':'available_count'}
    assert (predict(b,f)==2).all()
    b['target']='occupancy_rate';assert (predict(b,f)==1).all()


def test_smallest_collection_batch_has_actual_ids_and_no_generated_labels():
    import json
    from pathlib import Path
    p=Path('reports/field_route.json')
    if not p.exists():return
    plan=json.loads(p.read_text());small=plan['smallest_initial_batch']
    visits=[v for v in plan['assignments'] if v['assignment_id'] in small['assignment_ids']]
    assert len(visits)==8 and len({v['block_face_id'] for v in visits})==2
    assert {v['repeat_offset_minutes'] for v in visits}=={0,15,30,60}
    assert all(v['evaluation_role']=='development' and v['visit_status']=='planned_not_observed' for v in visits)


def test_tuning_uses_squared_error_even_when_mae_prefers_another_model(monkeypatch):
    from la_parking import temporal_experiment as exp
    train=pd.DataFrame({'target_occupancy_rate':np.zeros(80)})
    val=pd.DataFrame({'target_occupancy_rate':np.zeros(20)})
    monkeypatch.setattr(exp,'folds',lambda *args:iter([('fixture-only',train,val)]))
    monkeypatch.setattr(exp,'candidates',lambda *args:[('ridge',{'alpha':1}),('ridge',{'alpha':2})])
    monkeypatch.setattr(exp,'pattern_pair',lambda a,b,*args:(a,b))
    monkeypatch.setattr(exp,'fit_model',lambda tr,t,k,p,*args:p)
    monkeypatch.setattr(exp,'predict',lambda b,f:np.r_[np.zeros(19),1.] if b['alpha']==1 else np.full(20,.15))
    selected,metrics,trials=exp.tune_variant(train,'rmse_original_grid','known_blocks',{})
    assert selected==('ridge',{'alpha':2})
    assert trials[0]['mae']<trials[1]['mae'] and trials[0]['rmse']>trials[1]['rmse']
    assert np.isclose(metrics['rmse'],.15)


def test_manual_predictor_join_never_reads_target_counts_or_backdates_snapshot():
    from la_parking.temporal_predictors import manual_demand_predictors,HOUSING,JOBS
    requests=pd.DataFrame({'observation_id':['fixture-before','fixture-after','fixture-unknown'],
        'block_id':['a','a','outside'],'prediction_issued_at_utc':['2026-10-24T12:00Z','2026-10-27T12:00Z','2026-10-27T12:00Z'],
        'occupied':[0,999,0],'vacant_legal':[0,999,0]})
    c=pd.DataFrame({'block_id':['a'],**{col:[2.] for col in HOUSING+JOBS}})
    out=manual_demand_predictors(requests,c,'2026-10-25T12:00Z')
    assert out.loc[0,HOUSING+JOBS].isna().all() and out.loc[2,HOUSING+JOBS].isna().all()
    assert out.loc[1,HOUSING+JOBS].notna().all() and out.loc[1,'feature_available_at_utc']==pd.Timestamp('2026-10-25T12:00Z')
    assert 'occupied' not in out and 'vacant_legal' not in out and 'block_id' not in out
    requests['occupied']=requests['vacant_legal']=1
    pd.testing.assert_frame_equal(out,manual_demand_predictors(requests,c,'2026-10-25T12:00Z'))
