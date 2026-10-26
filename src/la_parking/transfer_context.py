"""Versioned demand joins for spatial transfer; no occupancy labels are generated."""
import json
from pathlib import Path
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.neighbors import BallTree
from .http import Store
from .spatial import METRIC_CRS
from .temporal_predictors import HOUSING,asof_context

ROOT=Path('data/modeling/spatial_v3')
SECTORS={'jobs':'C000','retail_jobs':'CNS07','education_jobs':'CNS15','healthcare_jobs':'CNS16','arts_jobs':'CNS17','food_jobs':'CNS18'}
EMPLOYMENT=['log_'+name+'_600' for name in SECTORS]+['employment_record_fraction','employment_vintage_age','jobs_x_weekday_daytime','retail_food_x_evening']
HOUSING_FEATURES=['log_population_600','log_housing_600','log_acs_housing_density','acs_no_vehicle_fraction','log_acs_households_density']
GEOMETRY=['street_length_m','network_centers_100','map_x_km','map_y_km']


def acquire():
    ROOT.mkdir(parents=True,exist_ok=True);store=Store(max_mb=12)
    url='https://lehd.ces.census.gov/data/lodes/LODES8/ca/wac/ca_wac_S000_JT00_2022.csv.gz'
    raw,record=store.get(url,max_mb=12)
    created=[];parts=[];blocks=gpd.read_parquet('data/modeling/temporal_v2/census2020_blocks.parquet')
    for chunk in pd.read_csv(raw,compression='gzip',dtype={'w_geocode':str},usecols=['w_geocode','createdate']+list(SECTORS.values()),chunksize=50000):
        selected=chunk.loc[chunk.w_geocode.isin(set(blocks.GEOID.astype(str)))];parts.append(selected);created.extend(selected.createdate.astype(str))
    jobs2022=pd.concat(parts,ignore_index=True)
    modified=parsedate_to_datetime(record['headers']['Last-Modified'])
    historical_2022=modified<pd.Timestamp('2024-11-21T00:00Z') and all(x<='20241120' for x in created)
    jobs2022.to_parquet(ROOT/'workplaces_2022.parquet',index=False)
    jobs2023=pd.read_parquet('data/processed/lodes_la_wac_2023.parquet',columns=['w_geocode','createdate']+list(SECTORS.values()))
    ctx=pd.read_parquet('data/modeling/current_context.parquet');bp=blocks.to_crs(METRIC_CRS).geometry.representative_point()
    indices=BallTree(np.c_[bp.x,bp.y]).query_radius(ctx[['x','y']].to_numpy(),r=600)
    coverage=json.loads(Path('reports/modeling/temporal_v2_predictors.json').read_text())['spatial_query_coverage']
    incomplete=set(coverage['incomplete_block_ids']);frames=[];matches={}
    for year,jobs,available in [(2022,jobs2022,'2024-11-21T00:00Z'),(2023,jobs2023,'2025-12-19T00:00Z')]:
        jobs=jobs.copy();jobs['GEOID']=jobs.w_geocode.astype(str).str.zfill(15)
        if jobs.GEOID.duplicated().any():raise ValueError('Duplicate workplace geography')
        joined=blocks[['GEOID']].merge(jobs,on='GEOID',how='left',validate='one_to_one');rows=[]
        for i,ix in enumerate(indices):
            b=joined.iloc[ix];valid=len(b)>0 and ctx.segment_id.iloc[i] not in incomplete and (year!=2022 or historical_2022)
            row={'block_id':ctx.segment_id.iloc[i],'employment_year':year,'available_at_utc':pd.Timestamp(available)}
            for name,col in SECTORS.items():row['log_'+name+'_600']=float(np.log1p(b[col].sum(min_count=1))) if valid else np.nan
            row['employment_record_fraction']=float(b.C000.notna().mean()) if valid else np.nan;rows.append(row)
        frames.append(pd.DataFrame(rows));matches[str(year)]={'matched_census_blocks':int(joined.C000.notna().sum()),'census_blocks':len(blocks)}
    pd.concat(frames,ignore_index=True).to_parquet(ROOT/'employment_context.parquet',index=False)
    streets=gpd.read_parquet('data/processed/pilot_street_segments.parquet').to_crs(METRIC_CRS).set_index('segment_id');geo=ctx[['segment_id','x','y']].copy()
    geo['street_length_m']=geo.segment_id.map(streets.geometry.length);geo['network_centers_100']=BallTree(ctx[['x','y']]).query_radius(ctx[['x','y']],r=100,count_only=True)
    geo['map_x_km']=(geo.x-ctx.x.mean())/1000;geo['map_y_km']=(geo.y-ctx.y.mean())/1000
    geo.rename(columns={'segment_id':'block_id'})[['block_id']+GEOMETRY].to_parquet(ROOT/'geometry_context.parquet',index=False)
    now=datetime.now(timezone.utc).isoformat();forward=ctx[['segment_id','business_100','business_300','business_600','food_retail_300']].rename(columns={'segment_id':'block_id'})
    forward['available_at_utc']=pd.Timestamp(now)
    for col in ['verified_eligible_capacity','permit_required','restriction_minutes_during_stay','event_count_600m']:forward[col]=np.nan
    forward.to_parquet(ROOT/'prospective_context.parquet',index=False)
    report={'built_at_utc':now,'occupancy_labels_created':0,'2022_source':{k:record[k] for k in ['url','sha256','bytes','retrieved_at_utc']},'2022_last_modified':modified.isoformat(),'2022_createdate_min':min(created),'2022_createdate_max':max(created),
        '2022_historical_version_consistent':historical_2022,'2022_public_release':'2024-11-19','2022_availability_gate':'2024-11-21T00:00Z','2023_availability_gate':'2025-12-19T00:00Z','matches':matches,
        'features':{'housing':HOUSING_FEATURES,'employment':EMPLOYMENT,'exploratory_geometry':GEOMETRY},'coverage':{'employment':{str(int(y)):g.notna().sum().to_dict() for y,g in pd.concat(frames).groupby('employment_year')},'prospective_business_nonmissing':{c:int(forward[c].notna().sum()) for c in ['business_100','business_300','business_600','food_retail_300']}},
        'prospective_only':'Active-business snapshot cannot reconstruct historical closures. Categories are available for prospective collection; counts are registration accounts, not verified activity or hours.',
        'unavailable':{'verified_supply_rules':'No sign-complete versioned capacity or restrictions; null remains null. Historic curb polygons are not stalls.','events':'No verified pre-issue event archive or attendance/geocode join; event_count remains null.','business_activity':'Verified operating hours, closures and footfall unavailable.'},
        'geographic_caveat':'Census2020 block polygons approximate the later TIGER geometry used with LODES. Missing workplace blocks stay missing, not zero. LODES is a disclosure-protected statistical predictor, not an occupancy observation.',
        'sources':['https://www.census.gov/programs-surveys/ces/news-and-updates/updates/11192024.html','https://lehd.ces.census.gov/data/lodes/LODES8/LODESTechDoc8.3.pdf']}
    Path('reports/modeling/spatial_v3_context.json').write_text(json.dumps(report,indent=2,default=lambda x:int(x) if isinstance(x,np.integer) else str(x)),encoding='utf8')
    print('2022 historical vintage verified:',historical_2022,'matched workplace blocks',matches,flush=True)
    return report


