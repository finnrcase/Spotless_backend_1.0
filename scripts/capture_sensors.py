"""One bounded public poll, status, or independent reviewed bay comparison."""
import argparse,json
from pathlib import Path
from la_parking.sensor_capture import Capture,poll,compare_manual
p=argparse.ArgumentParser();p.add_argument('command',choices=['poll','status','compare','release']);p.add_argument('--quarantine',action='store_true');p.add_argument('--directory',default='data/observations/sensor_capture');p.add_argument('--observations');p.add_argument('--reviews');p.add_argument('--poll-id');p.add_argument('--lock',default='reports/modeling/spatial_v3_locked_models.json');a=p.parse_args()
if a.command=='poll':r=poll(a.directory,a.quarantine)
else:
    c=Capture(a.directory)
    if a.command=='status':r=c.status()
    elif a.command=='release':r=c.release_for_locked_evaluation(a.poll_id,a.lock)
    else:
        import pandas as pd
        observations=pd.read_parquet(a.observations).to_dict('records') if a.observations else []
        reviews=pd.read_csv(a.reviews) if a.reviews else pd.DataFrame(columns=['observation_id','space_id','reviewed'])
        approved=set(map(tuple,reviews.loc[reviews.reviewed.eq(True),['observation_id','space_id']].to_numpy()))
        r=compare_manual(c,observations,approved)
    c.close()
print(json.dumps(r,indent=2))
