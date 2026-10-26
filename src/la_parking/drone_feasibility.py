"""Offline route/camera arithmetic and mission objects. No aircraft transport."""
import importlib.metadata,json,math,shutil,sys
from pathlib import Path
from copy import deepcopy
import geopandas as gpd
import numpy as np
from .spatial import METRIC_CRS


def validate(cfg):
    if cfg['mode']!='offline_simulation_only' or cfg['real_aircraft_enabled'] or cfg['transport']!='disabled':raise ValueError('Only offline simulation is implemented; aircraft connections are disabled')
    positive=['altitude_m','speed_m_s','battery_minutes','capture_interval_seconds','sensor_width_mm','sensor_height_mm','focal_length_mm','image_width_px','image_height_px']
    if any(not math.isfinite(cfg[k]) or cfg[k]<=0 for k in positive):raise ValueError('Positive finite camera/route settings required')
    for k in ['battery_reserve_fraction','tree_occlusion_fraction','shadow_occlusion_fraction','assumed_full_face_visibility_probability']:
        if not 0<=cfg[k]<1:raise ValueError('Fractions must be in [0,1)')
    if cfg['battery_reserve_fraction']==0:raise ValueError('A nonzero battery reserve is required even in the scenario')
    if any(not math.isfinite(cfg[k]) or cfg[k]<0 for k in ['flight_overhead_seconds','battery_turnaround_minutes','setup_operator_minutes','review_minutes_per_face']):raise ValueError('Negative/nonfinite operator or overhead assumption')
    return cfg


def camera_geometry(cfg):
    validate(cfg);width=cfg['altitude_m']*cfg['sensor_width_mm']/cfg['focal_length_mm'];length=cfg['altitude_m']*cfg['sensor_height_mm']/cfg['focal_length_mm']
    return {'footprint_width_m':width,'footprint_along_track_m':length,'gsd_width_m_per_pixel':width/cfg['image_width_px'],'gsd_height_m_per_pixel':length/cfg['image_height_px'],
        'trigger_spacing_m':cfg['speed_m_s']*cfg['capture_interval_seconds'],'all_values_simulated_from_camera_assumptions':True}


def route_faces(plan_path='reports/collection/development_plan.json'):
    plan=json.loads(Path(plan_path).read_text());wanted=[r['block_face_id'] for r in plan['faces_detail']]
    faces=gpd.read_parquet('data/processed/pilot_block_faces.parquet').to_crs(METRIC_CRS).set_index('block_face_id');result=[]
    for fid in wanted:
        r=faces.loc[fid];geom=r.geometry
        if geom.geom_type=='LineString':line=geom
        elif geom.geom_type=='MultiLineString':line=max(geom.geoms,key=lambda g:g.length)
        else:
            # Curb polygons are footprints, not flight paths. Explicitly use the
            # corresponding street offset as an approximate planning fallback.
            streets=gpd.read_parquet('data/processed/pilot_street_segments.parquet').to_crs(METRIC_CRS).set_index('segment_id');line=streets.loc[r.segment_id].geometry.offset_curve(8 if r.side=='left' else -8)
        result.append({'face_id':fid,'xy':[[float(x),float(y)] for x,y,*_ in line.coords],'length_m':float(line.length),'geometry_method':r.geometry_method})
    return result


def segment_coverage(length,start_seconds,finish_seconds,cfg,footprint):
    interval=cfg['capture_interval_seconds'];first=math.ceil(start_seconds/interval);last=math.floor(finish_seconds/interval)
    if last-first>100000:raise ValueError('Capture budget exceeds 100,000 frames per face')
    spans=[]
    for n in range(first,last+1):
        center=(n*interval-start_seconds)*cfg['speed_m_s'];spans.append((max(0,center-footprint/2),min(length,center+footprint/2)))
    covered=0.;end=0.
    for a,b in spans:
        if b>max(a,end):covered+=b-max(a,end)
        end=max(end,b)
    return covered/max(length,1e-9),max(0,last-first+1)


