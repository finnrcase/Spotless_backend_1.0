"""Build a self-contained phone collector from the real pilot inventory."""
import hashlib
import json
from pathlib import Path
import geopandas as gpd
import pandas as pd


def build_collector(output='reports/collector.html', root=None):
    root=Path(root or Path.cwd()); data=root/'data/processed'; template=root/'web/collector'
    faces=gpd.read_parquet(data/'pilot_block_faces.parquet').to_crs(4326)
    segments=gpd.read_parquet(data/'pilot_street_segments.parquet').to_crs(4326).set_index('segment_id')
    mapping=pd.read_parquet(data/'meter_face_mapping.parquet')
    expanded=root/'data/modeling/coverage_v4'
    if (expanded/'collector_faces.parquet').exists():
        faces=gpd.GeoDataFrame(pd.concat([faces,gpd.read_parquet(expanded/'collector_faces.parquet').to_crs(4326)],ignore_index=True),crs=4326).drop_duplicates('block_face_id')
        extra=gpd.read_parquet(expanded/'collector_streets.parquet').to_crs(4326).set_index('segment_id')
        segments=pd.concat([segments,extra]);segments=segments.loc[~segments.index.duplicated()]
        mapping=pd.concat([mapping,pd.read_parquet(expanded/'meter_mapping.parquet')],ignore_index=True).drop_duplicates('space_id')
    meters=mapping.loc[mapping.join_status=='matched'].groupby('block_face_id').size().to_dict()
    bay_points=pd.read_parquet(data/'meters.parquet',columns=['spaceid','latitude','longitude'])
    bay_rows=mapping.loc[mapping.join_status.eq('matched')].merge(bay_points,left_on='space_id',right_on='spaceid',validate='one_to_one')
    bays={face:g[['space_id','latitude','longitude']].sort_values('space_id').to_dict('records') for face,g in bay_rows.groupby('block_face_id')}
    support=json.loads((root/'reports/final_validation.json').read_text())
    source_coverage=json.loads((root/'reports/coverage.json').read_text())
    def paths(geom):
        if geom.geom_type=='Polygon': return [[list(p[:2]) for p in geom.exterior.coords]]
        if geom.geom_type in ['LineString','LinearRing']: return [[list(p[:2]) for p in geom.coords]]
        return [p for g in geom.geoms for p in paths(g)]
    records=[]; streets=[]
    for sid,seg in segments.iterrows():
        coords=paths(seg.geometry.simplify(.00001))[0]; center=seg.geometry.interpolate(.5,normalized=True)
        streets.append({'center':[round(center.x,7),round(center.y,7)],'path':coords})
    for face in faces.itertuples(index=False):
        seg=segments.loc[face.segment_id]; line=seg.geometry; coords=paths(line.simplify(.00001))[0]
        point=face.geometry.interpolate(.5,normalized=True) if face.geometry.geom_type=='LineString' else face.geometry.representative_point()
        dx=coords[-1][0]-coords[0][0]; dy=coords[-1][1]-coords[0][1]
        nx,ny=(-dy,dx) if face.side=='left' else (dy,-dx)
        direction=('north' if ny>=0 else 'south') if abs(ny)>=abs(nx) else ('east' if nx>=0 else 'west')
        records.append({'id':face.block_face_id,'street':seg.street_name,'code':hashlib.sha256(face.block_face_id.encode()).hexdigest()[:7].upper(),
                        'side_label':direction+' side (verify)','canonical_side':face.side,'method':face.geometry_method,
                        'meter_links':int(meters.get(face.block_face_id,0)),'meter_bays':bays.get(face.block_face_id,[]),'street_designation':seg.street_designation,'center':[round(point.x,7),round(point.y,7)],
                        'span':max(line.bounds[2]-line.bounds[0],line.bounds[3]-line.bounds[1],.0015),
                        'paths':paths(face.geometry.simplify(.000005)),'centerline':coords,
                        'endpoints':f'{coords[0][1]:.5f}, {coords[0][0]:.5f} → {coords[-1][1]:.5f}, {coords[-1][0]:.5f}'})
    payload={'jurisdiction':'City of Los Angeles','faces':sorted(records,key=lambda f:(f['street'],f['code'])),'streets':streets,'support':{'fresh_faces':support['faces_with_fresh_partial_metered_evidence'],'snapshot_utc':source_coverage['generated_at_utc'],'inventory_note':'Snapshot support covers original Westwood faces only; additional regional faces have no current availability claim. Unvalidated geography and accuracy.','curb_asset_vintage':'2017 inventory based on 2014 imagery; current maintenance not verified'}}
    html=(template/'index.html').read_text(encoding='utf8')
    substitutions={'/*__CSS__*/':(template/'styles.css').read_text(encoding='utf8'),
                   '/*__DATA__*/':json.dumps(payload,separators=(',',':')).replace('<','\\u003c'),
                   '/*__MODEL__*/':(template/'model.mjs').read_text(encoding='utf8').replace('export ','').replace('</script','<\\/script'),
                   '/*__APP__*/':(template/'app.js').read_text(encoding='utf8')}
    for key,value in substitutions.items(): html=html.replace(key,value)
    target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(html,encoding='utf8')
    manifest={'faces':len(records),'html_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size,'source':'local Westwood and optional bounded regional inventory; approximate faces, restrictions unknown','self_contained':True,'published':False}
    (target.parent/'collector_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    return manifest
