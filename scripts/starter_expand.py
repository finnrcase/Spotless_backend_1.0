"""Follow actual public API discoveries; spatially bound new geometry."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
from starter_sources import api,check,checks,store
from la_parking.connectors import arcgis,socrata
from la_parking.spatial import read_features
from la_parking.starter import BBOX
import pandas as pd

cds='https://gisserver.dot4la.org/server/rest/services/Sandbox_Environment/Curb_Data_Specification/FeatureServer'
check('code_the_curb_cds_service',lambda:api(cds,{'f':'json'}))
if checks['code_the_curb_cds_service']['status']=='retrieved':
    d=checks['code_the_curb_cds_service']['data']
    for layer in (d.get('layers',[])+d.get('tables',[]))[:10]:
        base=cds+'/'+str(layer['id'])
        check('cds_schema_'+str(layer['id']),lambda base=base:api(base,{'f':'json'}))
        check('cds_sample_'+str(layer['id']),lambda base=base:api(base+'/query',{'f':'json','where':'1=1','outFields':'*','returnGeometry':'true','outSR':4326,'resultRecordCount':2}))
analysis='https://services1.arcgis.com/tp9wqSVX1AitKgjd/arcgis/rest/services/Code_the_Curb_Corridor_Analysis/FeatureServer'
check('code_the_curb_corridor_service',lambda:api(analysis,{'f':'json'}))
check('code_the_curb_corridor_layer_schema',lambda:api(analysis+'/0',{'f':'json'}))
check('code_the_curb_corridor_sample',lambda:api(analysis+'/0/query',{'f':'json','where':'1=1','outFields':'*','outSR':4326,'resultRecordCount':2}))
check('code_the_curb_westwood_count',lambda:api(analysis+'/0/query',{'f':'json','where':'1=1','geometry':','.join(map(str,BBOX)),'geometryType':'esriGeometryEnvelope','inSR':4326,'spatialRel':'esriSpatialRelIntersects','returnCountOnly':'true'}))
check('legacy_permit_geojson',lambda:api('https://data.lacity.org/resource/2ckn-xmjp.geojson',{'$limit':1000}))
check('official_permit_services',lambda:__import__('starter_sources').page('https://ladot.lacity.gov/onlineservices'))
check('official_permit_faq',lambda:__import__('starter_sources').page('https://ladot.lacity.gov/about/faq'))
check('permit_policy_current',lambda:__import__('starter_sources').page('https://ladotparking.org/permits/'))

def blocks():
    layer='https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/tigerWMS_Census2020/MapServer/10'
    obj,meta,oid=arcgis(store,layer,bbox=BBOX,max_features=1500,batch=100)
    path=Path('data/staged/starter/census2020_blocks.geojson');path.write_text(json.dumps(obj),encoding='utf8')
    frame=read_features(path);frame.to_parquet(path.with_suffix('.parquet'),index=False)
    jobs=pd.read_parquet('data/processed/lodes_la_wac_2023.parquet');jobs['GEOID']=jobs.w_geocode.astype(str).str.zfill(15)
    joined=frame.merge(jobs,on='GEOID',how='left',validate='one_to_one')
    joined.to_parquet('data/staged/starter/pilot_workplace_blocks_2023.parquet',index=False)
    return {'source_url':layer,'geometry_rows':len(frame),'matched_workplace_rows':int(joined.C000.notna().sum()),'workplace_vintage':2023,
        'unmatched_are_missing_not_zero':True,'available_for_historical_forecasts':'Publication/availability date still needs verification; not added to primary backtests'}
check('pilot_workplace_geography',blocks)

def permits():
    frame=socrata(store,'2ckn-xmjp',max_rows=20000)
    if frame.empty:raise ValueError('Empty permit dataset')
    frame.to_parquet('data/staged/starter/permit_district_export.parquet',index=False)
    return {'rows':len(frame),'columns':frame.columns.tolist(),'legal_rule_completeness':False,'source_url':'https://data.lacity.org/d/2ckn-xmjp'}
check('permit_district_export',permits)

def permit_geometry():
    layer='https://maps.lacity.org/arcgis/rest/services/Permits/BOE_Permits_Geocoder/MapServer/403'
    obj,meta,oid=arcgis(store,layer,bbox=BBOX,max_features=1000,batch=100)
    path=Path('data/staged/starter/permit_district_geometry.geojson');path.write_text(json.dumps(obj))
    if obj['features']:read_features(path).to_parquet(path.with_suffix('.parquet'),index=False)
    return {'source_url':layer,'features':len(obj['features']),'schema_fields':meta['fields'],'geometry_type':meta['geometryType'],
        'geometry_source_vintage_verified':False,'restrictions_and_permit_eligibility_verified':False}
check('pilot_permit_geometry',permit_geometry)
