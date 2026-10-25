import json
import numpy as np
import pandas as pd
import pytest
from la_parking.labels import interval_panel
from la_parking.forecasting import ForecastArtifact,whole_stay_rules
from la_parking.modeling import prep_scenario,fit_head,predict_head
from la_parking.model_features import CALENDAR,HISTORY


def mapping():
    return pd.DataFrame({'space_id':['a','b'],'block_face_id':['block:left']*2,'segment_id':['block']*2,'join_status':['matched']*2})


def events(rows):
    e=pd.DataFrame(rows,columns=['space_id','observed_at_utc','state']);e.observed_at_utc=pd.to_datetime(e.observed_at_utc,utc=True);return e


def test_labels_are_weighted_overlap_not_transaction_counts():
    e=events([('a','2026-08-01T00:00Z','VACANT'),('b','2026-08-01T00:00Z','VACANT'),('a','2026-08-01T00:04Z','OCCUPIED'),('a','2026-08-01T00:06Z','VACANT')])
    f,_=interval_panel(e,mapping(),pd.Timestamp('2026-08-01T00:01Z'),pd.Timestamp('2026-08-01T00:16Z'),15,15,pd.Timestamp('2026-08-01T00:01Z'))
    assert f.occupied_seconds.iloc[0]==120
    assert f.known_seconds.iloc[0]==1740 # b TTL stops at minute 15, a stays known through end.
    assert f.occupancy_rate.iloc[0]==pytest.approx(120/1740)
    assert f.panel_available_count.iloc[0]==2
    assert not f.full_curb_label.iloc[0]


def test_unknown_stale_and_conflicting_states_are_not_vacancies():
    e=events([('a','2026-08-01T00:00Z','VACANT'),('b','2026-08-01T00:00Z','OCCUPIED'),('a','2026-08-01T00:04Z','UNKNOWN'),('b','2026-08-01T00:04Z','VACANT'),('b','2026-08-01T00:04Z','OCCUPIED')])
    f,_=interval_panel(e,mapping(),pd.Timestamp('2026-08-01T00:01Z'),pd.Timestamp('2026-08-01T00:31Z'),15,5,pd.Timestamp('2026-08-01T00:01Z'))
    assert f.known_seconds.iloc[0]==360
    assert f.known_seconds.iloc[1]==0
    assert pd.isna(f.occupancy_rate.iloc[1]) and pd.isna(f.panel_any_vacant.iloc[1])


def test_roster_uses_only_discovery_ids_and_no_backfill():
    e=events([('a','2026-08-01T00:00Z','OCCUPIED'),('b','2026-08-01T00:03Z','VACANT')])
    f,_=interval_panel(e,mapping(),pd.Timestamp('2026-08-01T00:01Z'),pd.Timestamp('2026-08-01T00:16Z'),15,15,pd.Timestamp('2026-08-01T00:01Z'))
    assert f.panel_sensor_count.iloc[0]==1
    assert f.panel_any_vacant.iloc[0]==0


def test_unseen_area_removes_own_and_held_area_history():
    f=pd.DataFrame({c:[.9] for c in HISTORY});f['neighbor_train_only_300']=.2;f['neighbor_train_only_600']=.3
    out=prep_scenario(f,'unseen_area')
    assert pd.isna(out.lag_rate_15.iloc[0]); assert out.neighbor_rate_300.iloc[0]==.2


def test_full_duration_rules_cross_midnight_and_permit():
    rules=[dict(type='no_parking',status='verified',start_utc='2026-11-01T08:30Z',end_utc='2026-11-01T10:00Z')]
    result=whole_stay_rules('2026-11-01T08:00Z',60,{},rules,physical_capacity=5,complete=True)
    assert result['eligible_capacity']==0
    assert whole_stay_rules('2026-11-01T08:00Z',15,{},[],physical_capacity=5,complete=False)['status']=='unknown'
    assert whole_stay_rules('2026-11-01T08:00Z',15,{},[],physical_capacity=5,complete=True)['eligible_capacity']==5


def test_unknown_rules_cannot_emit_suitable_probabilities():
    base=dict(block_face_id='x',issued_at='2026-08-25T12:00Z',arrival_time='2026-08-25T12:15Z',horizon_minutes=15,intended_stay_minutes=60,eligibility_profile={},forecast_mode='insufficient_data',evidence_class='unknown',model_uncertainty={},support='insufficient_data')
    assert ForecastArtifact(**base).probability_at_least_one is None
    with pytest.raises(ValueError): ForecastArtifact(**base,probability_at_least_one=.5)


def test_preprocessing_is_fit_on_training_only():
    n=40;train=pd.DataFrame({'x':np.arange(n,dtype=float),'target_occupancy_rate':np.arange(n)/n})
    cfg={'seed':430,'prediction_interval_nominal_coverage':.9}
    b=fit_head(train,train.iloc[:0],'occupancy_rate','regularized',['x'],10,cfg)
    center=b['model'].named_steps['standardscaler'].mean_.copy()
    test=pd.DataFrame({'x':[1e9],'panel_sensor_count':[1]});predict_head(b,test)
    np.testing.assert_array_equal(b['model'].named_steps['standardscaler'].mean_,center)


def test_saved_forecast_examples_abstain_on_real_suitability():
    from pathlib import Path
    path=Path('reports/modeling/forecast_examples.jsonl')
    if not path.exists(): pytest.skip('Run the modeling pipeline')
    rows=[ForecastArtifact.model_validate_json(line) for line in path.read_text().splitlines()]
    assert rows and all(r.probability_at_least_one is None and r.expected_available_spaces is None for r in rows)
