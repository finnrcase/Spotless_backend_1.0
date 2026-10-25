"""Build versioned geography, pilot observations and inspection artifacts."""
import hashlib
import json
from pathlib import Path
import duckdb
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from .http import utcnow
from .sources import PILOT
from .spatial import read_features, inventory, faces, meter_points, assign_meters
from .temporal import parse_time, intervals


def normalize_events(frame, source_id, retrieved_at):
    mapping={'SpaceID':'space_id','EventTime_UTC':'observed_at_utc','OccupancyState':'state',
             'spaceid':'space_id','eventtime':'observed_at_utc','occupancystate':'state'}
    frame=frame.rename(columns=mapping).copy()
    frame['observed_at_utc']=parse_time(frame.observed_at_utc,'UTC')
    frame['state']=frame.state.str.upper().str.strip()
    invalid=frame.observed_at_utc.isna()|~frame.state.isin(['OCCUPIED','VACANT','UNKNOWN'])|frame.space_id.isna()|(frame.observed_at_utc>pd.Timestamp(retrieved_at))
    rejects=frame.loc[invalid].copy()
    clean=frame.loc[~invalid,['space_id','observed_at_utc','state']].copy()
    clean['source_id']=source_id; clean['retrieved_at_utc']=pd.Timestamp(retrieved_at)
    clean['field_provenance']='observed'
    clean['observation_id']=clean.apply(lambda r:hashlib.sha256(f'{source_id}|{r.space_id}|{r.observed_at_utc}|{r.state}'.encode()).hexdigest(),axis=1)
    duplicates=int(clean.observation_id.duplicated().sum())
    return clean.drop_duplicates('observation_id'),rejects,duplicates


