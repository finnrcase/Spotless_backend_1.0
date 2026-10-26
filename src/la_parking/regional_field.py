"""Small regional unmetered-candidate walks, selected without occupancy values."""
import hashlib
import json
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from .census_coverage import ROOT
from .spatial import METRIC_CRS
from .field_route import cross_streets,local_slot


def prepare(output='reports'):
    if not (ROOT/'selected_streets.parquet').exists():return {}
    out=Path(output);cfg=json.loads(Path('config/coverage_v4.json').read_text())
    streets=gpd.read_parquet('data/processed/street_segments.parquet').to_crs(METRIC_CRS)
    meters=gpd.read_parquet('data/processed/meters.parquet').to_crs(METRIC_CRS)
    face_inventory=gpd.read_parquet('data/processed/block_faces.parquet')
    routes=[];assignments=[];chosen=[];reserved=[]
    for i,(region,bounds) in enumerate(cfg['neighborhoods'].items()):
        area=gpd.GeoSeries([box(*bounds)],crs=4326).to_crs(METRIC_CRS).iloc[0]
        candidates=streets.loc[streets.intersects(area)&streets.length.between(55,190)&~streets.street_designation.str.contains('Private|Freeway|Ramp|Walkway|Paper',case=False,na=False)].copy()
        nearby=meters.loc[meters.intersects(area.buffer(100))]
        candidates['nearby_inventory_meters']=[len(nearby.sindex.query(g.buffer(30),predicate='intersects')) for g in candidates.geometry]
        candidates=candidates.loc[candidates.nearby_inventory_meters.eq(0)]
        anchor=area.centroid;candidates['distance']=candidates.geometry.centroid.distance(anchor)
        selected=candidates.sort_values(['distance','segment_id']).head(2)
        if len(selected)!=2:raise ValueError('Need two short unmetered-candidate blocks per region')
        for j,seg in enumerate(selected.itertuples()):
            chosen.append(seg.segment_id);role='development' if j==0 else 'unseen_block_holdout'
            if j:reserved.append(seg.segment_id)
            faces=face_inventory.loc[face_inventory.segment_id.eq(seg.segment_id)].to_crs(4326)
            for face in faces.itertuples():
                point=face.geometry.representative_point()
                routes.append({'block_id':seg.segment_id,'block_face_id':face.block_face_id,'region':region,'street_name':seg.street_name,'canonical_side':face.side,
                    'code':hashlib.sha256(face.block_face_id.encode()).hexdigest()[:7].upper(),'cross_streets':cross_streets(seg.geometry,seg.street_name,streets),
                    'latitude':point.y,'longitude':point.x,'block_order':j+1,'length_m':seg.geometry.length,
                    'reconnaissance_stratum':'unmetered_candidate_verify','evaluation_role':role,'eligibility':'unknown_until_whole_stay_sign_review'})
            day=f'2026-11-{(2+i if j==0 else 18+i):02d}';session=f'{region.lower()}-v4-{day}'
            for delta in [0,15,30,60]:
                for side,face in enumerate(r for r in routes if r['block_id']==seg.segment_id):
                    stamp=local_slot(day,12)+pd.Timedelta(minutes=delta+side*4)
                    assignments.append({**face,'survey_session_id':session,'assignment_id':f'{session}-{delta:02d}-{side}',
                        'scheduled_local':stamp.isoformat(),'scheduled_utc':stamp.tz_convert('UTC').isoformat(),'sampling_method':'repeat_visit','repeat_offset_minutes':delta,'visit_status':'planned_not_observed'})
    reserved_rows=[a for a in assignments if a['evaluation_role']=='unseen_block_holdout']
    reservation={'version':'coverage-v4-field','unseen_physical_blocks':sorted(reserved),'reserved_session_ids':sorted({a['survey_session_id'] for a in reserved_rows}),
        'reserved_assignment_ids':[a['assignment_id'] for a in reserved_rows],'counts_collected':0,'block_selection':'Short City streets with no inventory meter point within 30m, nearest regional bbox center; absence is a reconnaissance candidate, not verified unmetered status.'}
    target=Path('config/coverage_v4_field_holdouts.json') if out.resolve()==Path('reports').resolve() else out/'coverage_v4_field_holdouts.json'
    if target.exists() and json.loads(target.read_text())!=reservation:raise ValueError('Regional field holdouts changed; register a new plan')
    target.write_text(json.dumps(reservation,indent=2)+'\n',encoding='utf8')
    selected_streets=gpd.read_parquet(ROOT/'selected_streets.parquet')
    gpd.GeoDataFrame(pd.concat([selected_streets,streets.loc[streets.segment_id.isin(chosen)].to_crs(4326)],ignore_index=True),crs=4326).drop_duplicates('segment_id').to_parquet(ROOT/'collector_streets.parquet',index=False)
    selected_faces=gpd.read_parquet(ROOT/'selected_faces.parquet')
    gpd.GeoDataFrame(pd.concat([selected_faces,face_inventory.loc[face_inventory.segment_id.isin(chosen)]],ignore_index=True),crs=face_inventory.crs).drop_duplicates('block_face_id').to_parquet(ROOT/'collector_faces.parquet',index=False)
    pd.DataFrame(assignments).to_csv(out/'regional_field_assignments.csv',index=False)
    result={'regional_faces':routes,'regional_assignments':assignments,'regional_collection_note':'32 optional snapshots: Downtown Nov2 and Hollywood Nov3 development (8 each); Nov18/19 different whole blocks reserved (8 each). Both sides at 0/15/30/60, second side four minutes later. Verify unmetered status, signs, access and capacity; missing visits stay missing. No labels collected.'}
    (out/'regional_field_route.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    return result