def simulate(faces,cfg):
    validate(cfg);camera=camera_geometry(cfg)
    if not faces or len(faces)>30:raise ValueError('A bounded route of 1–30 faces is required')
    if len({f['face_id'] for f in faces})!=len(faces):raise ValueError('Duplicate face IDs would inflate independent coverage')
    for face in faces:
        xy=np.asarray(face['xy'],dtype=float)
        if xy.ndim!=2 or xy.shape[1]!=2 or len(xy)<2 or not np.isfinite(xy).all():raise ValueError('Finite projected XY polylines required')
    speed=cfg['speed_m_s'];available=cfg['battery_minutes']*60*(1-cfg['battery_reserve_fraction']);overhead=cfg['flight_overhead_seconds']
    if available<=overhead:raise ValueError('Reserve leaves no route time after ascent/landing overhead')
    home=np.array(faces[0]['xy'][0]);remaining=list(faces);sorties=[];unreachable=[];records=[]
    while remaining:
        position=home.copy();elapsed=overhead;distance=0.;visits=[];points=[home.tolist()];consumed=[]
        for face in remaining:
            coords=np.array(face['xy']);coords=coords if np.linalg.norm(coords[0]-position)<=np.linalg.norm(coords[-1]-position) else coords[::-1]
            transit=float(np.linalg.norm(coords[0]-position));service=float(np.linalg.norm(np.diff(coords,axis=0),axis=1).sum());rth=float(np.linalg.norm(coords[-1]-home))
            if elapsed+(transit+service+rth)/speed>available:
                if not visits:unreachable.append(face['face_id']);consumed.append(face)
                continue
            start=elapsed+transit/speed;finish=start+service/speed;coverage,frames=segment_coverage(service,start,finish,cfg,camera['footprint_along_track_m'])
            visits.append({'face_id':face['face_id'],'geometric_curb_fraction':coverage,'assumed_visible_curb_fraction':coverage*(1-cfg['tree_occlusion_fraction'])*(1-cfg['shadow_occlusion_fraction']),
                'service_capture_frames':frames,'service_start_seconds':start,'service_end_seconds':finish,'count_truth_available':False})
            points.extend(coords.tolist());position=coords[-1];elapsed=finish;distance+=transit+service;consumed.append(face)
        if visits:
            rth=float(np.linalg.norm(position-home));elapsed+=rth/speed;distance+=rth;points.append(home.tolist())
            sorties.append({'flight_seconds_including_overhead':elapsed,'distance_m':distance,'waypoints_xy':points,'visits':visits,'battery_budget_seconds':available,'reserve_retained':elapsed<=available})
            records.extend(visits)
        if not consumed:raise ValueError('Route allocation made no progress')
        remaining=[r for r in remaining if r not in consumed]
    cycle=sum(s['flight_seconds_including_overhead'] for s in sorties)+max(0,len(sorties)-1)*cfg['battery_turnaround_minutes']*60
    operator_minutes=cfg['setup_operator_minutes']+cycle/60+len(records)*cfg['review_minutes_per_face']
    full=sum(v['geometric_curb_fraction']>=1-1e-6 for v in records);expected=full*cfg['assumed_full_face_visibility_probability']
    report={'data_kind':'simulation','mode':cfg['mode'],'camera':camera,'requested_faces':len(faces),'covered_faces':len(records),'infeasible_faces':unreachable,'sorties':sorties,
        'cycle_minutes_simulated':cycle/60,'revisit_interval_minutes_simulated':cycle/60+cfg['battery_turnaround_minutes'] if sorties else None,
        'capture_frames_simulated':sum(v['service_capture_frames'] for v in records),'unique_face_visit_units_simulated':len(records),
        'mean_visible_curb_fraction_simulated':float(np.mean([v['assumed_visible_curb_fraction'] for v in records])) if records else None,
        'mean_visible_fraction_all_requested_faces_simulated':sum(v['assumed_visible_curb_fraction'] for v in records)/len(faces),
        'operator_minutes_assumed':operator_minutes,'expected_complete_count_units_simulated':expected,
        'expected_usable_count_units_per_operator_hour_simulated':expected/(operator_minutes/60) if operator_minutes else None,
        'revisit_targets_feasible_under_assumptions':{str(m):bool(sorties and cycle/60+cfg['battery_turnaround_minutes']<=m and not unreachable) for m in [15,30,60]},
        'assumptions':cfg['assumptions'],'full_face_visibility_probability_assumed':cfg['assumed_full_face_visibility_probability'],
        'yield_assumption_note':'Full-face visibility probability is a separate unmeasured input, not inferred from mean visible curb area. Occlusion-area scenarios alone do not change that probability.',
        'real_flight_executed':False,'airspace_or_operational_approval':False,'detector_metrics':None,'forecast_improvement':None}
    return report