def run():
    stage=Path('data/staged'); out=Path('data/processed'); out.mkdir(parents=True,exist_ok=True)
    reports=Path('reports'); reports.mkdir(exist_ok=True)
    now=utcnow(); report={'generated_at_utc':now,'pilot_bbox':PILOT,'unmetered_verified_occupancy_labels':0,'warnings':[]}
    boundary=read_features(stage/'boundary.geojson')
    boundary.to_parquet(out/'city_boundary.parquet',index=False)
    streets=read_features(stage/'streets.geojson')
    print('Building city inventory from',len(streets),'source streets',flush=True)
    segments=inventory(streets,boundary)
    manifests=[json.loads(line) for line in Path('data/manifest.jsonl').read_text(encoding='utf8').splitlines()]
    street_retrieved=max(r['retrieved_at_utc'] for r in manifests if '/MapServer/341/query' in r.get('url','') and r.get('success'))
    segments['retrieved_at_utc']=pd.Timestamp(street_retrieved)
    segments['processed_at_utc']=pd.Timestamp(now)
    segments['field_provenance']='derived'
    segments.to_parquet(out/'street_segments.parquet',index=False)
    print('City segments saved:',len(segments),flush=True)
    segments.drop(columns='geometry').to_parquet(out/'segment_version_mapping.parquet',index=False)
    curbs=read_features(stage/'curbs.geojson') if (stage/'curbs.geojson').exists() else None
    block_faces=faces(segments,curbs)
    print('Block faces built:',len(block_faces),flush=True)
    block_faces.to_parquet(out/'block_faces.parquet',index=False)
    pilot_shape=box(*PILOT)
    pilot_segments=segments[segments.intersects(pilot_shape)].copy()
    pilot_segments.to_parquet(out/'pilot_street_segments.parquet',index=False)
    pilot_faces=block_faces[block_faces.segment_id.isin(pilot_segments.segment_id)].copy()
    pilot_faces.to_parquet(out/'pilot_block_faces.parquet',index=False)
    # Unknown eligible/physical counts deliberately remain null, including excluded roads.
    capacity=block_faces[['block_face_id','applicability']].copy()
    for field in ['physical_capacity','eligible_capacity','capacity_lower','capacity_upper']:
        capacity[field]=pd.Series([pd.NA]*len(capacity),dtype='Int64')
    capacity['capacity_method']='unavailable'; capacity['exclusions_complete']=False
    capacity['valid_from_utc']=pd.Timestamp(now); capacity['valid_to_utc']=pd.NaT
    capacity['confidence']=0.; capacity['field_provenance']='unavailable'
    capacity.to_parquet(out/'curb_inventory.parquet',index=False)

    meters_raw=pd.read_parquet(stage/'meters.parquet')
    meters,rejected=meter_points(meters_raw,boundary)
    # Nested source location dictionaries need JSON for portable parquet.
    for col in meters.columns:
        if meters[col].map(lambda v:isinstance(v,(dict,list))).any(): meters[col]=meters[col].map(lambda v:json.dumps(v) if isinstance(v,(dict,list)) else v)
    meters.to_parquet(out/'meters.parquet',index=False)
    rejected.astype(str).to_parquet(out/'meter_quarantine.parquet',index=False)
    pilot_meters=meters[meters.intersects(pilot_shape)].copy()
    joins=assign_meters(pilot_meters,pilot_segments)
    print('Pilot meter joins:',joins.join_status.value_counts().to_dict(),flush=True)
    joins.to_parquet(out/'meter_face_mapping.parquet',index=False)
    pilot_meters.to_parquet(out/'pilot_meters.parquet',index=False)
    ids=set(pilot_meters.spaceid)
    raw_current=pd.read_parquet(stage/'occupancy.parquet')
    # Retrieval timestamp belongs to the raw snapshot, not rebuild time.
    current_retrieved=max(r['retrieved_at_utc'] for r in manifests if '/resource/e7h6-4a3e.json' in r.get('url','') and '$offset' in (r.get('params') or {}) and r.get('success'))
    current,rejects,dupes=normalize_events(raw_current,'ladot_current',current_retrieved)
    current['age_seconds']=(pd.Timestamp(current_retrieved)-current.observed_at_utc).dt.total_seconds()
    current['stale']=current.age_seconds>900
    current.to_parquet(out/'city_current_occupancy.parquet',index=False)
    current[current.space_id.isin(ids)].to_parquet(out/'pilot_current_occupancy.parquet',index=False)
    report['current_occupancy']={'rows':len(current),'invalid_rows':len(rejects),'duplicates':dupes,'oldest_utc':str(current.observed_at_utc.min()),'newest_utc':str(current.observed_at_utc.max()),'stale_over_15_min':int(current.stale.sum()),'pilot_rows':int(current.space_id.isin(ids).sum()),'inventory_id_match_fraction':float(current.space_id.isin(set(meters.spaceid)).mean())}

    history=[]; history_quality=[]
    for ptr in sorted(stage.glob('history_20*.json')):
        info=json.loads(ptr.read_text()); frames=[]; total=0; invalid=0; duplicate=0
        print('Filtering historical month',info['month'],flush=True)
        for chunk in pd.read_csv(info['path'],chunksize=150000,dtype={'SpaceID':str}):
            total+=len(chunk)
            pilot=chunk[chunk.SpaceID.isin(ids)]
            if not len(pilot): continue
            clean,bad,d=normalize_events(pilot,'ladot_archive_'+info['month'],info['record']['retrieved_at_utc'])
            invalid+=len(bad); duplicate+=d; frames.append(clean)
        frame=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
        if len(frame):
            duplicate+=int(frame.observation_id.duplicated().sum()); frame=frame.drop_duplicates('observation_id')
            frame.to_parquet(out/f'pilot_history_{info["month"]}.parquet',index=False); history.append(frame)
        history_quality.append({'month':info['month'],'raw_city_rows':total,'pilot_rows':len(frame),'pilot_spaces':int(frame.space_id.nunique()) if len(frame) else 0,'invalid_pilot_rows':invalid,'duplicate_pilot_rows':duplicate,'min_utc':str(frame.observed_at_utc.min()) if len(frame) else None,'max_utc':str(frame.observed_at_utc.max()) if len(frame) else None})
    report['history']=history_quality
    if history:
        events=pd.concat(history,ignore_index=True)
        # Partition months to avoid creating intervals across unsampled months.
        coverage=[]
        for label,frame in events.groupby('source_id'):
            year,month=map(int,label.removeprefix('ladot_archive_').split('_'))
            start=pd.Timestamp(year=year,month=month,day=1,tz='America/Los_Angeles')
            end=(start+pd.DateOffset(months=1)).tz_convert('UTC')
            for horizon in [5,15,60]:
                iv=intervals(frame,horizon,window_end=end)
                iv['policy_horizon_minutes']=horizon
                if horizon==15: iv.to_parquet(out/f'intervals_{label}.parquet',index=False)
                expected=float((end-start.tz_convert('UTC')).total_seconds()*iv.space_id.nunique()/3600)
                known=float(iv.loc[iv.known,'seconds'].sum()/3600)
                coverage.append({'source_id':label,'horizon_minutes':horizon,'known_hours':known,'expected_space_hours':expected,'known_fraction':known/expected,'unknown_state_rows':int((iv.state=='UNKNOWN').sum()),'spaces':int(iv.space_id.nunique())})
        pd.DataFrame(coverage).to_parquet(out/'coverage_sensitivity.parquet',index=False)
        report['coverage_sensitivity']=coverage

    report['geography']={'source_streets':len(streets),'city_segments':len(segments),'block_faces':len(block_faces),'pilot_segments':len(pilot_segments),'pilot_faces':len(pilot_faces),'authoritative_curb_faces':int((pilot_faces.geometry_method=='authoritative_curb').sum()),'invalid_segments':int((~segments.is_valid).sum()),'invalid_faces':int((~block_faces.is_valid).sum()),'excluded_segments':int((segments.applicability=='excluded').sum())}
    report['meters']={'raw_rows':len(meters_raw),'city_valid_unique_rows':len(meters),'quarantine_rows':len(rejected),'pilot_rows':len(pilot_meters),'pilot_join_status':joins.join_status.value_counts().to_dict(),'missingness':pilot_meters.drop(columns='geometry').isna().mean().to_dict()}
    layer_counts={}
    for name in ['curbs','driveways','hydrants','regulatory_signs','bikeways','red_curb','buildings','zoning','construction','construction_streets']:
        path=stage/f'{name}.geojson'
        if not path.exists(): continue
        gdf=read_features(path); layer_counts[name]={'features':len(gdf),'invalid':int((~gdf.is_valid).sum()),'empty':int(gdf.is_empty.sum())}
        gdf.to_parquet(out/f'pilot_{name}.parquet',index=False)
    report['context_layers']=layer_counts
    report['warnings']=['No verified unmetered occupancy labels.', 'Current inventory is not historical supply; historical ID matches do not prove unchanged location.', '15-minute persistence is an unvalidated sensitivity policy, not continuous sensor coverage.', 'Block-face offsets are approximate except footprints passing documented curb coverage threshold.', 'Legal eligible capacity is unavailable until exclusions, permits and full-duration restrictions are verified.', 'Live SODA feeds have no transaction isolation; ordered pages and count checks do not detect all concurrent replacements.']
    Path('reports/coverage.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf8')
    from .features import build_context
    report['features']=build_context()
    Path('reports/coverage.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf8')
    # DuckDB queryable attributes; spatial geometry remains standard GeoParquet.
    with duckdb.connect(str(out/'parking.duckdb')) as con:
        for file in out.glob('*.parquet'):
            quoted=str(file.resolve()).replace("'","''")
            con.execute(f'CREATE OR REPLACE VIEW "{file.stem}" AS SELECT * FROM read_parquet(\'{quoted}\')')
    create_map(pilot_segments,pilot_meters,curbs,current)
    Path('reports/coverage.md').write_text('# Acquired coverage\n\n'+json.dumps(report,indent=2,default=str)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2,default=str),flush=True)
    return report


