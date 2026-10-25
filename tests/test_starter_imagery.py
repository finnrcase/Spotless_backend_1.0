"""Real source audits and isolated synthetic annotation fixtures; no field labels."""
import copy
import json
from pathlib import Path
import zipfile
import pytest
from la_parking.starter import verify_layer,resolve_package
from la_parking.imagery import evaluate_annotations,source_metadata
from la_parking.field_route import local_slot
from la_parking.contracts import ManualObservation


def imagery_fixture():
    task={'task_id':'synthetic-task','image':{'sha256':'fixture-hash','width':100,'height':100}}
    record={'task_id':'synthetic-task','image_sha256':'fixture-hash','annotator':'fixture-human-attestation',
        'reviewed_by_human':True,'annotation_complete':True,'shapes':[
            {'class':'visible_curb','points':[[0,0],[100,0],[100,100],[0,100]]},
            {'class':'tree_occluded','points':[[60,0],[100,0],[100,100],[60,100]]},
            {'class':'curbside_vehicle_candidate','box':[10,10,10,10]},
            {'class':'curbside_vehicle_candidate','box':[70,70,10,10]},
            {'class':'traffic_lane_vehicle','box':[30,30,10,10]}]}
    prediction={'task_id':'synthetic-task','image_sha256':'fixture-hash','detector_id':'synthetic-test-only',
        'boxes':[[10,10,10,10],[30,30,10,10],[70,70,10,10]]}
    return {'tasks':[task]},record,prediction


def test_no_detector_or_independent_labels_never_produces_fake_mae():
    manifest,record,prediction=imagery_fixture()
    r=evaluate_annotations(manifest,[])
    assert r['count_mae'] is None and r['precision'] is None and r['paired_faces']==0
    record['reviewed_by_human']=False
    assert evaluate_annotations(manifest,[record],[prediction])['count_mae'] is None


def test_historic_vehicle_scoring_excludes_occlusion_and_separates_traffic():
    manifest,record,prediction=imagery_fixture()
    r=evaluate_annotations(manifest,[record],[prediction])
    assert r['count_mae']==1 and r['true_positives']==1 and r['false_positives']==1 and r['false_negatives']==0
    assert r['precision']==.5 and r['recall']==1
    assert r['rows'][0]['reference_visible_candidates']==1 and r['rows'][0]['visible_fraction_of_image']==.6
    assert 'not legal vacancy' in r['evaluation_target'] and r['prediction_coverage_among_eligible_reviewed_faces']==1


def test_reference_masks_hashes_duplicates_and_prediction_bounds_are_checked():
    manifest,record,prediction=imagery_fixture()
    with pytest.raises(ValueError,match='Duplicate reference'):evaluate_annotations(manifest,[record,record],[prediction])
    with pytest.raises(ValueError,match='Duplicate or unknown'):evaluate_annotations(manifest,[record],[prediction,prediction])
    bad=copy.deepcopy(record);bad['image_sha256']='different'
    with pytest.raises(ValueError,match='hash mismatch'):evaluate_annotations(manifest,[bad])
    bad=copy.deepcopy(record);bad['shapes'][0]['points']=[[0,0],[100,100],[0,100],[100,0]]
    with pytest.raises(ValueError,match='Invalid area'):evaluate_annotations(manifest,[bad])
    bad=copy.deepcopy(prediction);bad['boxes']=[[95,95,10,10]]
    with pytest.raises(ValueError,match='prediction box'):evaluate_annotations(manifest,[record],[bad])
    record['shapes']=[s for s in record['shapes'] if s['class']!='visible_curb']
    assert evaluate_annotations(manifest,[record],[prediction])['count_mae'] is None


def test_complete_empty_visible_curb_can_be_zero_but_unknown_visibility_cannot():
    manifest,record,prediction=imagery_fixture();record['shapes']=record['shapes'][:1];prediction['boxes']=[]
    r=evaluate_annotations(manifest,[record],[prediction]);assert r['count_mae']==0 and r['recall'] is None
    record['shapes']=[]
    assert evaluate_annotations(manifest,[record],[prediction])['count_mae'] is None


