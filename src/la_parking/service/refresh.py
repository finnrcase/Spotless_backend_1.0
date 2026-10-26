"""Snapshot checks, source polling and forecast cache are distinct operations."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import hashlib,json,time
from pathlib import Path
from threading import RLock
import pandas as pd


class ForecastCache:
    def __init__(self,ttl=60,maximum=128):self.ttl=ttl;self.maximum=maximum;self.entries={};self.lock=RLock()
    def key(self,request,issue,revision,version):
        canonical={'request':request.model_dump(mode='json'),'issue':issue.isoformat(),'revision':revision,'model':version}
        # Live requests share a one-minute computation origin, but actual issuance remains in the stored response.
        if request.mode=='live':canonical['issue']=issue.replace(second=0,microsecond=0).isoformat()
        return hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    def get(self,key):
        with self.lock:
            value=self.entries.get(key)
            if value and time.monotonic()-value[0]<self.ttl:return deepcopy(value[1])
            self.entries.pop(key,None);return None
    def put(self,key,response):
        with self.lock:
            if len(self.entries)>=self.maximum:self.entries.pop(next(iter(self.entries)))
            self.entries[key]=(time.monotonic(),deepcopy(response))
    def clear(self):
        with self.lock:n=len(self.entries);self.entries.clear();return n


class RefreshManager:
    def __init__(self,repo,cache):
        self.repo=repo;self.cache=cache;self.last_check=0;self.last_feature_check=None
    def check(self,force=False):
        now=datetime.now(timezone.utc)
        if not force and time.monotonic()-self.last_check<self.repo.config['snapshot_check_seconds']:return False,0
        self.last_check=time.monotonic();self.last_feature_check=now.isoformat()
        if self.repo.fingerprint()!=self.repo.revision:
            self.repo.reload_snapshots();return True,self.cache.clear()
        return False,0
    def poll_source(self):
        """Explicit opt-in bounded official current-feed poll. Never trains or fabricates feature windows."""
        from ..http import Store
        from ..connectors import socrata
        from ..build import normalize_events
        from ..sources import DATASETS
        r=self.repo;now=datetime.now(timezone.utc).isoformat()
        status={'last_poll_attempt':now,'last_poll_success':r.source_state.get('last_poll_success'),'last_poll_error':None}
        from ..sensor_capture import protected_period
        if protected_period(now):
            status.update(holdout_guard=True,source_poll_performed=False,message='Reserved evaluation period: current sensor outcomes were not fetched or applied. Use the separate quarantined capture workflow to preserve a blind snapshot.')
            return False,0,status
        try:
            store=Store(root=r.root/'data',refresh=True)
            frame=socrata(store,DATASETS['occupancy'],max_rows=20000)
            clean,rejected,duplicates=normalize_events(frame,'ladot_current',now)
            if len(rejected) or not len(clean):raise ValueError('Current poll failed source validation')
            clean['age_seconds']=(pd.Timestamp(now)-clean.observed_at_utc).dt.total_seconds();clean['stale']=clean.age_seconds>900
            path=r.root/'data/processed/city_current_occupancy.parquet';temp=path.with_suffix('.incoming.parquet');clean.to_parquet(temp,index=False);temp.replace(path)
            status['last_poll_success']=now
        except Exception as exc:status['last_poll_error']=str(exc)
        path=r.root/'data/service/poll_status.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(status,indent=2),encoding='utf8')
        changed,cleared=self.check(force=True)
        return changed,cleared,status
