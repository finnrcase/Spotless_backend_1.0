"""Concrete small pilot assignments; every row remains planned, never a label."""
import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urlencode
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from .spatial import METRIC_CRS


def local_slot(day,hour,minute=0):
    # Construct wall time directly; adding elapsed hours to DST midnight is wrong.
    return pd.Timestamp(f'{day} {hour:02d}:{minute:02d}',tz='America/Los_Angeles')


def cross_streets(geometry,street,inventory):
    names=[]
    for xy in [geometry.coords[0],geometry.coords[-1]]:
        point=Point(xy);near=inventory.iloc[inventory.sindex.query(point.buffer(18),predicate='intersects')]
        values=sorted(set(near.loc[near.street_name.ne(street),'street_name']))
        names.append(' / '.join(values[:3]) or 'Intersection not resolved; verify map endpoints')
    return names


def build(output='reports',dates=('2026-10-27','2026-10-29','2026-11-01'),seed=430):
    out=Path(output);out.mkdir(exist_ok=True,parents=True)
    streets=gpd.read_parquet('data/processed/pilot_street_segments.parquet').to_crs(METRIC_CRS)
    faces=gpd.read_parquet('data/processed/pilot_block_faces.parquet').set_index('block_face_id')
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet')
    counts=mapping.loc[mapping.join_status.eq('matched')].groupby('segment_id').size()
    anchor=gpd.GeoSeries([Point(-118.4485,34.0635)],crs=4326).to_crs(METRIC_CRS).iloc[0]
    candidates=streets.loc[streets.length.between(55,190)&~streets.street_designation.str.contains('Private|Freeway|Ramp|Walkway|Paper',case=False,na=False)].copy()
    candidates['distance_to_start_m']=candidates.geometry.centroid.distance(anchor)
    candidates['linked_meters']=candidates.segment_id.map(counts).fillna(0).astype(int)
    candidates=candidates.loc[candidates.distance_to_start_m<1000].sort_values(['distance_to_start_m','segment_id'])
    selected=pd.concat([candidates.loc[candidates.linked_meters.eq(0)].head(5),candidates.loc[candidates.linked_meters.gt(0)].head(5)])
    if len(selected)!=10:raise ValueError('Need five metered-candidate and five unmetered-candidate physical blocks for this pilot')
    selected=gpd.GeoDataFrame(selected,geometry='geometry',crs=METRIC_CRS)
    rng=np.random.default_rng(seed);unmetered=selected.loc[selected.linked_meters.eq(0)]
    held=set(rng.choice(unmetered.segment_id.to_numpy(),size=3,replace=False))
    # Nearest-next order is a walking draft; street access/crossings need reconnaissance.
    ordered=[];remaining=selected.copy();point=anchor;distance=0.
    while len(remaining):
        dist=remaining.geometry.centroid.distance(point);idx=dist.idxmin();row=remaining.loc[idx]
        distance+=float(dist.loc[idx]);ordered.append(row);point=row.geometry.centroid;remaining=remaining.drop(index=idx)
    ordered=gpd.GeoDataFrame(ordered,crs=METRIC_CRS)
    route=[]
    for i,seg in enumerate(ordered.itertuples()):
        crosses=cross_streets(seg.geometry,seg.street_name,streets)
        for side in ['left','right']:
            fid=seg.segment_id+':'+side
            if fid not in faces.index:raise ValueError('Plan references missing face')
            geo=gpd.GeoSeries([faces.loc[fid].geometry],crs=4326).to_crs(4326).iloc[0]
            center=geo.representative_point()
            code=hashlib.sha256(fid.encode()).hexdigest()[:7].upper()
            route.append({'block_face_id':fid,'block_id':seg.segment_id,'code':code,'street_name':seg.street_name,'canonical_side':side,
                'cross_streets':crosses,'longitude':center.x,'latitude':center.y,
                'geometry_wkt':geo.wkt,'block_order':i+1,'length_m':float(seg.geometry.length),
                'reconnaissance_stratum':'unmetered_candidate_verify' if seg.linked_meters==0 else 'metered_or_mixed_candidate_verify',
                'evaluation_role':'unseen_block_holdout' if seg.segment_id in held else 'development',
                'eligibility':'unknown_until_whole_stay_sign_review'})
    assignments=[]
    for day in dates:
        for window,hour in [('morning',9),('afternoon',14),('evening',18)]:
            # Rotate/reverse route order without pretending visits are probability samples.
            indices=list(range(10));shift=int(rng.integers(0,10));indices=indices[shift:]+indices[:shift]
            if rng.integers(0,2):indices.reverse()
            session=f'westwood-{day}-{window}'
            visit_faces=[r for index in indices for r in route if r['block_order']==index+1]
            for i,face in enumerate(visit_faces):
                stamp=local_slot(day,hour)+pd.Timedelta(f'{i*5}min')
                assignments.append({**face,'survey_session_id':session,'assignment_id':f'{session}-{i+1:02d}',
                    'scheduled_local':stamp.isoformat(),'scheduled_utc':stamp.tz_convert('UTC').isoformat(),
                    'sampling_method':'repeat_visit','visit_status':'planned_not_observed','repeat_offset_minutes':None})
    # Two sides of a short development block are feasible within each 15-minute round.
    repeat=sorted([r for r in route if r['evaluation_role']=='development' and r['reconnaissance_stratum']=='unmetered_candidate_verify'],key=lambda r:(r['length_m'],r['block_face_id']))[0]
    repeat_faces=[r for r in route if r['block_id']==repeat['block_id']]
    for day in dates:
        session=f'westwood-{day}-changes'
        for delta in [0,15,30,60]:
            for i,face in enumerate(repeat_faces):
                stamp=local_slot(day,12)+pd.Timedelta(f'{delta+i*4}min')
                assignments.append({**face,'survey_session_id':session,'assignment_id':f'{session}-{delta:02d}-{i}',
                    'scheduled_local':stamp.isoformat(),'scheduled_utc':stamp.tz_convert('UTC').isoformat(),
                    'sampling_method':'repeat_visit','visit_status':'planned_not_observed','repeat_offset_minutes':delta})
    frame=pd.DataFrame(assignments);frame.to_csv(out/'field_assignments.csv',index=False)
    plan={'version':'westwood-field-route-v1','seed':seed,'faces':route,'assignments':assignments,'face_count':20,'physical_blocks':10,
        'regular_observations_planned':180,'change_observations_planned':24,'total_observations_planned':204,'observations_actually_collected':0,
        'dates':list(dates),'heldout_physical_block_ids':sorted(held),'approximate_centroid_route_distance_m':distance,
        'sampling':'Purposive local feasibility route with randomized order; not a representative citywide sample',
        'warnings':['Reconnaissance must verify street sides, public access, permits and actual parking population.',
            'Five-minute slots are a workload draft. Record actual times and skips; do not backfill planned times as observed.',
            'Repeat both sides at t, t+15, t+30 and t+60. If a round exceeds 15 minutes, reduce to one face and log the missed visit.',
            'Human review/label availability must precede later training origins. This pilot alone does not guarantee adequate independent train/validation/calibration/test evidence.']}
    (out/'field_route.json').write_text(json.dumps(plan,indent=2),encoding='utf8')
    template=Path('web/field_route.html').read_text(encoding='utf8')
    (out/'field_route.html').write_text(template.replace('/*__DATA__*/',json.dumps(plan,separators=(',',':')).replace('<','\\u003c')),encoding='utf8')
    lines=['# Westwood field collection route','', 'Start with the first four faces, export them, and review counting/location quality before committing to the full route. No manual IDs or coordinate transcription is needed. Open field_route.html and tap a visit to open the collector with its face, session and assignment filled.','',
        'This supplements the starter FIELD_COLLECTION.md: 20 faces × morning/afternoon/evening × Tuesday October 27, Thursday October 29 and Sunday November 1, 2026 = 180 planned snapshots. Two sides of one short development block add 24 observations at 12:00/12:15/12:30/13:00 (second side four minutes later) across the three days. Actual observation times govern any later 15/30/60-minute analysis.','',
        'Morning starts 09:00, afternoon 14:00, evening 18:00; each route reserves up to 100 minutes. Times are Los Angeles wall times and include the November 1 DST change correctly. Shift dates deliberately if unavailable and preserve the revised plan before collection.','',
        '| Order | Street | Between (verify) | Faces | Reconnaissance stratum | Evaluation role |','|---:|---|---|---|---|---|']
    for r in route[::2]:lines.append(f"| {r['block_order']} | {r['street_name']} | {' ↔ '.join(r['cross_streets'])} | Both sides | {r['reconnaissance_stratum']} | {r['evaluation_role']} |")
    lines+=['','Hold out the three listed complete physical blocks, including both sides, before model selection. This is a purposive workload/label-quality pilot, not citywide random sampling. Keep skipped assignments/reasons and do not replace difficult outcomes with convenient observations. Use the earlier randomized expansion design after reconnaissance and workload measurement.','', 'Unmarked gaps retain raw lengths and a counting convention. Trees, blocked sight lines and unknown rules remain missing. A parked car is not proof of legal capacity. No images or current source proxies become independent manual labels.']
    (out/'field_route.md').write_text('\n'.join(lines)+'\n',encoding='utf8');return plan
