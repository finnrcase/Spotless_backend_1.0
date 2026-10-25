"""Jurisdiction clipping, canonical sides and ambiguity-preserving meter joins."""
import hashlib
import json
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from shapely.prepared import prep

METRIC_CRS='EPSG:26911'  # NAD83 / UTM 11N; metres, suitable for LA distances.


def canonical_line(line):
    coords=list(line.coords)
    return LineString(coords if tuple(coords[0])<=tuple(coords[-1]) else coords[::-1])


def clean_geometry(obj):
    """ArcGIS can emit [x,y,z,null M]; preserve source raw, use XY for analysis."""
    def xy(coords):
        if isinstance(coords[0], (int,float)): return coords[:2]
        return [xy(c) for c in coords]
    obj=json.loads(json.dumps(obj))
    for f in obj['features']:
        if f.get('geometry'): f['geometry']['coordinates']=xy(f['geometry']['coordinates'])
    return obj


def read_features(path):
    obj=clean_geometry(json.loads(path.read_text(encoding='utf8')))
    if not obj['features']: return gpd.GeoDataFrame(geometry=[],crs=4326)
    return gpd.GeoDataFrame.from_features(obj,crs=4326)


def inventory(streets, boundary):
    if streets.crs is None or boundary.crs is None: raise ValueError('Explicit CRS required')
    if not streets.geometry.is_valid.all() or not boundary.geometry.is_valid.all(): raise ValueError('Invalid source geometry; inspect instead of silently repair')
    bound=boundary.to_crs(streets.crs).geometry.union_all()
    prepared=prep(bound)
    streets=streets.copy()
    streets['_physical_hash']=streets.geometry.map(lambda g:hashlib.sha256(g.normalize().wkb).hexdigest())
    keys=['ASSETID','OBJECTID','_physical_hash'] if 'ASSETID' in streets.columns else ['OBJECTID','_physical_hash']
    idcol='AutoID' if 'AutoID' in streets.columns else 'OBJECTID'
    grouped=streets.groupby(keys,dropna=False)
    lineage=grouped[idcol].agg(lambda s:json.dumps(sorted(str(v) for v in s))).rename('_source_row_ids')
    designations=grouped['Street_Designation'].agg(lambda s:json.dumps(sorted(set(str(v) for v in s)))).rename('_source_designations') if 'Street_Designation' in streets.columns else None
    streets=streets.drop_duplicates(keys).merge(lineage,on=keys,validate='one_to_one')
    if designations is not None: streets=streets.merge(designations,on=keys,validate='one_to_one')
    variants=streets.groupby(['ASSETID','OBJECTID'],dropna=False)['_physical_hash'].transform('nunique') if 'ASSETID' in streets.columns else streets.groupby('OBJECTID')['_physical_hash'].transform('nunique')
    streets['_multiple_geometry']=variants>1
    rows=[]
    for _,row in streets.iterrows():
        # Most streets lie entirely inside. Prepared predicates avoid repeated
        # expensive intersections with the detailed 10k+ vertex city outline.
        if prepared.covers(row.geometry): geom=row.geometry
        elif prepared.intersects(row.geometry): geom=row.geometry.intersection(bound)
        else: continue
        if geom.is_empty: continue
        parts=[geom] if geom.geom_type=='LineString' else [g for g in getattr(geom,'geoms',[]) if g.geom_type=='LineString']
        parts=sorted([canonical_line(g) for g in parts if g.length>0],key=lambda g:tuple(g.coords[0]))
        for i,line in enumerate(parts):
            oid=str(row['OBJECTID']); asset=str(row.get('ASSETID',oid))
            # IDs stable under source ordering changes; geometry hash detects version changes.
            sid=f'la:boe:asset:{asset}:oid:{oid}:part:{i}'
            if row['_multiple_geometry']: sid+=':variant:'+row['_physical_hash'][:12]
            label=str(row.get('_source_designations',row.get('Street_Designation',''))).lower()
            excluded=any(s in label for s in ['freeway','ramp','walkway','paper street'])
            rows.append({'segment_id':sid,'source_record_id':oid,'source_asset_id':asset,
                         'source_api_row_ids':row['_source_row_ids'],
                         'source_designations':row.get('_source_designations','[]'),
                         'source_version':hashlib.sha256(line.wkb).hexdigest(),
                         'street_name':' '.join(str(row.get(k,'') or '').strip() for k in ['TDIR','STNAME','STSFX']).strip(),
                         'street_designation':str(row.get('Street_Designation','')),
                         'applicability':'excluded' if excluded else 'needs_review',
                         'exclusion_reason':'source road designation' if excluded else None,
                         'jurisdiction':'City of Los Angeles','geometry':line})
    result=gpd.GeoDataFrame(rows,crs=streets.crs)
    if result.segment_id.duplicated().any(): raise ValueError('Duplicate segment ID')
    return result.to_crs(4326)


