"""Small metadata probes; no bulk exports."""
from pathlib import Path
import json
import requests

OUT = Path('data/discovery')
OUT.mkdir(parents=True, exist_ok=True)
urls = {
 'occupancy': 'https://data.lacity.org/api/views/e7h6-4a3e.json',
 'history': 'https://data.lacity.org/api/views/cj8s-ivry.json',
 'meters': 'https://data.lacity.org/api/views/s49e-q6j2.json',
 'sweeping': 'https://data.lacity.org/api/views/krk7-ayq2.json',
 'permits': 'https://data.lacity.org/api/views/s3st-6nwi.json',
 'signs': 'https://data.lacity.org/api/views/jp2s-nfz4.json',
 'business': 'https://data.lacity.org/api/views/6rrh-rzua.json',
 'navigate': 'https://maps.lacity.org/arcgis/rest/services/Mapping/NavigateLA/MapServer?f=json',
 'streets': 'https://lacitydbs.org/arcgiswebad/rest/services/SDE_IntersectionFinder/MapServer?f=json',
 'lighting_streets': 'https://portald1.lalightsaws.lacity.org/server/rest/services/LABureauOfStreetLighting032923/FeatureServer/0?f=json',
}
for name, url in urls.items():
 try:
  r=requests.get(url,timeout=45); r.raise_for_status(); obj=r.json()
  (OUT/f'{name}.json').write_text(json.dumps(obj,indent=2),encoding='utf8')
  print(name, obj.get('name'), 'updated',obj.get('rowsUpdatedAt'), 'license',obj.get('license'), flush=True)
  print(' columns',[(c.get('fieldName'),c.get('dataTypeName')) for c in obj.get('columns',[])],flush=True)
  print(' layers',obj.get('layers'),flush=True)
  if name=='history': print('attachments',obj.get('metadata',{}).get('attachments'),flush=True)
 except Exception as e: print(name,type(e).__name__,str(e),flush=True)
