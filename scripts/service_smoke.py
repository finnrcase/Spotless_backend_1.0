"""Exercise the real local API without writing synthetic observations."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,time
from fastapi.testclient import TestClient
from la_parking.service.api import create_app

out=Path('reports/service');out.mkdir(exist_ok=True)
with TestClient(create_app(background=False)) as client:
    (out/'openapi.json').write_text(json.dumps(client.get('/openapi.json').json(),indent=2),encoding='utf8')
    query={'destination':{'latitude':34.0608,'longitude':-118.4465},'arrival_time':'2026-08-25T17:00:00Z','intended_stay_minutes':60,'maximum_walking_distance_m':400,
           'eligibility':{'vehicle_class':'standard_passenger','permit_class':None},'mode':'historical_replay','replay_issue_time':'2026-08-25T17:00:00Z','include_experimental':True}
    (out/'example_request_replay.json').write_text(json.dumps(query,indent=2),encoding='utf8')
    start=time.monotonic();r=client.post('/api/predictions',json=query);print('status',r.status_code,'seconds',time.monotonic()-start,flush=True)
    if r.status_code!=200:raise RuntimeError(r.text)
    data=r.json();(out/'example_replay.json').write_text(json.dumps(data,indent=2),encoding='utf8')
    print('blocks',len(data['blocks']),'statuses',sorted(set(b['visual_status'] for b in data['blocks'])),flush=True)
    second=client.post('/api/predictions',json=query).json();assert second['cache_hit']
    query['mode']='live';query.pop('replay_issue_time');query['arrival_time']=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat();query['include_experimental']=False
    (out/'example_request_live.json').write_text(json.dumps(query,indent=2),encoding='utf8')
    live=client.post('/api/predictions',json=query);assert live.status_code==200,live.text
    (out/'example_live.json').write_text(json.dumps(live.json(),indent=2),encoding='utf8')
    (out/'health.json').write_text(json.dumps(client.get('/api/health').json(),indent=2),encoding='utf8')
