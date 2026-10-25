"""Synthetic fixtures exercise controls only; never write real occupancy evidence."""
import copy
import json
from datetime import datetime,timedelta
import numpy as np
import pandas as pd
import pytest
from la_parking import unmetered as u


def experiment():
    rows=[];ids={}
    for partition,n,day in [('train',40,1),('validation',10,3),('calibration',10,5),('future',12,7),('unseen',12,7)]:
        ids[partition]=[]
        for i in range(n):
            kind='metered' if partition=='train' and i>=20 else 'unmetered'
            block=('new'+str(i%3) if partition=='unseen' else 'meter'+str(i%4) if kind=='metered' else 'known'+str(i%4))
            stamp=datetime.fromisoformat(f'2026-10-{day:02d}T16:00+00:00')+timedelta(minutes=i*5)
            oid=f'synthetic-{partition}-{i}';ids[partition].append(oid)
            rows.append(dict(observation_id=oid,block_id=block,block_face_id=block+':left',parking_type=kind,
                observed_at_utc=stamp.isoformat(),window_end_utc=(stamp+timedelta(minutes=2)).isoformat(),
                prediction_issued_at_utc=(stamp-timedelta(minutes=60)).isoformat(),
                feature_available_at_utc=(stamp-timedelta(minutes=65)).isoformat(),
                label_available_at_utc=(stamp+timedelta(hours=1)).isoformat(),
                label_evidence='direct_reviewed_full_face',label_reviewed=True,
                intended_duration_minutes=60,vehicle_class='standard_passenger',permit_class=None,
                demand=float(i%7),physical_capacity=10.,restriction_minutes=float(i%2)*30,
                occupancy_rate=(i%7+1)/10,available_count=i%4,at_least_one=int(i%4>0),
                capacity_basis='estimated_positions' if i%2 else 'marked_spaces',sampling_method='randomized'))
    splits={axis:dict(train_ids=ids['train'],validation_ids=ids['validation'],calibration_ids=ids['calibration'],test_ids=ids[test]) for axis,test in [('future_time','future'),('unseen_block','unseen')]}
    manifest=dict(features=['demand','physical_capacity','restriction_minutes'],
        feature_families=dict(demand=['demand'],curb_supply=['physical_capacity'],time_dependent_restrictions=['restriction_minutes']),splits=splits)
    cfg={**u.config(),'parameter_candidates':[7],'auxiliary_metered_weights':[.25],'bootstrap_replicates':20}
    return pd.DataFrame(rows),manifest,cfg


def field_record():
    return dict(observation_id='synthetic-review',block_face_id='known:left',parking_type='unmetered',
        complete_face=True,rules_checked=True,occupied=4,vacant_legal=2,unsuitable=1,surveyed_capacity=7,
        capacity_basis='estimated_positions',intended_duration_minutes=60,
        survey_start_utc='2026-10-01T16:00Z',survey_end_utc='2026-10-01T16:02Z')


def review_record():
    return dict(observation_id='synthetic-review',counts_verified=True,location_verified=True,capacity_verified=True,
        rules_verified=True,reviewed_by='fixture-reviewer',reviewed_at_utc='2026-10-02T16:00Z')


def test_missing_observations_remain_unavailable(tmp_path):
    report=u.unavailable_report(tmp_path/'absent.parquet',tmp_path/'report')
    assert report['field_identified_unmetered_records']==0
    assert report['metered_training_improves_unmetered']=='not_evaluated'
    assert not report['production_transfer_authorized']
    for groups in report['comparisons'].values():
        for metrics in groups.values():assert metrics['test_r2'] is None and metrics['mae'] is None
    assert json.loads((tmp_path/'report/comparison.json').read_text())==report


def test_review_is_separate_from_intake_and_requires_counts_rules_and_capacity():
    obs=pd.DataFrame([field_record()]);review=pd.DataFrame([review_record()])
    approved,rejected=u.reviewed_labels(obs,review)
    assert not rejected and approved.occupancy_rate.iloc[0]==pytest.approx(4/7)
    assert approved.label_reviewed.iloc[0] and approved.available_count.iloc[0]==2
    assert approved.label_evidence.iloc[0]=='direct_reviewed_full_face'
    for field,value in [('rules_verified',False),('capacity_verified',False),('reviewed_at_utc','bad timestamp')]:
        bad=review.copy();bad.loc[0,field]=value
        labels,reasons=u.reviewed_labels(obs,bad)
        assert labels.empty and len(reasons)==1
    for field,value in [('vacant_legal',3),('complete_face',False),('capacity_basis','unknown'),('intended_duration_minutes',None)]:
        bad=obs.copy();bad.loc[0,field]=value
        labels,reasons=u.reviewed_labels(bad,review)
        assert labels.empty and len(reasons)==1


