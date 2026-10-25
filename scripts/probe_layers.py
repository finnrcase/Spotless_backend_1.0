from pathlib import Path
import json
from la_parking.http import Store
from la_parking.sources import NAV, STREETS
s=Store()
for ident in [341,414,324,325,107,177,157,431,393,399,75,1,212]:
 try:
  obj,_=s.json(f'{NAV}/{ident}',{'f':'json'})
  Path(f'data/discovery/nav_{ident}.json').write_text(json.dumps(obj,indent=2),encoding='utf8')
  print(ident,obj.get('name'),'fields',[(f['name'],f.get('domain')) for f in obj.get('fields',[])],flush=True)
  sample,_=s.json(f'{NAV}/{ident}/query',{'f':'geojson','where':'1=1','outFields':'*','outSR':4326,'resultRecordCount':1})
  print('sample',str(sample)[:1800],flush=True)
 except Exception as e: print(ident,str(e),flush=True)
