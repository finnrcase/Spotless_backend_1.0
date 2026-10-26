"""Isolated synthetic media fixtures; never claimed as measured detector results."""
import json
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
import pytest
from PIL import Image
from la_parking.capture_collection import import_captures,import_reviews,import_effort,audit,MediaCapture,metadata_suggestions


def fixture(tmp_path):
    image=tmp_path/'synthetic.jpg';Image.new('RGB',(8,8),'gray').save(image)
    inv=tmp_path/'inventory.parquet';pd.DataFrame({'block_face_id':['synthetic:left']}).to_parquet(inv)
    row={'capture_id':'synthetic-1','block_face_id':'synthetic:left','session_id':'fixture-session','visit_id':'fixture-visit','source':'walking_camera',
        'media_path':str(image),'capture_at_utc':'2026-10-01T12:00Z','time_precision':'exact_offset','latitude':34.06,'longitude':-118.44,'privacy_reviewed':True,'identifiers_present':False,'detector_count_candidate':99}
    return row,inv,tmp_path/'db'


def write(tmp_path,name,rows):
    p=tmp_path/name;p.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8');return p


def review(cid,code,count=3):
    return {'review_id':cid+code,'capture_id':cid,'reviewer_code':code,'reviewed_at_utc':datetime.now(timezone.utc).isoformat(),'human_counted':True,
        'independent_blind_count':True,'capture_time_verified':True,'location_verified':True,'occupied_visible':count,'visible_fraction':1,'full_face_visible':True,'privacy_verified':True,'visible_scope_id':'whole-fixture-face','masks':[]}


def test_duplicate_bytes_and_adjacent_frames_are_not_independent(tmp_path):
    row,inv,db=fixture(tmp_path);same={**row,'capture_id':'synthetic-2'}
    other=tmp_path/'different.jpg';Image.new('RGB',(8,8),'white').save(other);adjacent={**row,'capture_id':'synthetic-3','media_path':str(other)}
    result=import_captures(write(tmp_path,'captures.jsonl',[row,same,adjacent]),db,inv)
    assert result['accepted']==3 and result['automatic_cv_labels']==0
    report=audit(db,tmp_path/'out');assert report['unique_sample_units']==1 and report['exact_byte_duplicate_captures']==1
    queue=json.loads((tmp_path/'out/review_queue.json').read_text());assert 'detector_count_candidate' not in queue[0]['capture']
    assert report['detector_count_mae'] is None and report['usable_count_units_per_operator_hour'] is None


def test_import_conflicts_are_atomic_and_identical_ids_idempotent(tmp_path):
    row,inv,db=fixture(tmp_path);path=write(tmp_path,'a.jsonl',[row]);import_captures(path,db,inv)
    assert import_captures(path,db,inv)['duplicate_identical_ids']==1
    with pytest.raises(ValueError,match='Conflicting'):
        import_captures(write(tmp_path,'bad.jsonl',[{**row,'capture_id':'synthetic-new'},{**row,'confidence':.9}]),db,inv)
    assert audit(db,tmp_path/'out')['captures']==1


def test_hidden_curb_and_cv_candidates_never_become_full_face_labels(tmp_path):
    row,inv,db=fixture(tmp_path);import_captures(write(tmp_path,'c.jsonl',[row]),db,inv)
    reviews=[review(row['capture_id'],code) for code in ['r1','r2']]
    for r in reviews:r.update(visible_fraction=.5,full_face_visible=False)
    import_reviews(write(tmp_path,'r.jsonl',reviews),db);report=audit(db,tmp_path/'out')
    assert report['count_agreement_sample_units']==1 and report['independent_count_mae_equal_weight_per_unit']==0
    assert report['reviewed_full_face_count_units']==0 and report['legal_vacancy_labels_promoted']==0


def test_blind_count_agreement_yield_and_conflict_review(tmp_path):
    row,inv,db=fixture(tmp_path);import_captures(write(tmp_path,'c.jsonl',[row]),db,inv)
    import_reviews(write(tmp_path,'r.jsonl',[review(row['capture_id'],'r1',3),review(row['capture_id'],'r2',4)]),db)
    report=audit(db,tmp_path/'out');assert report['reviewed_full_face_count_units']==0 and report['independent_count_mae_equal_weight_per_unit']==1
    third=review(row['capture_id'],'adjudicator',3);third.update(adjudicated=True,notes='Synthetic fixture adjudication')
    import_reviews(write(tmp_path,'third.jsonl',[third]),db)
    effort={'effort_id':'fixture-hour','operator_code':'fixture-op','start_utc':'2026-10-01T12:00Z','end_utc':'2026-10-01T13:00Z','activity':'review'}
    import_effort(write(tmp_path,'effort.jsonl',[effort]),db);report=audit(db,tmp_path/'out')
    assert report['usable_count_units_per_operator_hour']==1 and report['reviewed_full_face_count_units']==1
    with pytest.raises(ValueError,match='Overlapping'):import_effort(write(tmp_path,'overlap.jsonl',[{**effort,'effort_id':'other'}]),db)


def test_date_only_and_unverified_local_time_are_not_exact_truth(tmp_path):
    row,inv,db=fixture(tmp_path);row.update(capture_at_utc=None,time_precision='date_only',capture_date='2022-05-11')
    import_captures(write(tmp_path,'date.jsonl',[row]),db,inv)
    report=audit(db,tmp_path/'out');assert report['reviewed_full_face_count_units']==0
    assert metadata_suggestions(row['media_path'])['capture_at_utc'] is None
    with pytest.raises(ValueError,match='Exact offset'):MediaCapture.model_validate({**row,'capture_at_utc':'2026-10-01T12:00Z'})


def test_reserved_physical_blocks_are_quarantined_and_cannot_be_reviewed(tmp_path):
    row,inv,db=fixture(tmp_path);held=json.loads(Path('config/field_holdouts.json').read_text())['unseen_physical_blocks'][0]
    row['block_face_id']=held+':left';pd.DataFrame({'block_face_id':[row['block_face_id']]}).to_parquet(inv)
    import_captures(write(tmp_path,'hold.jsonl',[row]),db,inv)
    report=audit(db,tmp_path/'out');assert report['quarantined']==1 and report['queue_items']==0
    with pytest.raises(ValueError,match='quarantined'):import_reviews(write(tmp_path,'r.jsonl',[review(row['capture_id'],'r1')]),db)


def test_plan_excludes_all_holds_and_logs_conditional_sampling_probabilities(tmp_path):
    from la_parking.collection_design import plan
    result=plan(tmp_path/'plan');p=json.loads((tmp_path/'plan/development_plan.json').read_text())
    assert result['faces']==16 and result['planned_snapshots']==64 and len(p['assignments'])==64
    assert not set(r['block_id'] for r in p['faces_detail'])&set(result['protected_blocks_excluded'])
    assert all(0<r['selection']['conditional_draw_probability']<=1 and r['selection']['marginal_inclusion_probability'] is None for r in p['faces_detail'])
    assert {r['repeat_offset_minutes'] for r in p['assignments']}=={0,15,30,60}