def mission_preview(simulation,cfg):
    """Relocate relative XY into a synthetic SITL field; no real Westwood plan."""
    from pyproj import Geod
    geod=Geod(ellps='WGS84');lat,lon=cfg['sitl_synthetic_home'];items=[]
    if simulation['sorties']:
        points=simulation['sorties'][0]['waypoints_xy'];origin=np.array(points[0])
        for i,xy in enumerate(points):
            delta=np.array(xy)-origin;east,north=map(float,delta);heading=math.degrees(math.atan2(east,north));distance=math.hypot(east,north);lng,lt,_=geod.fwd(lon,lat,heading,distance)
            items.append({'latitude_deg':lt,'longitude_deg':lng,'relative_altitude_m':float(cfg['altitude_m']),'speed_m_s':float(cfg['speed_m_s']),'is_fly_through':False,
                'gimbal_pitch_deg':-90.,'gimbal_yaw_deg':0.,'camera_action':'START_PHOTO_INTERVAL' if i==0 else 'STOP_PHOTO_INTERVAL' if i==len(points)-1 else 'NONE',
                'loiter_time_s':0.,'camera_photo_interval_s':float(cfg['capture_interval_seconds']),'acceptance_radius_m':1.,'yaw_deg':0.,'camera_photo_distance_m':0.,
                'vehicle_action':'TAKEOFF' if i==0 else 'LAND' if i==len(points)-1 else 'NONE'})
    return {'data_kind':'simulation','coordinate_scope':'Synthetic test-field relocation of relative route shape; NOT a real Westwood flight plan','transport':'disabled',
        'px4_tag':cfg['px4_tag'],'mavsdk_version':cfg['mavsdk_version'],'mission_items':items}


def build_sdk_plan(preview):
    """Construct pinned SDK data objects only. Never instantiate/connect a vehicle."""
    if preview.get('transport')!='disabled' or preview.get('data_kind')!='simulation':raise ValueError('Only offline mission objects are accepted')
    runtime=Path('data/drone_feasibility/runtime')
    if runtime.exists():sys.path.insert(0,str(runtime.resolve()))
    if importlib.metadata.version('mavsdk')!=preview['mavsdk_version']:raise ValueError('Pinned SDK version mismatch')
    from mavsdk.plugins.mission import MissionItem,MissionPlan
    items=[]
    for raw in preview['mission_items']:
        values=dict(raw);values['camera_action']=getattr(MissionItem.CameraAction,values['camera_action']);values['vehicle_action']=getattr(MissionItem.VehicleAction,values['vehicle_action']);items.append(MissionItem(**values))
    result=MissionPlan(mission_items=items);result.to_c_struct()
    return result