def test_source_raster_resolution_and_identity_are_pinned():
    checks={'naip_source_raster_info':{'data':{'pixelSizeX':.6,'pixelSizeY':.6,'extent':{'xmin':0,'ymin':0,'xmax':100,'ymax':100,'spatialReference':{'wkid':26911}}}},
        'naip_current_scene_identity':{'data':{'attributes':{'Name':'m_3411861_nw_11_060_20220511','Category':1}}}}
    assert source_metadata(checks)[0]['pixelSizeX']==.6
    bad=copy.deepcopy(checks);bad['naip_source_raster_info']['data']['pixelSizeX']=.3
    with pytest.raises(ValueError,match='native raster'):source_metadata(bad)
    bad=copy.deepcopy(checks);bad['naip_current_scene_identity']['data']['attributes']['Category']=2
    with pytest.raises(ValueError,match='identity changed'):source_metadata(bad)


def test_starter_real_pages_reconcile_independent_ids_and_preserve_age():
    package=Path('data/reference/parking_data_starter')
    if not package.exists():pytest.skip('Real supplied starter package not present')
    for name,count in [('curbs',6402),('driveways',1803)]:
        frame,audit=verify_layer(package,name)
        assert len(frame)==count and audit['all_ids_reconciled'] and audit['outside_exact_requested_bbox']>0
        assert frame.parking_capacity.isna().all() and frame.current_legal_status.eq('unknown').all()
        assert frame.source_imagery_year.eq(2014).all()


def test_false_completeness_claim_and_unsafe_archive_are_rejected(tmp_path):
    package=tmp_path/'synthetic-package';data=package/'data';data.mkdir(parents=True)
    feature={'type':'Feature','properties':{'OBJECTID':1},'geometry':{'type':'Polygon','coordinates':[[[-118.45,34.06],[-118.449,34.06],[-118.449,34.061],[-118.45,34.061],[-118.45,34.06]]]}}
    objects={'curbs_metadata.json':{'objectIdField':'OBJECTID','fields':[]},'curbs_count.json':{'count':2},'curbs_ids.json':{'objectIds':[1,2]},
        'curbs_pilot_complete.geojson':{'type':'FeatureCollection','features':[feature]},'curbs_page_00000.geojson':{'type':'FeatureCollection','features':[feature]}}
    for name,obj in objects.items():(data/name).write_text(json.dumps(obj))
    with pytest.raises(ValueError,match='incomplete/duplicate'):verify_layer(package,'curbs')
    archive=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../unsafe.txt','synthetic')
    with pytest.raises(ValueError,match='Unsafe'):resolve_package(archive)


def test_local_wall_time_survives_fall_dst_and_plan_preserves_holdouts():
    assert local_slot('2026-10-29',9).tz_convert('UTC').hour==16
    assert local_slot('2026-11-01',9).tz_convert('UTC').hour==17
    path=Path('reports/field_route.json')
    if not path.exists():pytest.skip('Build route first')
    plan=json.loads(path.read_text());assert len(plan['faces'])==20 and len(plan['assignments'])==204
    assert plan['observations_actually_collected']==0
    for block in plan['heldout_physical_block_ids']:
        rows=[r for r in plan['assignments'] if r['block_id']==block]
        assert {r['canonical_side'] for r in rows}=={'left','right'} and all(r['evaluation_role']=='unseen_block_holdout' for r in rows)
    repeats=[r for r in plan['assignments'] if r['repeat_offset_minutes'] is not None]
    assert len(repeats)==24 and {r['repeat_offset_minutes'] for r in repeats}=={0,15,30,60}


def test_manual_raw_gaps_are_not_automatically_stalls():
    base=dict(source_id='synthetic-test',source_record_id='fixture',source_version='test',retrieved_at_utc='2026-10-25T12:05Z',
        confidence=.4,field_provenance={},observation_id='fixture',block_face_id='fixture:left',observer_pseudonym='test',
        survey_start_utc='2026-10-25T12:00Z',survey_end_utc='2026-10-25T12:05Z',complete_face=False,
        location_method='confirmed_map_pin',latitude=34.06,longitude=-118.44)
    r=ManualObservation(**base,gap_lengths_m=[4.5,9.2],survey_session_id='test-session')
    assert r.gap_lengths_m==[4.5,9.2] and r.surveyed_capacity is None
    assert ManualObservation(**base,gap_lengths_m=[]).gap_lengths_m==[]
    assert ManualObservation(**base).gap_lengths_m is None
    for values in [[float('inf')],[-1],[0]]:
        with pytest.raises(ValueError):ManualObservation(**base,gap_lengths_m=values)
