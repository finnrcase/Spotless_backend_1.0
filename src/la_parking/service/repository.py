"""Local geometry, routing and snapshot access; no training or remote calls."""
import hashlib
import heapq
import json
from pathlib import Path
from threading import RLock
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from ..spatial import METRIC_CRS


class Repository:
    def __init__(self,root,observations_dir=None):
        self.root=Path(root);p=self.root/'data/processed'
        self.streets=gpd.read_parquet(p/'street_segments.parquet').to_crs(METRIC_CRS).set_index('segment_id',drop=False)
        self.faces=gpd.read_parquet(p/'block_faces.parquet').to_crs(METRIC_CRS).set_index('block_face_id',drop=False)
        self.geographic_faces=self.faces.to_crs(4326)
        self.boundary=gpd.read_parquet(p/'city_boundary.parquet').to_crs(METRIC_CRS).geometry.union_all()
        self.mapping=pd.read_parquet(p/'meter_face_mapping.parquet').query("join_status=='matched'")
        self.meters=pd.read_parquet(p/'pilot_meters.parquet').drop(columns='geometry').merge(self.mapping,left_on='spaceid',right_on='space_id')
        self.config=json.loads((self.root/'config/service.json').read_text())
        self.rules_path=self.root/self.config['restrictions_path']
        self.observations_dir=Path(observations_dir or self.root/'data/observations')
        self.lock=RLock();self.rules=[];self.rule_coverage=[];self.rule_load_error=None
        self.current=pd.DataFrame();self.design=None;self.context=None;self.historical=None;self.model_cache={}
        self.graph=None;self.revision='';self.source_state={};self.reload_snapshots()

    @staticmethod
    def point(lat,lon):return gpd.GeoSeries([Point(lon,lat)],crs=4326).to_crs(METRIC_CRS).iloc[0]

    def fingerprint(self):
        paths=[self.root/'data/processed/city_current_occupancy.parquet',self.rules_path,self.observations_dir/'manual_observations.parquet',
               self.root/'data/modeling/design.parquet',self.root/'artifacts/models/catalog.json',self.root/'data/service/poll_status.json']
        paths+=list((self.root/'artifacts/models').glob('*.joblib'))
        return hashlib.sha256('|'.join(f'{p}:{p.stat().st_mtime_ns}:{p.stat().st_size}' if p.exists() else f'{p}:missing' for p in sorted(paths)).encode()).hexdigest()[:20]

    def reload_snapshots(self):
        with self.lock:
            self.rule_load_error=None;self.rules=[];self.rule_coverage=[]
            if self.rules_path.exists():
                try:
                    from .schemas import RestrictionRecord,RuleCoverage
                    obj=json.loads(self.rules_path.read_text(encoding='utf8'))
                    self.rules=[RestrictionRecord.model_validate(x).model_dump(mode='json') for x in obj.get('rules',[])]
                    self.rule_coverage=[RuleCoverage.model_validate(x).model_dump(mode='json') for x in obj.get('coverage',[])]
                except Exception as exc:self.rules=[];self.rule_coverage=[];self.rule_load_error=f'Rule snapshot rejected: {exc}'
            path=self.root/'data/processed/city_current_occupancy.parquet'
            self.current=pd.read_parquet(path) if path.exists() else pd.DataFrame()
            manual=self.observations_dir/'manual_observations.parquet'
            self.manual=pd.read_parquet(manual) if manual.exists() else pd.DataFrame()
            if len(self.manual):
                self.manual['survey_end_utc']=pd.to_datetime(self.manual.survey_end_utc,utc=True)
                self.manual['retrieved_at_utc']=pd.to_datetime(self.manual.retrieved_at_utc,utc=True)
            self.source_state={'current_feed_present':path.exists(),'last_poll_attempt':None,'last_poll_success':None,'last_poll_error':None,
                'latest_source_observation':self.current.observed_at_utc.max().isoformat() if len(self.current) else None,
                'source_snapshot_retrieved_at':self.current.retrieved_at_utc.max().isoformat() if len(self.current) else None}
            self.source_state['newest_manual_observation']=self.manual.survey_end_utc.max().isoformat() if len(self.manual) else None
            status=self.root/'data/service/poll_status.json'
            if status.exists():self.source_state.update(json.loads(status.read_text()))
            self.design=None;self.context=None;self.historical=None;self.model_cache={};self.revision=self.fingerprint()

    def load_model_data(self):
        with self.lock:
            if self.design is None:
                import pyarrow.parquet as pq
                from ..model_features import CALENDAR,HISTORY,CONTEXT
                path=self.root/'data/modeling/design.parquet'
                if not path.exists():return False
                wanted=set(CALENDAR+HISTORY+CONTEXT+['block_face_id','block_id','issued_at_utc','arrival_time_utc','horizon_minutes','panel_sensor_count','area','neighbor_all_300','neighbor_all_600','neighbor_train_only_300','neighbor_train_only_600'])
                columns=sorted(wanted&set(pq.read_schema(path).names))
                self.design=pd.read_parquet(path,columns=columns,filters=[('horizon_minutes','==',0)])
                c=self.root/'data/modeling/current_context.parquet';self.context=pd.read_parquet(c) if c.exists() else pd.DataFrame()
                frames=[pd.read_parquet(p,columns=['space_id','observed_at_utc','state']) for p in (self.root/'data/processed').glob('pilot_history_20*.parquet')]
                self.historical=pd.concat(frames,ignore_index=True).merge(self.mapping[['space_id','block_face_id']],on='space_id',how='inner') if frames else pd.DataFrame(columns=['space_id','block_face_id','observed_at_utc','state'])
            return True

    def model(self,path):
        import joblib
        with self.lock:
            key=str(path)
            if key not in self.model_cache:self.model_cache[key]=joblib.load(self.root/path)
            return self.model_cache[key]

    def search(self,text,limit=12):
        q=text.strip().upper()
        if len(q)<2:return []
        found=self.streets.loc[self.streets.street_name.str.contains(q,case=False,regex=False,na=False)]
        output=[]
        for name,group in found.groupby('street_name'):
            row=group.iloc[0];point=gpd.GeoSeries([row.geometry.interpolate(.5,normalized=True)],crs=METRIC_CRS).to_crs(4326).iloc[0]
            output.append({'label':name+' · approximate street segment center','latitude':point.y,'longitude':point.x,'segment_id':row.segment_id})
            if len(output)>=limit:break
        return output

    def build_graph(self):
        if self.graph is not None:return
        graph={};ends={}
        def node(p):return (round(p[0]/2),round(p[1]/2))
        for r in self.streets.itertuples(index=False):
            if any(s in str(r.street_designation).lower() for s in ['private','freeway','ramp','paper street']):continue
            coords=list(r.geometry.coords);a,b=node(coords[0]),node(coords[-1]);length=r.geometry.length
            graph.setdefault(a,[]).append((b,length));graph.setdefault(b,[]).append((a,length));ends[r.segment_id]=(a,b)
        self.graph=graph;self.ends=ends

    def nearby(self,location,maximum,limit=120):
        point=self.point(location.latitude,location.longitude)
        if not self.boundary.covers(point):return [],False,False
        self.build_graph()
        ix=self.streets.sindex.query(point.buffer(150),predicate='intersects')
        nearest=self.streets.iloc[ix]
        nearest=nearest.loc[nearest.segment_id.isin(self.ends)]
        if not len(nearest):return [],True,False
        distances=nearest.geometry.distance(point);origin=nearest.loc[distances.idxmin()]
        offset=float(origin.geometry.distance(point));along=origin.geometry.project(point)
        a,b=self.ends[origin.segment_id];queue=[(offset+along,a),(offset+origin.geometry.length-along,b)];heapq.heapify(queue);reached={}
        while queue:
            distance,node=heapq.heappop(queue)
            if distance>maximum+200 or distance>=reached.get(node,float('inf')):continue
            reached[node]=distance
            for other,length in self.graph.get(node,[]):
                if distance+length<reached.get(other,float('inf')):heapq.heappush(queue,(distance+length,other))
        ix=self.faces.sindex.query(point.buffer(maximum),predicate='intersects');candidates=self.faces.iloc[ix]
        output=[]
        for r in candidates.itertuples(index=False):
            if r.segment_id not in self.ends:continue
            straight=float(r.geometry.distance(point))
            if straight>maximum:continue
            line=self.streets.loc[r.segment_id].geometry;projection=line.project(point);anchor=line.interpolate(projection)
            side_offset=float(r.geometry.distance(anchor));a,b=self.ends[r.segment_id]
            distance=min(reached.get(a,float('inf'))+projection,reached.get(b,float('inf'))+line.length-projection)+side_offset
            if r.segment_id==origin.segment_id:distance=min(distance,offset+abs(projection-along)+side_offset)
            if distance>maximum:continue
            output.append({'face':r,'straight':straight,'walking':float(distance)})
        output.sort(key=lambda x:x['walking']);truncated=len(output)>limit
        return output[:limit],True,truncated

    def price(self,face_id,preference,arrival=None):
        import re
        m=self.meters.loc[self.meters.block_face_id==face_id]
        values=[]
        for v in m.raterange:
            values.extend(float(n) for n in re.findall(r'\d+(?:\.\d+)?',str(v)))
        low,high=(min(values),max(values)) if values else (None,None)
        return {'minimum_published_hourly':low,'maximum_published_hourly':high,'preference_status':'unknown' if high is None else 'above_preference' if preference is not None and low>preference else 'possibly_within_preference',
                'source':'October 2026 meter-policy snapshot; not a verified arrival-time quote','historical_vintage_matches':False,'ranking_price':high}
