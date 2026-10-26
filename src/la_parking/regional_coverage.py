"""Bounded expansion from cached historical labels, never reserved current states."""
import hashlib,json
from pathlib import Path
import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box
from sklearn.neighbors import BallTree
from .spatial import assign_meters,METRIC_CRS
from .build import normalize_events
from .labels import interval_panel
from .http import Store,utcnow
from .connectors import arcgis
from .census_coverage import ROOT,join_points


def archive_pointer(month):
    for p in [Path(f'data/staged/temporal_v2/history_{month}.json'),Path(f'data/staged/history_{month}.json')]:
        if p.exists():return json.loads(p.read_text())
    raise ValueError('Cached archive unavailable: '+month)


def acquire():
    cfg=json.loads(Path('config/coverage_v4.json').read_text());ROOT.mkdir(parents=True,exist_ok=True)
    streets=gpd.read_parquet('data/processed/street_segments.parquet');meters=gpd.read_parquet('data/processed/meters.parquet')
    conn=duckdb.connect();roster=set()
    for month in ['2025_09','2026_06']:
        pointer=archive_pointer(month);year,num=map(int,month.split('_'));start=pd.Timestamp(year=year,month=num,day=1,tz='America/Los_Angeles').tz_convert('UTC');end=start+pd.Timedelta('7D')
        ids=conn.execute('SELECT DISTINCT SpaceID FROM read_csv_auto(?) WHERE EventTime_UTC>=? AND EventTime_UTC<?',[pointer['path'],start.tz_localize(None),end.tz_localize(None)]).fetchdf()
        roster.update(ids.SpaceID.astype(str))
    selected=[];all_mapping=[];regions=[];neighborhood_reports={}
    for name,bounds in cfg['neighborhoods'].items():
        points=meters.loc[meters.intersects(box(*bounds))].copy();mapping=assign_meters(points,streets)
        active=mapping.loc[mapping.join_status.eq('matched')&mapping.space_id.isin(roster)]
        candidates=sorted(active.segment_id.unique(),key=lambda x:hashlib.sha256(f'{cfg["seed"]}|{x}'.encode()).hexdigest())
        chosen=candidates[:cfg['maximum_new_blocks_each']];selected.extend(chosen)
        # Include all meters on the complete selected physical streets, even across bbox edges.
        segment=streets.loc[streets.segment_id.isin(chosen)];buffer=segment.to_crs(METRIC_CRS).buffer(40).union_all()
        whole=meters.loc[meters.to_crs(METRIC_CRS).intersects(buffer)]
        mapped=assign_meters(whole,streets);mapped=mapped.loc[mapped.segment_id.isin(chosen)].copy();mapped['region']=name;all_mapping.append(mapped)
        centers=segment.to_crs(METRIC_CRS).geometry.interpolate(.5,normalized=True);ll=centers.to_crs(4326)
        regions.append(pd.DataFrame({'block_id':segment.segment_id.to_numpy(),'region':name,'x':centers.x.to_numpy(),'y':centers.y.to_numpy(),'longitude':ll.x.to_numpy(),'latitude':ll.y.to_numpy()}))
        neighborhood_reports[name]={'candidate_inventory_meters':len(points),'discovery_reporting_candidate_blocks':len(candidates),'selected_blocks':len(chosen),'mapped_inventory_meters_on_full_blocks':len(mapped),'initial_join_status':mapping.join_status.value_counts().to_dict()}
    mapping=pd.concat(all_mapping,ignore_index=True)
    if mapping.space_id.duplicated().any():raise ValueError('Duplicate regional sensor lineage')
    mapping.to_parquet(ROOT/'meter_mapping.parquet',index=False)
    region=pd.concat(regions,ignore_index=True);region.to_parquet(ROOT/'regions.parquet',index=False)
    streets.loc[streets.segment_id.isin(selected)].to_parquet(ROOT/'selected_streets.parquet',index=False)
    faces=gpd.read_parquet('data/processed/block_faces.parquet');faces.loc[faces.segment_id.isin(selected)].to_parquet(ROOT/'selected_faces.parquet',index=False)
    census=join_points(region);census.to_parquet(ROOT/'regional_census.parquet',index=False)
    ids=pd.DataFrame({'spaceid':mapping.space_id});conn.register('chosen_ids',ids);month_reports={}
    for month in cfg['sensor_archive_months']:
        print('Regional archive',month,flush=True);pointer=archive_pointer(month)
        raw=conn.execute('SELECT * FROM read_csv_auto(?) WHERE SpaceID IN (SELECT spaceid FROM chosen_ids)',[pointer['path']]).fetchdf()
        events,rejects,dupes=normalize_events(raw,'regional_archive_'+month,pointer['record']['retrieved_at_utc']);events.to_parquet(ROOT/f'events_{month}.parquet',index=False)
        year,num=map(int,month.split('_'));start=pd.Timestamp(year=year,month=num,day=1,tz='America/Los_Angeles');end=start+pd.DateOffset(months=1);discovery=start+pd.Timedelta('7D')
        panel,quality=interval_panel(events,mapping,discovery,end,15,15,discovery);panel['source_month']=month;panel['block_id']=panel.block_face_id.str.rsplit(':',n=1).str[0];panel=panel.merge(region[['block_id','region']],on='block_id',validate='many_to_one')
        panel.to_parquet(ROOT/f'panel_{month}.parquet',index=False)
        month_reports[month]={'archive_sha256':pointer['record']['sha256'],'new_download':False,'events':len(events),'rejected':len(rejects),'duplicates':dupes,'quality':quality,'unknown_events':int(events.state.eq('UNKNOWN').sum()),
            'by_region':[{**{'region':name},'face_bins':len(g),'supported_rate_bins':int((g.coverage_fraction.ge(.25)&g.occupancy_rate.notna()).sum()),'faces':g.block_face_id.nunique(),'blocks':g.block_id.nunique()} for name,g in panel.groupby('region')]}
    conn.close()
    roster_report=check_locations(cfg,meters)
    report={'built_at_utc':utcnow(),'neighborhoods':neighborhood_reports,'months':month_reports,'current_sensor_location_checks':roster_report,'sensor_status':'Current SENSOR_STATUS values excluded to preserve holdouts; historical UNKNOWN and report gaps remain uncertain, not vacancy.',
        'census_join':{'blocks':len(census),'missing_tracts':int(census.tract_id.isna().sum()),'missing_household_features':int(census.no_vehicle_fraction.isna().sum())},
        'new_occupancy_archive_downloads':0,'fresh_holdouts_opened':False,'unmetered_occupancy_labels':0,'citywide_accuracy_validated':False,'geometry_vintage':'Current inventory/map; historical mapping and relocations unverified; sensor locations are not stalls or legal supply'}
    Path('reports/modeling/coverage_v4_acquisition.json').write_text(json.dumps(report,indent=2,default=lambda x:int(x) if isinstance(x,np.integer) else str(x)),encoding='utf8');print(json.dumps(report,indent=2));return report


