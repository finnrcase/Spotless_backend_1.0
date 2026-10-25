"""Bounded public Census context, with source vintage and availability gates."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.neighbors import BallTree
from shapely.geometry import box
from .http import Store
from .connectors import arcgis
from .spatial import METRIC_CRS

HOUSING=['census_population_600','census_housing_600','acs_housing_density','acs_no_vehicle_fraction','acs_households_density']
JOBS=['lodes_jobs_known_600','lodes_block_match_fraction_600']
AVAILABILITY={**{c:'2024-12-13T00:00Z' for c in HOUSING},**{c:'2025-12-19T00:00Z' for c in JOBS}}


def asof_context(frame,context):
    f=frame.merge(context,on='block_id',how='left',validate='many_to_one')
    for col,available in AVAILABILITY.items():
        f.loc[f.issued_at_utc<pd.Timestamp(available),col]=np.nan
    return f


def manual_demand_predictors(requests,context,context_available_at):
    """Independent predictor rows for the reviewed unmetered/mixed comparison.

    Requests contain IDs and forecast times only. No count, capacity or rule label
    enters this join. For prospective use, respect actual local snapshot creation.
    """
    required=['observation_id','block_id','prediction_issued_at_utc']
    if not set(required)<=set(requests) or requests.observation_id.duplicated().any():raise ValueError('Unique observation IDs, physical block IDs and issue timestamps required')
    f=requests[required].copy();stamps=[pd.Timestamp(v) for v in f.prediction_issued_at_utc]
    available=pd.Timestamp(context_available_at)
    if available.tzinfo is None or any(pd.isna(v) or v.tzinfo is None for v in stamps):raise ValueError('Timezone-aware predictor availability and issue times required')
    f['issued_at_utc']=pd.to_datetime(stamps,utc=True);f=asof_context(f,context)
    columns=HOUSING+JOBS
    f.loc[f.issued_at_utc<available,columns]=np.nan
    observed=f[columns].notna().any(axis=1)
    f['feature_available_at_utc']=pd.to_datetime(np.where(observed,available.tz_convert('UTC'),f.issued_at_utc),utc=True)
    f['demand_context_status']=np.where(observed,'cached_public_demand_context','unavailable_at_issue_or_outside_coverage')
    return f[['observation_id','prediction_issued_at_utc','feature_available_at_utc','demand_context_status']+columns]


def acquire_predictors():
    out=Path('data/modeling/temporal_v2');out.mkdir(parents=True,exist_ok=True)
    store=Store(max_mb=85);report={'sources':{},'availability':AVAILABILITY,'unavailable':{
        'verified_curb_supply_restrictions':'No historically versioned sign-complete legal supply; historic curb polygons are not stalls.',
        'business_activity':'October 2026 account snapshot cannot reconstruct closures or issued historical hours. Excluded.',
        'events':'No pre-issue archived attendance/calendar versions for evaluation periods. Excluded.',
        'weather_transit':'Current snapshots do not provide historical issued forecasts/schedules. Excluded.'}}
    base='https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/tigerWMS_Census2020/MapServer'
    bbox=[-118.473,34.038,-118.417,34.087] # pilot plus >600m buffer
    layers={}
    for name,number,budget in [('blocks',10,1500),('tracts',6,100)]:
        path=out/f'census2020_{name}.parquet'
        if path.exists():g=gpd.read_parquet(path)
        else:
            obj,meta,oid=arcgis(store,base+'/'+str(number),bbox=bbox,max_features=budget,batch=100)
            g=gpd.GeoDataFrame.from_features(obj['features'],crs=4326);g.to_parquet(path,index=False)
        if g.GEOID.duplicated().any():raise ValueError('Duplicate Census geographic IDs')
        layers[name]=g;report['sources'][name]={'url':base+'/'+str(number),'rows':len(g),'bbox':bbox,'complete_id_pages':True,'vintage':'2020-01-01; full intersecting polygons, not clipped'}
    tracts=layers['tracts'];wanted=set('1400000US'+tracts.GEOID.astype(str))
    tables=[]
    for table in ['b08201','b25001']:
        url=f'https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/acsdt5y2023-{table}.dat'
        try:
            path,record=store.get(url,max_mb=85);parts=[]
            for chunk in pd.read_csv(path,sep='|',dtype=str,chunksize=30000):
                # Census table-based summary file uses GEO_ID and estimate/MOE pairs.
                parts.append(chunk.loc[chunk.GEO_ID.isin(wanted)])
            t=pd.concat(parts,ignore_index=True);t['tract_id']=t.GEO_ID.str[-11:]
            t.to_parquet(out/f'acs2023_{table}.parquet',index=False);tables.append(t.set_index('tract_id'))
            report['sources'][table]={'url':url,'bytes':record['bytes'],'sha256':record['sha256'],'tracts_matched':len(t),'retrieved_at_utc':record['retrieved_at_utc'],'last_modified':record.get('headers',{}).get('Last-Modified'),
                'survey_period':'2019-2023','public_release':'2024-12-12','MOE':'Retained in staged table. Tract survey estimates are contextual predictors, not occupancy truth.'}
            print('ACS',table,len(t),'tracts',flush=True)
        except Exception as exc:report['sources'][table]={'status':'unavailable','reason':str(exc)}
    ctx=pd.read_parquet('data/modeling/current_context.parquet');points=gpd.GeoDataFrame(ctx[['segment_id']],geometry=gpd.points_from_xy(ctx.longitude,ctx.latitude),crs=4326)
    joined=gpd.sjoin(points,tracts[['GEOID','geometry']],how='left',predicate='within').drop(columns='index_right')
    if joined.segment_id.duplicated().any():raise ValueError('Ambiguous tract join; do not silently choose one')
    c=joined.rename(columns={'segment_id':'block_id','GEOID':'tract_id'}).drop(columns='geometry')
    for col in HOUSING+JOBS:c[col]=np.nan
    if tables:
        acs=pd.concat(tables,axis=1);acs=acs.loc[:,~acs.columns.duplicated()]
        for col in acs:
            if col.endswith(tuple(str(i).zfill(3) for i in range(1,50))):
                acs[col]=pd.to_numeric(acs[col],errors='coerce').where(lambda x:x>=0)
        def v(name):return pd.to_numeric(acs.get(name,pd.Series(np.nan,index=acs.index)),errors='coerce').where(lambda x:x>=0)
        area=tracts.set_index('GEOID').AREALAND.astype(float)/1e6
        acs['acs_housing_density']=v('B25001_E001')/area
        acs['acs_households_density']=v('B08201_E001')/area
        acs['acs_no_vehicle_fraction']=v('B08201_E002')/v('B08201_E001').replace(0,np.nan)
        for col in HOUSING[2:]:c[col]=c.tract_id.map(acs[col])
    blocks=layers['blocks'].copy();blocks['GEOID']=blocks.GEOID.astype(str)
    jobs=pd.read_parquet('data/processed/lodes_la_wac_2023.parquet');jobs['GEOID']=jobs.w_geocode.astype(str).str.zfill(15)
    if jobs.GEOID.duplicated().any():raise ValueError('Duplicate workplace block IDs')
    blocks=blocks.merge(jobs[['GEOID','C000']],on='GEOID',how='left',validate='one_to_one')
    bp=blocks.to_crs(METRIC_CRS).geometry.representative_point();tree=BallTree(np.c_[bp.x,bp.y]);indices=tree.query_radius(ctx[['x','y']].to_numpy(),r=600)
    for i,idx in enumerate(indices):
        b=blocks.iloc[idx]
        if not len(b):continue
        for target,source in [('census_population_600','POP100'),('census_housing_600','HU100'),('lodes_jobs_known_600','C000')]:
            c.loc[i,target]=pd.to_numeric(b[source],errors='coerce').sum(min_count=1)
        c.loc[i,'lodes_block_match_fraction_600']=b.C000.notna().mean()
    extent=gpd.GeoSeries([box(*bbox)],crs=4326).to_crs(METRIC_CRS).iloc[0]
    neighborhoods=gpd.GeoSeries(gpd.points_from_xy(ctx.x,ctx.y),crs=METRIC_CRS).buffer(600)
    complete=neighborhoods.within(extent)
    c.loc[~complete,HOUSING[:2]+JOBS]=np.nan
    report['spatial_query_coverage']={'full_600m_neighborhoods':int(complete.sum()),'incomplete_neighborhoods':int((~complete).sum()),'incomplete_block_ids':c.loc[~complete,'block_id'].tolist(),'handling':'Neighborhood counts/match fraction remain missing outside the complete query envelope; full-tract ACS estimates remain available.'}
    c.to_parquet(out/'context_asof.parquet',index=False)
    report.update(rows=len(c),feature_nonmissing={col:int(c[col].notna().sum()) for col in HOUSING+JOBS},
        aggregation='600m from street center to full block representative point; approximate demand context, not supply. Missing workplace blocks are not zero jobs.',
        lodes={'year':2023,'source_file_modified':'2025-12-03 (official directory; not public release time)','public_release':'2025-12-18','conservative_available':'2025-12-19','September_2025_values_masked':True,'matched_blocks':int(blocks.C000.notna().sum()),'geographic_blocks':len(blocks),
            'geography':'2020 block identifiers; published OnTheMap geometry is TIGER 2024. This join uses Census2020 geometry as an approximate fallback; unmatched IDs remain missing.'},
        sources_references=['https://www.census.gov/programs-surveys/acs/news/data-releases/2023/release-schedule.html','https://lehd.ces.census.gov/data/lodes/LODES8/ca/wac/','https://www.census.gov/programs-surveys/ces/news-and-updates/updates/12182025.html'])
    Path('reports/modeling/temporal_v2_predictors.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return c
