import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from la_parking.evaluation import evaluate, regression_metrics, probability_metrics, validate_split
from la_parking.contracts import ManualObservation


def row(id,block='b1',kind='unmetered',when='2026-10-20T12:00:00Z',y=.5,p=.4):
    stamp=pd.Timestamp(when)
    return dict(observation_id=id,block_id=block,block_face_id=block+':left',parking_type=kind,
                observed_at_utc=stamp.isoformat(),window_end_utc=(stamp+pd.Timedelta(minutes=5)).isoformat(),
                prediction_issued_at_utc=(stamp-pd.Timedelta(minutes=10)).isoformat(),feature_available_at_utc=(stamp-pd.Timedelta(minutes=20)).isoformat(),
                occupancy_rate=y,pred_occupancy_rate=p,occupied_count=int(y*10),pred_occupied_count=p*10,
                available_count=2,pred_available_count=2.5,at_least_one=1,pred_at_least_one=.7)


def data():
    train=pd.DataFrame([row('tr1',y=.2),row('tr2',y=.8)])
    held=pd.DataFrame([row('te1',when='2026-10-22T12:00:00Z',y=.2,p=.3),row('te2',when='2026-10-22T13:00:00Z',y=.8,p=.7)])
    return train,held


def test_negative_and_undefined_r2_never_hidden():
    assert regression_metrics([0,1],[3,3])['r2']<0
    assert regression_metrics([1,1],[1,1])['r2'] is None
    assert regression_metrics([1],[1])['r2'] is None


def test_future_time_separate_groups_and_training_only_baselines():
    train,held=data(); result=evaluate(train,held,'future_time')
    unmetered=result['by_parking_type']['unmetered']
    assert unmetered['regression']['occupancy_rate']['r2']==pytest.approx(8/9)
    assert unmetered['regression']['occupancy_rate']['baselines']['train_mean']['mae']==pytest.approx(.3)
    assert result['by_parking_type']['metered']['status']=='no_held_out_labels'
    assert not result['aspiration_is_acceptance_criterion']
    assert unmetered['finding_at_least_one_space']['brier_score']==pytest.approx(.09)


def test_time_and_block_holdouts_reject_different_leakage():
    train,held=data()
    with pytest.raises(ValueError,match='physical blocks'): evaluate(train,held,'unseen_block')
    held['block_id']='new'; held['block_face_id']='new:left'
    with pytest.raises(ValueError,match='previously observed blocks'): evaluate(train,held,'future_time')
    assert evaluate(train,held,'unseen_block')['time_generalization_validated'] is False
    train,held=data(); held['prediction_issued_at_utc']='2026-10-20T12:30Z'
    with pytest.raises(ValueError): evaluate(train,held,'future_time')


def test_feature_and_observation_overlap_leakage_rejected():
    train,held=data(); held.loc[0,'feature_available_at_utc']='2026-10-22T12:00Z'
    with pytest.raises(ValueError,match='Feature leakage'): evaluate(train,held,'future_time')
    train,held=data(); held.loc[0,'observation_id']='tr1'
    with pytest.raises(ValueError,match='observation overlap'): evaluate(train,held,'future_time')


def test_abstentions_show_prediction_coverage():
    train,held=data(); held.loc[0,'pred_occupancy_rate']=np.nan
    report=evaluate(train,held,'future_time')['by_parking_type']['unmetered']['regression']['occupancy_rate']
    assert report['prediction_coverage']==.5 and report['r2'] is None


def test_probability_reliability_and_bad_values():
    m=probability_metrics([0,1],[.1,.9]); assert m['brier_score']==pytest.approx(.01)
    assert m['ece']==pytest.approx(.1); assert sum(b['n'] for b in m['reliability_bins'])==2
    train,held=data(); held['pred_at_least_one']='nonsense'
    with pytest.raises(ValueError,match='Nonnumeric'): evaluate(train,held,'future_time')
    with pytest.raises(ValueError): probability_metrics([0,1],[.1,1.1])


def test_confirmed_pin_never_claims_gps_accuracy():
    base=dict(source_id='test',source_record_id='x',source_version='test',retrieved_at_utc='2026-10-25T12:05Z',confidence=.4,field_provenance={'latitude':'assumed'},
              observation_id='x',block_face_id='b:left',observer_pseudonym='fixture',survey_start_utc='2026-10-25T12:00Z',survey_end_utc='2026-10-25T12:05Z',
              complete_face=False,latitude=34.06,longitude=-118.445,location_method='confirmed_map_pin',parking_type='unmetered')
    assert ManualObservation(**base).gps_accuracy_m is None
    with pytest.raises(ValueError): ManualObservation(**base,gps_accuracy_m=5)


def test_collector_contains_real_faces_and_no_third_party_requests():
    from la_parking.collector import build_collector
    # Integration artifact validation; no synthesized observations written.
    if not Path('reports/collector.html').exists(): pytest.skip('Build the collector first')
    html=Path('reports/collector.html').read_text(encoding='utf8')
    assert '/*__DATA__*/' not in html and '/*__APP__*/' not in html
    assert '<script src=' not in html and 'fetch(' not in html
    assert 'canonical_side' in html and 'unmetered' in html


def test_cli_report_artifacts_include_probability_and_baseline_tables(tmp_path):
    from la_parking.evaluation import run_evaluation
    train,held=data()
    train.to_csv(tmp_path/'train.csv',index=False); held.to_csv(tmp_path/'test.csv',index=False)
    report=run_evaluation(tmp_path/'train.csv',tmp_path/'test.csv','future_time',tmp_path/'fixture_report.json')
    assert json.loads((tmp_path/'fixture_report.json').read_text())['axis']=='future_time'
    markdown=(tmp_path/'fixture_report.md').read_text(encoding='utf8')
    assert 'Test R²' in markdown and 'Train-mean baseline MAE' in markdown and 'Brier' in markdown
    assert 'No held-out labels' in markdown
