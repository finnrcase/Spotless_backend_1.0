"""Synthetic geometry only; these tests are not flight or detector evidence."""
import json
from pathlib import Path
import pytest
from la_parking.drone_feasibility import validate,camera_geometry,segment_coverage,simulate,mission_preview,build_sdk_plan


def config():
    return json.loads(Path('config/drone_feasibility.json').read_text())


def face(name='fixture',start=0,length=100):
    return {'face_id':name,'xy':[[start,0],[start+length,0]]}


def test_default_is_offline_and_rejects_aircraft_transports():
    cfg=config();assert validate(cfg)['transport']=='disabled'
    for change in [{'mode':'real'},{'real_aircraft_enabled':True},{'transport':'udp://127.0.0.1:14540'},{'battery_reserve_fraction':0},{'speed_m_s':float('nan')}]:
        with pytest.raises(ValueError):validate({**cfg,**change})
    with pytest.raises(ValueError,match='offline'):build_sdk_plan({'data_kind':'simulation','transport':'serial'})


def test_camera_equations_and_sparse_trigger_gaps():
    cfg=config();g=camera_geometry(cfg)
    assert g['footprint_width_m']==pytest.approx(45) and g['footprint_along_track_m']==pytest.approx(30)
    assert g['gsd_width_m_per_pixel']==pytest.approx(.01125)
    assert segment_coverage(100,0,25,cfg,30)[0]==pytest.approx(1)
    sparse={**cfg,'capture_interval_seconds':20}
    assert 0<segment_coverage(100,0,25,sparse,10)[0]<.3


def test_budget_reserve_unreachable_faces_and_requested_population():
    cfg=config();r=simulate([face(),face('unreachable',1e6)],cfg)
    assert r['requested_faces']==2 and r['covered_faces']==1 and r['infeasible_faces']==['unreachable']
    assert all(s['flight_seconds_including_overhead']<=s['battery_budget_seconds'] for s in r['sorties'])
    assert not any(r['revisit_targets_feasible_under_assumptions'].values())
    assert r['mean_visible_fraction_all_requested_faces_simulated']==pytest.approx(r['mean_visible_curb_fraction_simulated']/2)
    with pytest.raises(ValueError,match='no route time'):simulate([face()],{**cfg,'battery_minutes':1})


def test_unique_units_and_explicit_yield_assumptions():
    cfg=config();r=simulate([face()],cfg);assert r['capture_frames_simulated']>r['unique_face_visit_units_simulated']==1
    assert r['expected_complete_count_units_simulated']==pytest.approx(.3)
    assert r['detector_metrics'] is None and r['forecast_improvement'] is None and not r['airspace_or_operational_approval']
    more_hidden=simulate([face()],{**cfg,'tree_occlusion_fraction':.8})
    assert more_hidden['mean_visible_curb_fraction_simulated']<r['mean_visible_curb_fraction_simulated']
    assert 'not inferred' in r['yield_assumption_note']
    with pytest.raises(ValueError,match='Duplicate'):simulate([face(),face()],cfg)
    with pytest.raises(ValueError,match='Finite'):simulate([{'face_id':'bad','xy':[[0,0],[float('nan'),1]]}],cfg)


def test_preview_is_relocated_and_never_connects(monkeypatch):
    cfg=config();r=simulate([face(start=368000)],cfg)
    preview=mission_preview(r,cfg)
    first=preview['mission_items'][0]
    assert first['latitude_deg']==pytest.approx(cfg['sitl_synthetic_home'][0])
    assert first['longitude_deg']==pytest.approx(cfg['sitl_synthetic_home'][1])
    assert preview['transport']=='disabled' and 'NOT a real Westwood' in preview['coordinate_scope']
    assert first['vehicle_action']=='TAKEOFF' and preview['mission_items'][-1]['vehicle_action']=='LAND'


def test_configured_capture_budget_is_bounded():
    cfg={**config(),'capture_interval_seconds':.00001}
    with pytest.raises(ValueError,match='100,000'):segment_coverage(100,0,25,cfg,30)