def test_preparation_joins_predictors_without_creating_or_overwriting_labels():
    obs=pd.DataFrame([field_record()]);review=pd.DataFrame([review_record()])
    predictors=pd.DataFrame([dict(observation_id='synthetic-review',demand=2,physical_capacity=7,
        prediction_issued_at_utc='2026-10-01T15:00Z',feature_available_at_utc='2026-09-30T00:00Z')])
    inventory=pd.DataFrame([dict(block_face_id='known:left',segment_id='known')])
    table,rejected=u.prepare_table(obs,review,predictors,inventory)
    assert not rejected and table.block_id.iloc[0]=='known' and table.occupancy_rate.iloc[0]==pytest.approx(4/7)
    with pytest.raises(ValueError,match='overwrite'):u.prepare_table(obs,review,predictors.assign(available_count=5),inventory)
    with pytest.raises(ValueError,match='overwrite'):u.prepare_table(obs,review,predictors.assign(block_id='new'),inventory)
    with pytest.raises(ValueError,match='No reviewed'):u.prepare_table(obs,review.assign(rules_verified=False),predictors,inventory)


@pytest.mark.parametrize('evidence',['partial_meter_panel','business_density_proxy','assumed_vacancy'])
def test_auxiliary_predictors_and_partial_panels_cannot_become_occupancy_labels(evidence):
    frame,manifest,cfg=experiment();frame.loc[0,'label_evidence']=evidence
    with pytest.raises(ValueError,match='incompatible labels'):u.compare(frame,manifest,cfg)


def test_missing_review_and_future_features_are_rejected():
    frame,manifest,cfg=experiment();frame.loc[0,'label_reviewed']=False
    with pytest.raises(ValueError,match='reviewed'):u.compare(frame,manifest,cfg)
    frame,manifest,cfg=experiment();frame.loc[0,'feature_available_at_utc']='2026-10-20T00:00Z'
    with pytest.raises(ValueError,match='timestamp leakage'):u.compare(frame,manifest,cfg)
    frame,manifest,cfg=experiment();manifest['features'].append('available_count')
    with pytest.raises(ValueError,match='leakage'):u.compare(frame,manifest,cfg)


def test_unseen_blocks_cannot_leak_via_auxiliary_metered_opposite_curbs():
    frame,manifest,cfg=experiment()
    mask=(frame.parking_type=='metered')&(frame.block_id=='meter0')
    frame.loc[mask,'block_id']='new0';frame.loc[mask,'block_face_id']='new0:right'
    f=u.validate_experiment(frame,manifest,manifest['features'],cfg)
    with pytest.raises(ValueError,match='opposite-side'):u.split_rows(f,'unseen_block',manifest['splits']['unseen_block'],cfg)
    frame,manifest,cfg=experiment();manifest['splits']['future_time']['test_ids']=manifest['splits']['unseen_block']['test_ids']
    f=u.validate_experiment(frame,manifest,manifest['features'],cfg)
    with pytest.raises(ValueError,match='revisit observed'):u.split_rows(f,'future_time',manifest['splits']['future_time'],cfg)


def test_required_predictor_families_cannot_silently_disappear():
    frame,manifest,cfg=experiment();manifest['features'].remove('restriction_minutes')
    with pytest.raises(ValueError,match='explicit unavailable'):u.compare(frame,manifest,cfg)
    manifest['unavailable_families']={'time_dependent_restrictions':'No historically verified restriction coverage'}
    assert len(u.validate_experiment(frame,manifest,manifest['features'],cfg))==len(frame)


def test_full_comparison_uses_identical_unmetered_tests_and_positive_auxiliary_weight(tmp_path,monkeypatch):
    frame,manifest,cfg=experiment();calls=[];real_fit=u._fit
    def fit(data,*args,**kwargs):
        calls.append((set(data.parking_type),kwargs.get('meter_weight')))
        return real_fit(data,*args,**kwargs)
    monkeypatch.setattr(u,'_fit',fit)
    report=u.compare(frame,manifest,cfg);u.write_report(report,tmp_path)
    assert any(kinds=={'metered','unmetered'} and weight==.25 for kinds,weight in calls)
    assert any(kinds=={'unmetered'} for kinds,_ in calls)
    for axis,groups in report['comparisons'].items():
        assert len(groups)==6
        for strategy,targets in groups.items():
            for target,metrics in targets.items():
                assert metrics['n']==12 and metrics['test_population']=='unmetered' and metrics['prediction_coverage']==1
                assert set(metrics['by_capacity_basis'])=={'marked_spaces','estimated_positions'}
                if target=='at_least_one':
                    assert 0<=metrics['brier_score']<=1 and sum(b['n'] for b in metrics['reliability_bins'])==12
                else:assert np.isfinite(metrics['mae']) and 'r2' in metrics
        assert len(report['coverage'][axis]['test_observation_ids'])==12
        for selected in report['selection'][axis]['unmetered_plus_metered'].values():assert selected['uses_metered_labels'] and selected['metered_weight']>0
    assert not report['production_transfer_authorized'] and not report['aspiration_is_acceptance_criterion']
    assert 'Paired changes' in (tmp_path/'comparison.md').read_text(encoding='utf8')
    json.dumps(report,allow_nan=False)


