"""Expand existing Census vintages, preserve MOEs and avoid duplicate predictors."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from .http import Store
from .connectors import arcgis

ROOT=Path('data/modeling/coverage_v4');NEW=['vehicle_lower_bound_per_household','one_person_household_fraction']


def derive(frame):
    f=frame.copy()
    def number(name):return pd.to_numeric(f[name],errors='coerce').where(lambda x:x>=0)
    hh=number('B08201_E001').replace(0,np.nan)
    f['no_vehicle_fraction']=number('B08201_E002')/hh
    f['vehicle_lower_bound_per_household']=sum(w*number(f'B08201_E{i:03}') for i,w in [(3,1),(4,2),(5,3),(6,4)])/hh
    f['one_person_household_fraction']=number('B08201_E007')/hh
    f['zero_household_denominator']=number('B08201_E001').eq(0)
    f['derived_ratio_moe']=np.nan
    return f


def acquire():
    ROOT.mkdir(parents=True,exist_ok=True);store=Store(max_mb=85);tables=[];sources={}
    for name in ['b08201','b25001']:
        url=f'https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/acsdt5y2023-{name}.dat'
        raw,rec=store.get(url,max_mb=85);parts=[]
        for chunk in pd.read_csv(raw,sep='|',dtype=str,chunksize=50000):parts.append(chunk.loc[chunk.GEO_ID.str.startswith('1400000US06037',na=False)])
        f=pd.concat(parts,ignore_index=True);f['tract_id']=f.GEO_ID.str[-11:]
        if f.tract_id.duplicated().any():raise ValueError('Duplicate Census tract IDs')
        old=pd.read_parquet(f'data/modeling/temporal_v2/acs2023_{name}.parquet').set_index('tract_id');new=f.set_index('tract_id')
        common=old.index.intersection(new.index);compare=[c for c in old.columns if c in new and c!='GEO_ID']
        mismatches=int((old.loc[common,compare].fillna('<null>')!=new.loc[common,compare].fillna('<null>')).to_numpy().sum())
        sources[name]={'url':url,'sha256':rec['sha256'],'retrieved_at_utc':rec['retrieved_at_utc'],'cached_national_bytes':rec['bytes'],'extracted_county_tracts':len(f),'previous_tracts':len(old),'common_tracts':len(common),'estimate_and_moe_cell_mismatches':mismatches}
        tables.append(f.set_index('tract_id').drop(columns='GEO_ID'))
    values=pd.concat(tables,axis=1);values=derive(values);values.reset_index().to_parquet(ROOT/'census_tracts_2023.parquet',index=False)
    layer='https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/tigerWMS_Census2020/MapServer/6';path=ROOT/'tract_geometry.parquet'
    if not path.exists():
        obj,_,_=arcgis(store,layer,where="STATE='06' AND COUNTY='037'",max_features=3000,batch=250)
        g=gpd.GeoDataFrame.from_features(obj['features'],crs=4326);g.to_parquet(path,index=False)
    else:g=gpd.read_parquet(path)
    joined=g[['GEOID','AREALAND']].rename(columns={'GEOID':'tract_id'}).merge(values.reset_index(),on='tract_id',how='left',validate='one_to_one')
    joined['housing_density']=pd.to_numeric(joined.B25001_E001,errors='coerce').where(lambda x:x>=0)/(pd.to_numeric(joined.AREALAND)/1e6)
    joined.to_parquet(ROOT/'tract_features.parquet',index=False)
    oldctx=pd.read_parquet('data/modeling/temporal_v2/context_asof.parquet');test=oldctx.merge(joined[['tract_id','no_vehicle_fraction']],on='tract_id',how='left',validate='many_to_one')
    valid=test.acs_no_vehicle_fraction.notna()&test.no_vehicle_fraction.notna()
    report={'year':2023,'survey_period':'2019-2023','public_release':'2024-12-12','available_at_utc':'2024-12-13T00:00:00Z','sources':sources,'geometry_source':layer,'county_geometry_tracts':len(g),
        'county_tracts_without_matching_2023_table':int(joined.B08201_E001.isna().sum()),'previous_context_rows':len(test),'existing_vehicle_fraction_pairs':int(valid.sum()),'existing_vehicle_fraction_max_abs_difference':float((test.loc[valid,'acs_no_vehicle_fraction']-test.loc[valid,'no_vehicle_fraction']).abs().max()),
        'previous_missing_vehicle_rows':int(test.acs_no_vehicle_fraction.isna().sum()),'newly_filled_previous_vehicle_rows':int((test.acs_no_vehicle_fraction.isna()&test.no_vehicle_fraction.notna()).sum()),'zero_household_tracts':int(values.zero_household_denominator.sum()),
        'new_features':NEW,'duplicate_predictors_added':False,'moe_handling':'All original estimate and 90% margin-of-error columns retained, including sentinel codes. Derived ratio MOE remains null; numerator/denominator MOEs are not sufficient to assert covariance.',
        'vehicle_censoring':'4+ vehicle households contribute four to a lower bound, not an exact vehicle count. No-vehicle complement is not added as a duplicate predictor.',
        'occupancy_labels_created':0,'api_comparison':json.loads(Path('reports/modeling/census_v4_auth.json').read_text())}
    Path('reports/modeling/census_v4_comparison.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps({k:v for k,v in report.items() if k not in ['sources','api_comparison']},indent=2));return report


def join_points(context):
    """Exact polygon GEOID join; no nearest-tract imputation across missing boundaries."""
    g=gpd.read_parquet(ROOT/'tract_geometry.parquet');points=gpd.GeoDataFrame(context.copy(),geometry=gpd.points_from_xy(context.longitude,context.latitude),crs=4326)
    result=gpd.sjoin(points,g[['GEOID','geometry']],how='left',predicate='within').drop(columns='index_right').rename(columns={'GEOID':'tract_id'})
    if result.block_id.duplicated().any():raise ValueError('Ambiguous tract assignment')
    return pd.DataFrame(result.drop(columns='geometry')).merge(pd.read_parquet(ROOT/'tract_features.parquet'),on='tract_id',how='left',validate='many_to_one')