def create_map(segments,meters,curbs,current=None):
    import folium
    m=folium.Map(location=[34.065,-118.445],zoom_start=14,tiles=None)
    # No external basemap needed; local layer controls and geometries make coverage explicit.
    folium.GeoJson(json.loads(segments[['segment_id','street_name','geometry']].to_json()),name='Pilot streets: legal capacity unknown',tooltip=folium.GeoJsonTooltip(fields=['street_name','segment_id'])).add_to(m)
    if curbs is not None and len(curbs): folium.GeoJson(json.loads(curbs[['OBJECTID','geometry']].to_json()),name='Authoritative physical curb footprints',style_function=lambda _: {'color':'orange','weight':2}).add_to(m)
    group=folium.FeatureGroup(name='Meter inventory, not occupancy')
    for _,r in meters.iterrows(): folium.CircleMarker([r.geometry.y,r.geometry.x],radius=2,color='green',popup=str(r.spaceid)).add_to(group)
    group.add_to(m); folium.LayerControl().add_to(m)
    if current is not None:
        sensors=meters.merge(current[['space_id','state','stale','age_seconds']],left_on='spaceid',right_on='space_id',how='inner',validate='one_to_one')
        sensor_group=folium.FeatureGroup(name='Last-known sensors: blue fresh / red stale (>15 min)')
        for _,r in sensors.iterrows():
            folium.CircleMarker([r.geometry.y,r.geometry.x],radius=5,color='red' if r.stale else 'blue',popup=f'{r.spaceid}: {r.state}; age {r.age_seconds/60:.0f} minutes at retrieval').add_to(sensor_group)
        sensor_group.add_to(m)
        # Replace the initial control after all evidence layers have been added.
        for key in list(m._children):
            if key.startswith('layer_control'): del m._children[key]
        folium.LayerControl().add_to(m)
    m.get_root().html.add_child(folium.Element('<div style="position:fixed;top:10px;left:60px;z-index:9999;background:white;padding:8px">Westwood/UCLA pilot • Lines = streets; green = meters; orange = physical curbs. Unmetered occupancy unavailable.</div>'))
    m.save('reports/coverage_map.html')