def test_model_selection_and_calibration_never_use_final_test_targets():
    frame,manifest,cfg=experiment();first=u.compare(frame,manifest,cfg)
    altered=frame.copy();test_ids=set(manifest['splits']['future_time']['test_ids']+manifest['splits']['unseen_block']['test_ids'])
    mask=altered.observation_id.isin(test_ids)
    altered.loc[mask,'occupancy_rate']=1-altered.loc[mask,'occupancy_rate']
    altered.loc[mask,'available_count']=3-altered.loc[mask,'available_count']
    altered.loc[mask,'at_least_one']=altered.loc[mask,'available_count'].gt(0).astype(int)
    second=u.compare(altered,copy.deepcopy(manifest),cfg)
    assert first['selection']==second['selection']
    assert first['comparisons']!=second['comparisons']


def test_no_metered_auxiliary_or_inconsistent_targets_fail_explicitly():
    frame,manifest,cfg=experiment();frame.loc[frame.parking_type=='metered','parking_type']='unmetered'
    with pytest.raises(ValueError,match='compatible metered'):u.compare(frame,manifest,cfg)
    frame,manifest,cfg=experiment();frame.loc[0,'at_least_one']=1
    with pytest.raises(ValueError,match='labels disagree'):u.compare(frame,manifest,cfg)


def test_late_label_reviews_cannot_enter_earlier_forecast_training():
    frame,manifest,cfg=experiment();frame.loc[0,'label_available_at_utc']='2026-10-06T00:00Z'
    with pytest.raises(ValueError,match='review availability'):u.compare(frame,manifest,cfg)


def test_persistence_only_uses_fresh_prior_states_and_abstains_to_reported_fallback():
    frame,manifest,cfg=experiment();test=frame.loc[frame.observation_id.isin(manifest['splits']['future_time']['test_ids'])].copy()
    test['lagged_observed_occupancy']=.7;test['lag_age_minutes']=10
    pred,coverage=u.persistence_baseline(test,'occupancy_rate',.2,'future_time',cfg)
    assert coverage==1 and np.all(pred==.7)
    test['lag_age_minutes']=20
    pred,coverage=u.persistence_baseline(test,'occupancy_rate',.2,'future_time',cfg)
    assert coverage==0 and np.all(pred==.2)
    test['lag_age_minutes']=5
    pred,coverage=u.persistence_baseline(test,'occupancy_rate',.2,'unseen_block',cfg)
    assert coverage==0 and np.all(pred==.2)


def test_prepare_and_compare_files_end_to_end(tmp_path,monkeypatch):
    frame,manifest,cfg=experiment();observations=[];reviews=[]
    for i,r in frame.iterrows():
        observations.append({**field_record(),'observation_id':r.observation_id,'block_face_id':r.block_face_id,
            'parking_type':r.parking_type,'occupied':5+i%3,'vacant_legal':r.available_count,
            'unsuitable':10-(5+i%3)-r.available_count,'surveyed_capacity':10,'capacity_basis':r.capacity_basis,
            'vehicle_class':r.vehicle_class,'permit_class':r.permit_class,
            'survey_start_utc':r.observed_at_utc,'survey_end_utc':r.window_end_utc})
        reviews.append({**review_record(),'observation_id':r.observation_id,'reviewed_at_utc':r.label_available_at_utc})
    obs_path=tmp_path/'synthetic_observations.parquet';pd.DataFrame(observations).to_parquet(obs_path,index=False)
    reviews_path=tmp_path/'synthetic_reviews.csv';pd.DataFrame(reviews).to_csv(reviews_path,index=False)
    predictors_path=tmp_path/'synthetic_predictors.parquet'
    frame[['observation_id','prediction_issued_at_utc','feature_available_at_utc']+manifest['features']].to_parquet(predictors_path,index=False)
    inventory_path=tmp_path/'synthetic_inventory.parquet'
    frame[['block_face_id','block_id']].drop_duplicates().rename(columns={'block_id':'segment_id'}).to_parquet(inventory_path,index=False)
    table_path=tmp_path/'synthetic_prepared.parquet'
    audit=u.prepare(reviews_path,predictors_path,table_path,obs_path,inventory_path)
    assert audit['prepared_rows']==len(frame) and not audit['rejected'] and len(audit['source_sha256'])==4
    manifest_path=tmp_path/'synthetic_manifest.json';manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(u,'config',lambda:cfg)
    report=u.run(table_path,manifest_path,tmp_path/'synthetic_report')
    assert report['status']=='evaluated_on_held_out_unmetered_only' and report['input_sha256']
    assert (tmp_path/'synthetic_report/comparison.json').exists()
