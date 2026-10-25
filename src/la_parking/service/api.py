"""FastAPI local application. Training and acquisition are never import side effects."""
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
import asyncio
import json
import tempfile
from threading import RLock
import pandas as pd
from fastapi import FastAPI,Request,HTTPException,Query
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from shapely.geometry import mapping
from .schemas import PredictionRequest,PredictionResponse,BlockForecast,ObservationBatch,RefreshResponse
from .repository import Repository
from .inference import Inference
from .refresh import ForecastCache,RefreshManager
from .eligibility import evaluate,resolve_local
from ..observations import ingest

UTC=timezone.utc


class Service:
    def __init__(self,repo,clock=None):
        self.repo=repo;self.clock=clock or (lambda:datetime.now(UTC));self.cache=ForecastCache(repo.config['forecast_cache_seconds'],repo.config['maximum_cache_entries'])
        self.refresh=RefreshManager(repo,self.cache);self.inference=Inference(repo);self.write_lock=RLock()

    def predict(self,query:PredictionRequest):
        with self.repo.lock:return self._predict(query)

    def _predict(self,query:PredictionRequest):
        self.refresh.check();computed=self.clock().astimezone(UTC)
        issue=query.replay_issue_time if query.mode=='historical_replay' else computed
        if query.arrival_time<issue:raise ValueError('Arrival is before the current issue time; choose a future arrival or explicit historical replay')
        key=self.cache.key(query,issue,self.repo.revision,self.repo.config['model_version']);cached=self.cache.get(key)
        if cached:
            cached['cache_hit']=True;cached['response_at']=computed.isoformat();return PredictionResponse.model_validate(cached)
        nearby,in_city,truncated=self.repo.nearby(query.destination,query.maximum_walking_distance_m,self.repo.config['maximum_candidates'])
        blocks=[];replay=query.mode=='historical_replay'
        for candidate in nearby:
            face=candidate['face'];face_id=face.block_face_id
            rules=evaluate(face_id,query.arrival_time,query.intended_stay_minutes,query.eligibility.model_dump(),self.repo.rules,self.repo.rule_coverage,issue)
            evidence=self.inference.evidence(face_id,issue,replay)
            panel,prior,inference=self.inference.estimate(face_id,issue,query.arrival_time,query.intended_stay_minutes,query.eligibility.model_dump(),query.include_experimental,replay)
            price=self.repo.price(face_id,query.maximum_price_per_hour,query.arrival_time)
            if rules.status=='prohibited':visual='known_restriction'
            elif prior is not None:visual='experimental_extrapolation'
            elif panel is not None:visual='model_estimate'
            elif evidence['status']=='recent':visual='observed_recent'
            else:visual='insufficient_data'
            reason='Eligible availability is unsupported; ranked by estimated walking distance and optional indicative price'
            item=BlockForecast(block_face_id=face_id,street_name=self.repo.streets.loc[face.segment_id].street_name,
                geometry=mapping(self.repo.geographic_faces.loc[face_id].geometry.simplify(.000005)),geometry_method=face.geometry_method,
                straight_line_distance_m=candidate['straight'],walking_distance_m=candidate['walking'],rank_reason=reason,visual_status=visual,eligibility=rules,
                panel_estimate=panel,experimental_activity_rank=prior,evidence={**evidence,'fresh_computation_at':computed.isoformat(),'feature_origin_at':inference.get('feature_origin_at'),
                    'inference_status':inference['status'],'model_mode':inference.get('model_mode'),'historical_geometry_verified':False,'mode':query.mode},
                uncertainty={'rules':rules.reason,'capacity':'Total physical and eligible capacity unknown','model':inference.get('model_uncertainty',{'status':'unavailable or unvalidated'}),
                    'physical_curb_assets':'Historic 2017 inventory from 2014 imagery; not parking stalls or verified current supply',
                    'posted_sign_verification_is_independent':True},price=price,unavailable_reason=inference.get('reason'))
            blocks.append(item)
        # Never rank a demand rank or panel probability as suitable-space probability.
        def rank(b):
            restriction={'allowed':0,'unknown':1,'conflict':2,'prohibited':3}[b.eligibility.status]
            supported=b.probability_at_least_one_suitable
            price=b.price.get('ranking_price')
            preference_bad=b.price.get('preference_status')=='above_preference'
            return (restriction,0 if supported is not None else 1,-(supported or 0),int(preference_bad),
                price if query.prefer_lower_price and price is not None else float('inf') if query.prefer_lower_price else 0,b.walking_distance_m or float('inf'))
        blocks.sort(key=rank)
        for n,b in enumerate(blocks,1):b.rank=n
        result=PredictionResponse(request=query,forecast_issued_at=issue,computed_at=computed,response_at=computed,arrival_time=query.arrival_time,
            intended_stay_end=query.arrival_time+timedelta(minutes=query.intended_stay_minutes),model_version=self.repo.config['model_version'],cache_hit=False,cache_key=key,data_revision=self.repo.revision,
            mode_label='HISTORICAL REPLAY — real archived observations, not live parking' if replay else 'LIVE REQUEST — evidence may be old or missing',blocks=blocks,
            coverage={'inside_city':in_city,'nearby_faces_returned':len(blocks),'candidate_limit_reached':truncated,'known_rule_prohibitions':sum(b.eligibility.status=='prohibited' for b in blocks),
                'unknown_or_conflicting_eligibility':sum(b.eligibility.status in ['unknown','conflict'] for b in blocks),'numerical_suitable_space_estimates':0,
                'all_city_predictions_validated':False,'outside_city_reason':None if in_city else 'Destination is outside the City of Los Angeles boundary'},
            refresh={'source':self.repo.source_state,'snapshot_checked_at':self.refresh.last_feature_check,'feature_updates':'File revisions reload independently; current transaction polls do not rebuild historical feature windows',
                'forecast_cache_seconds':self.repo.config['forecast_cache_seconds'],'client_refresh':'Client may request refreshed results; that does not make the source evidence fresh'},
            limitations=['Experimental panel counts/probabilities do not describe full-curb or legally suitable parking.',
                'Unknown rules remain unknown throughout the requested stay. Verify posted signs separately.',
                'Walking distances use centerlines; pedestrian access, crossings and accessibility are unverified.',
                'Price ranges come from a later snapshot, not an arrival-time quote. No validated search-time model exists.'])
        self.cache.put(key,result.model_dump(mode='json'));return result