def write_coverage_markdown(report):
    geo=report['geography']; meter=report['meters']; live=report['current_occupancy']
    lines=['# Measured data coverage','',f"Generated: {report['generated_at_utc']}. Storage times are UTC; local schedules use America/Los_Angeles.",'',
           f"City inventory: **{geo['city_segments']:,} segments / {geo['block_faces']:,} faces** after jurisdiction clipping and source-join duplicate handling.",
           f"Westwood/UCLA pilot: **{geo['pilot_segments']:,} segments / {geo['pilot_faces']:,} faces / {meter['pilot_rows']:,} meters**. {geo['authoritative_curb_faces']} faces use associated authoritative physical curb footprints; the remainder use approximate offsets.",'',
           f"Pilot meter joins: {meter['pilot_join_status']}. No ambiguous assignment becomes a training label.",
           f"Current feed: {live['rows']:,} city sensor states, {live['pilot_rows']} pilot states. {live['stale_over_15_min']:,} city states exceed the unvalidated 15-minute freshness policy. Latest transaction: {live['newest_utc']}.",'',
           '**Verified unmetered occupancy labels: 0. Physical and eligible capacity remain unknown.**','',
           '| Archive month | Raw city events | Pilot events | Pilot sensor IDs | Actual pilot UTC span |','|---|---:|---:|---:|---|']
    for h in report['history']: lines.append(f"| {h['month']} | {h['raw_city_rows']:,} | {h['pilot_rows']:,} | {h['pilot_spaces']} | {h['min_utc']} to {h['max_utc']} |")
    lines+=['','| Source | Persistence cap (min) | Known fraction of expected sensor-time |','|---|---:|---:|']
    for c in report.get('coverage_sensitivity',[]): lines.append(f"| {c['source_id']} | {c['horizon_minutes']} | {c.get('known_fraction',0):.1%} |")
    lines+=['','This fraction measures inferred state persistence under a policy, not verified continuous ground truth. Missing hours are not vacant hours.','', '| Pilot layer | Features | Invalid |','|---|---:|---:|']
    for k,v in report['context_layers'].items(): lines.append(f"| {k} | {v['features']:,} | {v['invalid']} |")
    lines+=['','[Interactive coverage map](coverage_map.html). Full missingness, age, joins and sensitivity: `coverage.json`. Source status/terms: `../config/source_registry.json`.','']
    lines.extend('- '+s for s in report['warnings'])
    Path('reports/coverage.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
