"""Causal synthetic experiment fixtures; never real performance evidence."""
import copy,json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from la_parking.controlled_observations import config,validate_labels,make_design,fit_development,evaluate_locked,partitions,predict,fit,features


def dataset():
    rows=[];ids={}
    for phase,day,blocks in [('train',1,'abcd'),('validation',3,'abcd'),('calibration',5,'abcd'),('known',7,'abcd'),('unseen',7,'efgh')]:
        ids[phase]=[]
        for i,b in enumerate(blocks):
            oid='synthetic-'+phase+'-'+b;t=pd.Timestamp(f'2026-10-{day:02d}T12:00Z')+pd.Timedelta(minutes=i*5);ids[phase].append(oid)
            rows.append({'source_id':'manual_field','observation_id':oid,'block_face_id':b+':left','block_id':b,'parking_type':'unmetered','observed_at_utc':t,'window_end_utc':t+pd.Timedelta('1min'),
                'retrieved_at_utc':t+pd.Timedelta('1min'),'label_available_at_utc':t+pd.Timedelta('2min'),'label_reviewed':True,'label_evidence':'direct_reviewed_full_face',
                'capacity_verified':True,'survey_session_id':'synthetic-'+phase,'intended_duration_minutes':60,'vehicle_class':'standard_passenger','permit_class':None,
                'occupancy_rate':(i+day)%8/10,'available_count':i%2,'at_least_one':i%2,'source_record_id':oid,'observer_confidence':.6})
    manifest={'data_kind':'synthetic_demo','splits':{axis:{'train_ids':ids['train'],'validation_ids':ids['validation'],'calibration_ids':ids['calibration'],'test_ids':ids[test]} for axis,test in [('known_block_future','known'),('unseen_block_future','unseen')]},
        'release':{'phase':'locked_test','evaluation_start_utc':'2026-10-07T00:00Z','evaluation_end_utc':'2026-10-08T00:00Z','freeze_file':'synthetic-unused-lock'}}
    cfg={**config(),'horizons_minutes':[15],'bootstrap_replicates':8,'minimum_rows':{k:1 for k in ['train','validation','calibration','test']},'minimum_training_blocks':1,'minimum_unseen_test_blocks':1}
    return pd.DataFrame(rows),manifest,cfg,ids


def test_context_is_causal_and_targets_are_not_recent_inputs():
    f,m,cfg,ids=dataset();f=validate_labels(f);ctx=pd.DataFrame([{'observation_id':ids['known'][0],'horizon_minutes':15,'available_at_utc':'2026-10-07T12:00Z','received_at_utc':'2026-10-07T12:00Z',**{c:9 for c in cfg['context_features']}}])
    rows=make_design(f,ctx,15,cfg);q=rows.loc[rows.observation_id.eq(ids['known'][0])].iloc[0]
    assert not q.context_supported and pd.isna(q.housing_density) and not q.recent_supported
    changed=f.copy();changed.loc[changed.observation_id.isin(ids['known']+ids['unseen']),'occupancy_rate']=.99
    a=make_design(changed,ctx,15,cfg)
    np.testing.assert_allclose(rows[['recent_rate','recent_vacant']].to_numpy(),a[['recent_rate','recent_vacant']].to_numpy(),equal_nan=True)


def test_recent_frame_must_finish_and_be_reviewed_before_issue_and_not_share_target_capture():
    f,m,cfg,ids=dataset();f=validate_labels(f);target=f.loc[f.observation_id.eq(ids['known'][0])].iloc[0].to_dict()
    prior={**target,'observation_id':'synthetic-recent','source_record_id':'synthetic-recent','observed_at_utc':pd.Timestamp('2026-10-07T11:20Z'),'window_end_utc':pd.Timestamp('2026-10-07T11:21Z'),'retrieved_at_utc':pd.Timestamp('2026-10-07T11:21Z'),'label_available_at_utc':pd.Timestamp('2026-10-07T11:22Z'),'occupancy_rate':.7}
    frame=pd.concat([f,pd.DataFrame([prior])],ignore_index=True)
    q=make_design(frame,pd.DataFrame(),15,cfg).set_index('observation_id').loc[target['observation_id']]
    assert q.recent_rate==.7 and q.recent_age_minutes==25
    frame.loc[frame.observation_id.eq('synthetic-recent'),'source_record_id']=target['source_record_id']
    assert not make_design(frame,pd.DataFrame(),15,cfg).set_index('observation_id').loc[target['observation_id']].recent_supported


def test_context_only_baseline_cannot_access_recent_features():
    f,m,cfg,ids=dataset();f=make_design(validate_labels(f),pd.DataFrame(),15,cfg);train=f.loc[f.observation_id.isin(ids['train'])];val=f.loc[f.observation_id.isin(ids['validation'])].copy();val['recent_rate']=.99
    a=fit(train,'occupancy_rate','persistence',features('A_reference',cfg),cfg);c=fit(train,'occupancy_rate','persistence',features('C_recent',cfg),cfg)
    assert not np.allclose(predict(a,val),.99) and np.allclose(predict(c,val),.99)


def test_separate_development_selection_and_locked_same_row_evaluation(tmp_path):
    f,m,cfg,ids=dataset();development=f.loc[~f.observation_id.isin(ids['known']+ids['unseen'])]
    out=tmp_path/'models';result=fit_development(development,pd.DataFrame(),m,out,cfg)
    assert not result['test_outcomes_opened'] and all(r['validation_only'] for r in result['learning_curves_validation_only'])
    report=evaluate_locked(f,pd.DataFrame(),m,out,tmp_path/'evaluation.json');rows=report['results']
    scored=[r for r in rows if r['status']=='scored'];assert scored and not report['test_used_for_selection']
    for axis in ['known_block_future','unseen_block_future']:
        for target in ['occupancy_rate','vacant_count','legal_vacancy']:
            same=[r for r in scored if r['axis']==axis and r['target']==target];assert len(same)==4 and len({r['row_sha256'] for r in same})==1
    assert all('loss_95_by_block_day' in r for r in scored)
    with pytest.raises(ValueError,match='frozen'):fit_development(development,pd.DataFrame(),m,out,cfg)
    altered=f.copy();altered.loc[altered.observation_id.isin(ids['known']),'occupancy_rate']=.01
    with pytest.raises(ValueError,match='Previously inspected'):evaluate_locked(altered,pd.DataFrame(),m,out,tmp_path/'evaluation.json')


def test_development_refuses_test_targets_and_wrong_block_grouping(tmp_path):
    f,m,cfg,ids=dataset()
    with pytest.raises(ValueError,match='test/undeclared'):fit_development(f,pd.DataFrame(),m,tmp_path/'model',cfg)
    f.loc[0,'block_id']='wrong'
    with pytest.raises(ValueError,match='Physical blocks'):validate_labels(f)


def test_all_three_horizons_use_actual_clock_and_declared_review_receipt():
    f,m,cfg,ids=dataset();f=validate_labels(f)
    for horizon in [15,30,60]:
        rows=make_design(f,pd.DataFrame(),horizon,cfg)
        assert ((rows.arrival_time_utc-rows.issued_at_utc)==pd.Timedelta(minutes=horizon)).all()
    f.loc[0,'label_available_at_utc']=f.loc[0,'observed_at_utc']
    with pytest.raises(ValueError,match='chronology'):validate_labels(f)