def run(config_path='config/drone_feasibility.json',output='reports/drone_feasibility',validate_sdk=False):
    cfg=validate(json.loads(Path(config_path).read_text()));faces=route_faces();report=simulate(faces,cfg);preview=mission_preview(report,cfg)
    report['versions']={k:cfg[k] for k in ['px4_tag','px4_tag_object_sha','mavsdk_version','mavsdk_windows_wheel_sha256']};report['sdk_data_objects_validated']=False
    if validate_sdk:
        plan=build_sdk_plan(preview);report['sdk_data_objects_validated']=True;report['sdk_mission_items']=len(plan.mission_items)
    report['sitl_execution_status']='not_run_offline_only';report['runtime_commands_found']={k:bool(shutil.which(k)) for k in ['px4','gz','docker','wsl']}
    report['sitl_blocker']='This command never opens an aircraft transport. A separately configured PX4/Gazebo SITL lab is required for physics/MAVLink execution; a WSL launcher alone does not establish a usable Linux runtime. See verification.json for the local runtime audit.'
    report['network_connections_created']=0
    out=Path(output);out.mkdir(parents=True,exist_ok=True);(out/'simulation.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8');(out/'mission_preview.json').write_text(json.dumps(preview,indent=2)+'\n',encoding='utf8')
    sensitivity=[]
    for speed in [2.,4.,6.]:
        for occlusion in [.1,.35,.6]:
            scenario=deepcopy(cfg);scenario['speed_m_s']=speed;scenario['tree_occlusion_fraction']=occlusion;r=simulate(faces,scenario)
            sensitivity.append({'data_kind':'simulation','speed_m_s_assumed':speed,'tree_occlusion_fraction_assumed':occlusion,'full_face_visibility_probability_assumed':cfg['assumed_full_face_visibility_probability'],
                'covered_faces':r['covered_faces'],'requested_faces':r['requested_faces'],'sorties':len(r['sorties']),'cycle_minutes':r['cycle_minutes_simulated'],'mean_visible_fraction':r['mean_visible_curb_fraction_simulated'],'expected_usable_count_units_per_hour':r['expected_usable_count_units_per_operator_hour_simulated']})
    for probability in [.1,.6]:
        scenario=deepcopy(cfg);scenario['assumed_full_face_visibility_probability']=probability;r=simulate(faces,scenario)
        sensitivity.append({'data_kind':'simulation','speed_m_s_assumed':cfg['speed_m_s'],'tree_occlusion_fraction_assumed':cfg['tree_occlusion_fraction'],'full_face_visibility_probability_assumed':probability,
            'covered_faces':r['covered_faces'],'requested_faces':r['requested_faces'],'sorties':len(r['sorties']),'cycle_minutes':r['cycle_minutes_simulated'],'mean_visible_fraction':r['mean_visible_curb_fraction_simulated'],'expected_usable_count_units_per_hour':r['expected_usable_count_units_per_operator_hour_simulated']})
    (out/'sensitivity.json').write_text(json.dumps(sensitivity,indent=2)+'\n',encoding='utf8')
    lines=['# Offline drone feasibility — simulated only','','All route/camera/coverage/revisit/productivity values below are **simulated assumptions, not observed flights, detections, legal approvals or forecast gains**.','',
        f"{report['covered_faces']}/{report['requested_faces']} planned development faces; {len(report['sorties'])} simulated sorties; cycle {report['cycle_minutes_simulated']:.2f} min; assumed operator time {report['operator_minutes_assumed']:.2f} min.",
        f"Raw service frames: {report['capture_frames_simulated']}; unique face-visit units: {report['unique_face_visit_units_simulated']}. Frames are not independent labels.",
        f"Expected usable count units/operator hour under the unmeasured full-visibility assumption: {report['expected_usable_count_units_per_operator_hour_simulated']:.2f}.",
        '',report['sitl_blocker'],'','MAVSDK mission data objects validated: '+str(report['sdk_data_objects_validated'])+'. No network connections, aircraft controls or real flights occurred. See docs/drone_feasibility.md for pins, assumptions, matched comparison and qualified-pilot approval questions.']
    (out/'simulation.md').write_text('\n'.join(lines)+'\n',encoding='utf8');return {k:v for k,v in report.items() if k!='sorties'}