def faces(segments, curbs=None, offset_m=8):
    projected=segments.to_crs(METRIC_CRS)
    curb_projected=curbs.to_crs(METRIC_CRS) if curbs is not None and len(curbs) else None
    if curb_projected is not None:
        curb_projected=curb_projected.loc[curb_projected.geometry.notna()&curb_projected.is_valid&~curb_projected.is_empty].copy()
    rows=[]
    for seg in projected.itertuples(index=False):
        line=seg.geometry
        for side,dist in [('left',offset_m),('right',-offset_m)]:
            approximate=line.offset_curve(dist)
            if approximate.is_empty: approximate=line
            method='approximate_centerline_offset'; confidence=.2; geom=approximate; ids=[]
            coverage=0.
            if curb_projected is not None:
                ix=curb_projected.sindex.query(approximate.buffer(5),predicate='intersects')
                candidates=curb_projected.iloc[ix]
                # Keep the physical curb footprints, never interpret them as legal spaces.
                candidates=candidates[candidates.geometry.distance(approximate)<5]
                if len(candidates):
                    union=candidates.geometry.union_all()
                    coverage=approximate.intersection(union.buffer(1)).length/max(approximate.length,1)
                    ids=candidates.OBJECTID.astype(str).tolist()
                    if coverage>=.8:
                        geom=union; method='authoritative_curb'; confidence=.6
            rows.append({'block_face_id':seg.segment_id+':'+side,'segment_id':seg.segment_id,'side':side,
                         'orientation':'canonical_endpoint_order','geometry_method':method,
                         'curb_source_ids':json.dumps(ids),'curb_coverage_fraction':coverage,
                         'confidence':confidence,'geometry':geom,'applicability':seg.applicability})
    return gpd.GeoDataFrame(rows,crs=METRIC_CRS).to_crs(4326)


def meter_points(frame,boundary):
    frame=frame.copy()
    frame['latitude']=frame.latlng.map(lambda d:float(d['latitude']) if isinstance(d,dict) and d.get('latitude') else float('nan'))
    frame['longitude']=frame.latlng.map(lambda d:float(d['longitude']) if isinstance(d,dict) and d.get('longitude') else float('nan'))
    valid=frame.latitude.between(33,35)&frame.longitude.between(-119,-117)
    rejected=frame.loc[~valid].copy()
    good=frame.loc[valid].copy()
    # Drop only truly identical exported rows; quarantine conflicting SpaceIDs.
    good['_row_hash']=good.apply(lambda r:hashlib.sha256(json.dumps(r.to_dict(),sort_keys=True,default=str).encode()).hexdigest(),axis=1)
    good=good.drop_duplicates('_row_hash')
    conflict=good.spaceid.duplicated(keep=False)
    rejected=pd.concat([rejected,good.loc[conflict]],ignore_index=True)
    good=good.loc[~conflict].drop(columns=['_row_hash'])
    points=gpd.GeoDataFrame(good,geometry=gpd.points_from_xy(good.longitude,good.latitude),crs=4326)
    bound=boundary.to_crs(4326).geometry.union_all()
    points['within_city']=points.geometry.covered_by(bound)
    rejected=pd.concat([rejected,pd.DataFrame(points.loc[~points.within_city].drop(columns='geometry'))],ignore_index=True)
    return points.loc[points.within_city].copy(),rejected


def assign_meters(points,segments,max_distance_m=35,ambiguity_m=3):
    pts=points.to_crs(METRIC_CRS)
    segs=segments.to_crs(METRIC_CRS)
    records=[]
    for _,pt in pts.iterrows():
        ix=segs.sindex.query(pt.geometry.buffer(max_distance_m),predicate='intersects')
        candidates=segs.iloc[ix]
        d=candidates.geometry.distance(pt.geometry).sort_values()
        status='unmatched'; sid=None; side=None; distance=None
        if len(d):
            distance=float(d.iloc[0])
            if len(d)>1 and d.iloc[1]-d.iloc[0]<=ambiguity_m: status='ambiguous'
            else:
                row=segs.loc[d.index[0]]; line=row.geometry
                pos=line.project(pt.geometry); a=line.interpolate(max(0,pos-.5)); b=line.interpolate(min(line.length,pos+.5))
                cross=(b.x-a.x)*(pt.geometry.y-a.y)-(b.y-a.y)*(pt.geometry.x-a.x)
                if abs(cross)<.1: status='ambiguous'
                else: status='matched'; sid=row.segment_id; side='left' if cross>0 else 'right'
        records.append({'space_id':pt.spaceid,'join_status':status,'distance_m':distance,'segment_id':sid,
                        'block_face_id':sid+':'+side if sid else None})
    return pd.DataFrame(records)
