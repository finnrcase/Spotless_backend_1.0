"""Small verified context acquisitions, independent of the core run."""
import json
from pathlib import Path
import pandas as pd
from la_parking.http import Store
from la_parking.connectors import arcgis
from la_parking.sources import NAV,PILOT

s=Store(); stage=Path('data/staged'); result={}
def attempt(name,fn):
 try: result[name]={'status':'verified/downloaded','result':fn()}
 except Exception as exc: result[name]={'status':'blocked','error':str(exc)}; print(name,exc,flush=True)
 Path('reports/supplement_status.json').write_text(json.dumps(result,indent=2),encoding='utf8')

def curbs():
 obj,meta,oid=arcgis(s,f'{NAV}/324',bbox=PILOT,max_features=25000)
 (stage/'curbs.geojson').write_text(json.dumps(obj),encoding='utf8')
 (stage/'curbs_metadata.json').write_text(json.dumps(meta),encoding='utf8')
 return {'features':len(obj['features']),'scope':PILOT}
attempt('curbs',curbs)

def weather(year):
 # Station IDs verified in Spotless source documentation; actual date ranges inspected below.
 path,rec=s.get(f'https://www.ncei.noaa.gov/data/global-hourly/access/{year}/72295023174.csv',max_mb=20)
 frame=pd.read_csv(path)
 frame.to_parquet(stage/f'lax_weather_{year}.parquet',index=False)
 return {'rows':len(frame),'min_date':str(frame.DATE.min()),'max_date':str(frame.DATE.max()),'retrieved_at_utc':rec['retrieved_at_utc'],'sha256':rec['sha256']}
for year in [2025,2026]: attempt(f'lax_weather_{year}',lambda year=year:weather(year))

def lodes():
 path,rec=s.get('https://lehd.ces.census.gov/data/lodes/LODES8/ca/wac/ca_wac_S000_JT00_2023.csv.gz',max_mb=15)
 frame=pd.read_csv(path,compression='gzip',dtype={'w_geocode':str})
 la=frame[frame.w_geocode.str.startswith('06037')]
 la.to_parquet(stage/'lodes_la_wac_2023.parquet',index=False)
 return {'state_rows':len(frame),'la_county_rows':len(la),'year':2023,'sha256':rec['sha256']}
attempt('lodes',lodes)

def metro():
 obj,rec=s.json('https://api.metro.net/openapi.json')
 (stage/'metro_openapi.json').write_text(json.dumps(obj,indent=2),encoding='utf8')
 return {'paths':list(obj.get('paths',{})),'retrieved_at_utc':rec['retrieved_at_utc']}
attempt('metro_schema',metro)