def enrich(frame):
    f=asof_context(frame,pd.read_parquet('data/modeling/temporal_v2/context_asof.parquet'))
    for original,new in zip(HOUSING,HOUSING_FEATURES):f[new]=f[original] if original=='acs_no_vehicle_fraction' else np.log1p(f[original])
    jobs=pd.read_parquet(ROOT/'employment_context.parquet')
    for col in EMPLOYMENT:f[col]=np.nan
    for year in [2022,2023]:
        y=jobs.loc[jobs.employment_year.eq(year)].set_index('block_id');values=y.reindex(f.block_id)
        safe=np.asarray(pd.to_datetime(values.available_at_utc.to_numpy(),utc=True)<=f.issued_at_utc.to_numpy())
        for col in ['log_'+n+'_600' for n in SECTORS]+['employment_record_fraction']:f.loc[safe,col]=values[col].to_numpy()[safe]
        f.loc[safe,'employment_vintage_age']=f.loc[safe,'arrival_time_utc'].dt.year-year
    local=f.arrival_time_utc.dt.tz_convert('America/Los_Angeles');f['jobs_x_weekday_daytime']=f.log_jobs_600*((local.dt.dayofweek<5)&local.dt.hour.between(8,17))
    f['retail_food_x_evening']=(f.log_retail_jobs_600+f.log_food_jobs_600)*local.dt.hour.between(17,22)
    f=f.merge(pd.read_parquet(ROOT/'geometry_context.parquet'),on='block_id',how='left',validate='many_to_one')
    return f