def check_locations(cfg,meters):
    # Current map metadata/locations only. Explicitly exclude SENSOR_STATUS values.
    roster_report={};store=Store(max_mb=5);layer='https://maps.lacity.org/lahub/rest/services/LADOT/MapServer/16'
    mxy=meters.to_crs(METRIC_CRS);tree=BallTree(np.c_[mxy.geometry.x,mxy.geometry.y]);meter_ids=meters.spaceid.astype(str).to_numpy()
    for name,bounds in cfg['neighborhoods'].items():
        try:
            obj,meta,oid=arcgis(store,layer,bbox=bounds,max_features=4500,batch=250,out_fields='OBJECTID,SENSOR_UNIQUE_ID,GPSX,GPSY,MTYPE,ADDRESS_SPACE')
            g=gpd.GeoDataFrame.from_features(obj['features'],crs=4326)
            if 'SENSOR_STATUS' in g:raise ValueError('Reserved status values must not be requested')
            geo=g.to_crs(METRIC_CRS);distance,index=tree.query(np.c_[geo.geometry.x,geo.geometry.y],k=2)
            g['nearest_inventory_space_id']=meter_ids[index[:,0]];g['nearest_inventory_distance_m']=distance[:,0];g['nearest_location_ambiguous']=(distance[:,1]-distance[:,0])<=3
            g.to_parquet(ROOT/f'current_sensor_locations_{name.lower()}.parquet',index=False)
            roster_report[name]={'rows':len(g),'complete_ids_verified':True,'distance_over_35m':int((distance[:,0]>35).sum()),'location_ambiguous':int(g.nearest_location_ambiguous.sum()),'status_values_requested':False,'historical_install_or_move_dates':'unavailable; current locations do not prove historical sensor location'}
        except Exception as exc:roster_report[name]={'status':'unavailable','reason':str(exc),'status_values_requested':False}
    return roster_report


def audit_existing():
    """Repeat location checks without rescanning archives or requesting states."""
    from .sensor_audit import event_patterns
    cfg=json.loads(Path('config/coverage_v4.json').read_text())
    path=Path('reports/modeling/coverage_v4_acquisition.json');report=json.loads(path.read_text())
    report['current_sensor_location_checks']=check_locations(cfg,gpd.read_parquet('data/processed/meters.parquet'))
    mapping=pd.read_parquet(ROOT/'meter_mapping.parquet');summaries={}
    for month in cfg['sensor_archive_months']:
        year,num=map(int,month.split('_'));start=pd.Timestamp(year=year,month=num,day=1,tz='America/Los_Angeles');end=start+pd.DateOffset(months=1)
        events=pd.read_parquet(ROOT/f'events_{month}.parquet');summaries[month]={}
        for name in cfg['neighborhoods']:
            ids=set(mapping.loc[mapping.region.eq(name),'space_id']);e=events.loc[events.space_id.isin(ids)]
            summary,_=event_patterns(e,start,end,ids);summaries[month][name]=summary
    report['event_reporting_audit']=summaries
    report['location_budget_note']='Downtown first query stopped at 4002 > 2000. Explicit ceiling increased to 4500 location-only features, exact object ID reconciliation; no truncated page accepted.'
    path.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report['current_sensor_location_checks'],indent=2))