def create_app(repository=None,clock=None,observations_dir=None,background=True):
    root=Path(__file__).resolve().parents[3]
    @asynccontextmanager
    async def lifespan(app):
        if app.state.service is None:app.state.service=Service(Repository(root,observations_dir),clock)
        async def monitor():
            last_poll=0.
            while True:
                await asyncio.sleep(app.state.service.repo.config['snapshot_check_seconds'])
                svc=app.state.service;await asyncio.to_thread(svc.refresh.check,True)
                if svc.repo.config['source_poll_enabled']:
                    import time
                    if time.monotonic()-last_poll>=svc.repo.config['source_poll_seconds']:
                        await asyncio.to_thread(svc.refresh.poll_source);last_poll=time.monotonic()
        task=asyncio.create_task(monitor()) if background else None
        try:yield
        finally:
            if task:
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
    app=FastAPI(title='Spotless local parking API',version='0.2.0',description='Local City of Los Angeles discovery, full-stay rule checks and experimental sensor-panel forecasts. Unsupported suitability values stay null.',lifespan=lifespan)
    app.state.service=Service(repository,clock) if repository else None
    def service():
        if app.state.service is None:raise HTTPException(503,'Local datasets have not loaded')
        return app.state.service

    @app.middleware('http')
    async def local_writes_only(request,call_next):
        origin=request.headers.get('origin')
        if request.method=='POST' and origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'Cross-origin writes are disabled on this local service'},status_code=403)
        return await call_next(request)

    @app.get('/api/health')
    def health():
        s=service();s.refresh.check()
        newest=s.repo.source_state.get('latest_source_observation')
        age=(pd.Timestamp(s.clock())-pd.Timestamp(newest)).total_seconds()/60 if newest else None
        return {'status':'degraded' if age is None or age>15 or s.repo.rule_load_error or s.repo.source_state.get('last_poll_error') else 'ready_with_data_gaps','data_revision':s.repo.revision,'sources':s.repo.source_state,'newest_observation_age_minutes':age,
            'rule_load_error':s.repo.rule_load_error,'rules_available':len(s.repo.rules),'model_version':s.repo.config['model_version'],'validated_suitability':False}

    @app.get('/api/config')
    def configuration():
        s=service()
        return {'timezone':'America/Los_Angeles','default_destination':{'latitude':34.0608,'longitude':-118.4465,'label':'Westwood pilot center (approximate)'},
            'replay_issue_time':s.repo.config['replay_issue_utc'],'server_now':s.clock().isoformat(),'horizons':[0,15,30,60,120],
            'source_poll_enabled':s.repo.config['source_poll_enabled'],'client_refresh_seconds':60}

    @app.get('/api/destinations')
    def destinations(q:str=Query(min_length=2,max_length=100)):return {'matches':service().repo.search(q)}

    @app.get('/api/time/resolve')
    def resolve(local_time:str,fold:int|None=None):
        try:value=resolve_local(local_time,fold)
        except ValueError as exc:raise HTTPException(422,str(exc))
        return {'utc':value.isoformat(),'timezone':'America/Los_Angeles','fold':fold}

    @app.post('/api/predictions',response_model=PredictionResponse)
    def predict(query:PredictionRequest):
        try:return service().predict(query)
        except ValueError as exc:raise HTTPException(422,str(exc))

    @app.get('/api/streets')
    def streets(latitude:float,longitude:float,radius_m:int=Query(default=900,ge=100,le=3000)):
        r=service().repo;p=r.point(latitude,longitude);ix=r.streets.sindex.query(p.buffer(radius_m),predicate='intersects')
        frame=r.streets.iloc[ix][['segment_id','street_name','geometry']].to_crs(4326)
        if len(frame)>1800:raise HTTPException(422,'Too many street features; use a smaller map radius')
        return json.loads(frame.to_json(drop_id=True))

    @app.get('/api/observations/template')
    def observation_template(face_id:str):
        r=service().repo
        if face_id not in r.faces.index:raise HTTPException(404,'Unknown face')
        pt=r.geographic_faces.loc[face_id].geometry.representative_point()
        return {'block_face_id':face_id,'latitude':pt.y,'longitude':pt.x,'location_method':'confirmed_map_pin','gps_accuracy_m':None,
            'review_required':True,'message':'Confirm this side and its limits in person; the pin is an assumed location, not GPS.'}

    @app.post('/api/observations')
    def observations(batch:ObservationBatch):
        s=service();directory=s.repo.observations_dir;directory.mkdir(parents=True,exist_ok=True)
        with s.write_lock:
            # Body is bounded by record count and serialized bytes; temporary import stays in the observation workspace.
            body=''.join(json.dumps(r)+'\n' for r in batch.records)
            if len(body.encode())>2_000_000:raise HTTPException(413,'Observation batch exceeds 2 MB')
            with tempfile.TemporaryDirectory(dir=directory) as temp:
                path=Path(temp)/'import.jsonl';path.write_text(body,encoding='utf8')
                result=ingest(path,inventory_path=s.repo.root/'data/processed/block_faces.parquet',output=directory)
            changed,cleared=s.refresh.check(force=True)
        return {**result,'data_revision':s.repo.revision,'cache_entries_cleared':cleared,'automatic_training':False,'posted_sign_rules_automatically_verified':False}

    @app.post('/api/refresh',response_model=RefreshResponse)
    def refresh(poll_source:bool=False):
        s=service()
        if poll_source:
            changed,cleared,status=s.refresh.poll_source();message='Official source poll attempted; evidence timestamps and feature support remain independent'
        else:changed,cleared=s.refresh.check(force=True);message='Local snapshots checked; no network poll or training performed'
        return RefreshResponse(checked_at=s.clock(),changed=changed,data_revision=s.repo.revision,cache_entries_cleared=cleared,source_poll_performed=poll_source,message=message)

    @app.get('/collector',include_in_schema=False)
    @app.get('/collector.html',include_in_schema=False)
    def collector():return FileResponse(root/'reports/collector.html')

    @app.get('/field-route',include_in_schema=False)
    def field_route():return FileResponse(root/'reports/field_route.html')

    @app.get('/imagery',include_in_schema=False)
    def imagery():return RedirectResponse('/imagery/annotator.html')

    app.mount('/imagery',StaticFiles(directory=root/'reports/imagery',check_dir=False),name='historic-imagery')

    app.mount('/assets',StaticFiles(directory=root/'web/map'),name='map-assets')
    @app.get('/',include_in_schema=False)
    def index():return FileResponse(root/'web/map/index.html')
    from fastapi.openapi.utils import get_openapi
    from ..contracts import ManualObservation
    from .schemas import RestrictionRecord,RuleCoverage
    def openapi_contract():
        if app.openapi_schema:return app.openapi_schema
        schema=get_openapi(title=app.title,version=app.version,description=app.description,routes=app.routes)
        manual=ManualObservation.model_json_schema(ref_template='#/components/schemas/{model}')
        components=schema.setdefault('components',{}).setdefault('schemas',{})
        for name,definition in manual.pop('$defs',{}).items():components.setdefault(name,definition)
        components['ManualObservation']=manual
        for cls in [RestrictionRecord,RuleCoverage]:components[cls.__name__]=cls.model_json_schema()
        components['ObservationBatch']['properties']['records']['items']={'$ref':'#/components/schemas/ManualObservation'}
        schema['info']['description']+=' Observation imports validate each record and return per-line accepted/rejected results. Example responses in reports/service are from real local datasets; synthetic fixtures stay in temporary tests.'
        app.openapi_schema=schema;return schema
    app.openapi=openapi_contract
    return app


app=create_app()
