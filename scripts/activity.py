"""Verified calendar, NOAA mirror and Metro requests; no paid services."""
import json
from pathlib import Path
import zipfile
import pandas as pd
from la_parking.http import Store
s=Store(); stage=Path('data/staged'); result={}
def attempt(name,fn):
 try: result[name]={'status':'verified/downloaded','result':fn()}
 except Exception as exc: result[name]={'status':'blocked','error':str(exc)}; print(name,exc,flush=True)
 Path('reports/activity_status.json').write_text(json.dumps(result,indent=2),encoding='utf8')

for year in [2025,2026]:
 def weather(year=year):
  path,rec=s.get(f'https://noaa-global-hourly-pds.s3.amazonaws.com/{year}/72295023174.csv',max_mb=20)
  frame=pd.read_csv(path,dtype=str); frame.to_parquet(stage/f'lax_weather_{year}.parquet',index=False)
  return {'rows':len(frame),'min_date':str(frame.DATE.min()),'max_date':str(frame.DATE.max()),'sha256':rec['sha256']}
 attempt(f'lax_weather_{year}',weather)

def calendar():
 path,rec=s.get('https://registrar.ucla.edu/file/fa0541df-37fc-4e16-9041-f217b8317c22',max_mb=2)
 text=path.read_text(encoding='utf-8-sig')
 if 'BEGIN:VCALENDAR' not in text: raise ValueError('Not an ICS calendar')
 (stage/'ucla_2026_27.ics').write_text(text,encoding='utf8')
 return {'events':text.count('BEGIN:VEVENT'),'sha256':rec['sha256']}
attempt('ucla_calendar',calendar)

def gtfs():
 path,rec=s.get('https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip',max_mb=20)
 with zipfile.ZipFile(path) as z:
  # Read only known entries, never extract arbitrary archive paths.
  info=pd.read_csv(z.open('feed_info.txt'),dtype=str).fillna('')
  cal=pd.read_csv(z.open('calendar.txt'),dtype=str)
  cal.to_parquet(stage/'metro_rail_calendar.parquet',index=False)
  stops=pd.read_csv(z.open('stops.txt'))
  stops.to_parquet(stage/'metro_rail_stops.parquet',index=False)
  info.to_parquet(stage/'metro_rail_feed_info.parquet',index=False)
 return {'stops':len(stops),'feed_info':info.to_dict('records'),'calendar_min':cal.start_date.min(),'calendar_max':cal.end_date.max(),'sha256':rec['sha256']}
attempt('metro_rail_gtfs',gtfs)

def metro():
 schema=json.loads((stage/'metro_openapi.json').read_text())
 path='/canceled_service/all'
 if path not in schema['paths']: raise ValueError('Documented path not present')
 obj,rec=s.json('https://api.metro.net'+path)
 (stage/'metro_canceled_service.json').write_text(json.dumps(obj,indent=2),encoding='utf8')
 return {'response_type':type(obj).__name__,'retrieved_at_utc':rec['retrieved_at_utc']}
attempt('metro_canceled_service',metro)
