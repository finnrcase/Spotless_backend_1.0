"""Bounded Westwood public context. Schedules/listings are not occupancy truth."""
import hashlib,html,json,re
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
from .http import Store,utcnow
from .connectors import arcgis

ROOT=Path('data/westwood_context')


class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.links=[];self.ics=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and a.get('href'):self.links.append(a['href'])
        call=a.get('onclick','')
        if call.startswith('downloadIcsFile(') and call.endswith(')'):
            self.ics.append(json.loads(call[len('downloadIcsFile('):-1])['content'])


def ics_event(text):
    text=re.sub(r'\r?\n[ \t]','',text);values={}
    for line in text.splitlines():
        name,sep,value=line.partition(':')
        if sep:values[name.split(';')[0]]=value.replace('\\,',',').replace('\\n','\n')
    def utc(key):
        v=values.get(key)
        return datetime.strptime(v,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat() if v and re.fullmatch(r'\d{8}T\d{6}Z',v) else None
    latitude=longitude=None
    if values.get('GEO'):
        latitude,longitude=map(float,values['GEO'].split(';'))
    return {'event_id':values.get('UID'),'title':values.get('SUMMARY'),'start_utc':utc('DTSTART'),'end_utc':utc('DTEND'),
        'ics_dtstamp_utc':utc('DTSTAMP'),'dtstamp_semantics':'ICS DTSTAMP is not independently verified publication/modification time','status':values.get('STATUS'),'location_text':values.get('LOCATION'),
        'latitude':latitude,'longitude':longitude,'time_precision':'explicit_utc' if utc('DTSTART') else 'unresolved',
        'geolocation_status':'source_geo' if latitude is not None else 'unavailable_no_geocoding_or_campus_centroid_substitution'}


def listing_event(row,bbox):
    m=row.get('meta',{});get=lambda n:m.get('vibemap_event_'+n)
    def number(value):
        try:return float(value) if value not in [None,''] else None
        except (ValueError,TypeError):return None
    lat=number(get('latitude'));lon=number(get('longitude'));west,south,east,north=bbox
    valid=lat is not None and lon is not None and south<=lat<=north and west<=lon<=east
    tags={t.get('slug','') for t in row.get('tags',[])}
    def when(key):
        value=get(key)
        if not value:return None
        t=pd.Timestamp(value)
        # Naive provider dates are retained; geography does not prove timezone.
        return t.tz_convert('UTC').isoformat() if t.tzinfo else None
    return {'event_id':str(row['id']),'title':html.unescape(row.get('title','')),'url':row.get('permalink'),
        'latitude':lat if valid else None,'longitude':lon if valid else None,'inside_pilot_bbox':valid,
        'start_raw':get('start_date'),'end_raw':get('end_date'),'start_utc':when('start_date'),'end_utc':when('end_date'),
        'time_precision':'explicit_offset' if when('start_date') else 'provider_wall_time_timezone_unverified',
        'provider_updated_raw':get('updated_at'),'venue_name':get('venue_name'),'venue_address':get('venue_address'),
        'recurrence_raw':get('recurrence'),'listing_quality':'provider_predicted_recurring' if 'events_feed_predicted' in tags else 'listing_not_independently_confirmed',
        'attendance':None,'occupancy_label':False}


def normalize_sweeping(feature):
    p=feature['properties'];value=p.get('Posted_Time','');match=re.fullmatch(r'\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*-\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*',value,re.I)
    def clock(hour,minute,meridiem):
        if not 1<=int(hour)<=12 or int(minute or 0)>59:raise ValueError('Invalid posted time')
        return f'{int(hour)%12+(12 if meridiem.lower()=="pm" else 0):02d}:{int(minute or 0):02d}'
    start=end=None
    if match:start=clock(*match.groups()[:3]);end=clock(*match.groups()[3:])
    return {'source_record_id':str(p['OBJECTID']),'route':p.get('Route'),'posted_day':p.get('Posted_Day'),'posted_time_raw':value,'weeks_raw':p.get('Weeks'),
        'local_start':start,'local_end':end,'timezone':'America/Los_Angeles','geometry':feature['geometry'],
        'source_last_edited_utc':pd.to_datetime(p['last_edited_date'],unit='ms',utc=True).isoformat() if p.get('last_edited_date') else None,
        'effective_from_utc':None,'effective_to_utc':None,'rule_status':'route_polygon_schedule_candidate_requires_side_sign_and_effective_date_verification',
        'physical_capacity':None,'automatic_eligibility':False}


def normalize_reservation(feature,oid):
    p=feature['properties']
    def date(key):return pd.to_datetime(p[key],unit='ms',utc=True).isoformat() if p.get(key) is not None else None
    return {'source_record_id':str(p[oid]),'reservation_id':str(p.get('PWRS_ID','')),'category':p.get('Category'),'permit_type':p.get('Type'),
        'event_type':p.get('EventType'),'street_name':p.get('StreetName'),'status':p.get('ActiveStatus'),
        'source_entered_utc':date('EnterDate'),'start_date_encoded_utc':date('StartDate'),'end_date_encoded_utc':date('EndDate'),
        'time_precision':'date_only_until_time_and_timezone_semantics_verified','geometry':feature['geometry'],
        'verified_closure':False,'eligible_capacity_effect':None,'note':'Permit/reservation is not proof of a parking-lane closure. Daily hours, curb side and legal effect remain unknown.'}


def acquire(config_path='config/westwood_context.json',refresh=False):
    cfg=json.loads(Path(config_path).read_text());ROOT.mkdir(parents=True,exist_ok=True);s=Store(root=ROOT/'requests',max_mb=6,refresh=refresh)
    report={'generated_at_utc':utcnow(),'version':cfg['version'],'bbox':cfg['bbox'],'sources':{},'occupancy_labels_added':0,'historical_tests_opened':False,'models_promoted':False}
    def save(name,role,fn,terms):
        try:
            records,details=fn();body=json.dumps(records,ensure_ascii=True,allow_nan=False).encode();digest=hashlib.sha256(body).hexdigest()
            folder=ROOT/'normalized'/name;folder.mkdir(parents=True,exist_ok=True);path=folder/(digest+'.json')
            if not path.exists():path.write_bytes(body)
            report['sources'][name]={'status':'acquired','role':role,'rows':len(records),'normalized_sha256':digest,'normalized_path':str(path),'terms':terms,**details}
        except Exception as exc:
            report['sources'][name]={'status':'unavailable','role':role,'blocker':str(exc)[:250],'terms':terms}
    def ucla():
        p,rec=s.get(cfg['ucla_home'],allow_html=True);links=list(dict.fromkeys(Page(p.read_text(encoding='utf8')).links));links=[a for a in links if re.fullmatch(r'/event/[a-f0-9-]+',a)]
        records=[]
        for link in links[:cfg['maximum_ucla_details']]:
            p,r=s.get('https://community.ucla.edu'+link,allow_html=True);ics=Page(p.read_text(encoding='utf8')).ics
            if len(ics)!=1:raise ValueError('UCLA detail no longer contains exactly one downloadable ICS payload')
            row=ics_event(ics[0]);row.update(source_url='https://community.ucla.edu'+link,received_at_utc=r['received_at_utc'],available_at_utc=r['received_at_utc'],raw_sha256=r['sha256']);records.append(row)
        if len({r['event_id'] for r in records})!=len(records):raise ValueError('Duplicate UCLA event UID')
        return records,{'discovered_links':len(links),'detail_budget':cfg['maximum_ucla_details'],'complete_calendar_export':False,
            'geolocated':sum(r['latitude'] is not None for r in records),'timed':sum(r['start_utc'] is not None for r in records),
            'source_url':cfg['ucla_home'],'received_at_utc':rec['received_at_utc'],'availability':'Per-detail completed receipt; current listing never backfilled historically','access':'Public HTML with actual downloadable ICS payload, not a documented catalog API'}
    def westwood():
        fields='id,title,permalink,tags,meta.latitude,meta.longitude,meta.start_date,meta.end_date,meta.updated_at,meta.venue_name,meta.venue_address,meta.recurrence'
        records=[];expected=None;receipts=[];hashes=[]
        for page in range(1,cfg['maximum_event_pages']+1):
            obj,r=s.json(cfg['westwood_events'],{'featured':'true','fields':fields,'per_page':24,'page':page});meta=obj['pagination'];total=int(obj['total_count'])
            if total>cfg['maximum_events'] or int(meta['total_pages'])>cfg['maximum_event_pages']:raise ValueError('Event budget exceeded; no partial export accepted')
            if int(meta['current_page'])!=page or expected is not None and expected!=total:raise ValueError('Event pagination changed or page parameter ignored')
            expected=total;receipts.append(r['received_at_utc']);hashes.append(r['sha256'])
            records.extend(listing_event(row,cfg['bbox']) for row in obj['events'])
            if not meta['has_more']:break
        if len(records)!=expected or len({r['event_id'] for r in records})!=expected:raise ValueError('Incomplete/duplicate Westwood event export')
        for row in records:row.update(received_at_utc=max(receipts),available_at_utc=max(receipts))
        return records,{'source_url':cfg['westwood_events'],'complete_ids_verified':True,'export_scope':'Featured listings only; not every local event',
            'received_at_utc':max(receipts),'raw_sha256':hashes,'geolocated_inside_pilot':sum(r['inside_pilot_bbox'] for r in records),
            'explicit_timezone_rows':sum(r['start_utc'] is not None for r in records),'usable_exact_time_features':sum(r['start_utc'] is not None and r['inside_pilot_bbox'] for r in records)}
    def layer(name,url,normalizer,fields='*',ids=False):
        obj,meta,oid=arcgis(s,url,bbox=cfg['bbox'],max_features=cfg['maximum_rule_features'],batch=50 if ids else 200,out_fields=fields,query_by_ids=ids)
        received=s.last_record['received_at_utc'];rows=[normalizer(f,oid) if name.startswith('pwrs') else normalizer(f) for f in obj['features']]
        for row in rows:row.update(received_at_utc=received,available_at_utc=received)
        return rows,{'source_url':url,'source_layer_name':meta.get('name'),'source_edit_metadata':meta.get('editingInfo'),'received_at_utc':received,
            'fields':[f['name'] for f in meta['fields']],'complete_ids_verified':True,'current_rule_or_stall_validation':False}
    save('ucla_events','demand_proxy',ucla,'Public UCLA calendar/ICS. Website terms apply; no bulk redistribution license verified. Store only bounded factual event fields; raw stays local.')
    save('westwood_events','demand_proxy',westwood,'Public Westwood Village / Vibemap endpoint actually used by its event page; no separate open-data redistribution license verified. Predicted recurrence listings are not independently confirmed events.')
    save('sweeping','supply_rule_candidate',lambda:layer('sweeping',cfg['sweeping_layer'],normalize_sweeping),'Public City source linked by StreetsLA application; service license text not specified. Route polygons do not establish side-specific legal restrictions.')
    fields='AutoID,PWRS_ID,Category,Type,EventType,StreetName,EnterDate,StartDate,EndDate,ActiveStatus'
    for name,index in [('pwrs_lines',34),('pwrs_polygons',35)]:
        save(name,'temporary_activity_not_verified_closure',lambda name=name,index=index:layer(name,cfg['pwrs_root']+'/'+str(index),normalize_reservation,fields,True),'Public City BOE service; no contacts or token-bearing report links requested. No complete legal-closure coverage claimed.')
    def historical():
        p,r=s.get(cfg['historic_westwood_report'],max_mb=cfg['maximum_historic_pdf_mb']);from pypdf import PdfReader
        reader=PdfReader(p);hits=[]
        for i,page in enumerate(reader.pages[:120]):
            text=page.extract_text() or ''
            if re.search(r'Westwood',text,re.I) and re.search(r'parking|2013',text,re.I):hits.append(i+1)
        return [{'source_url':cfg['historic_westwood_report'],'raw_sha256':r['sha256'],'received_at_utc':r['received_at_utc'],'pdf_pages':len(reader.pages),
            'westwood_parking_reference_pages':hits,'pages_inspected':min(120,len(reader.pages)),'inspection_truncated':len(reader.pages)>120,'exact_observation_times':None,'full_face_labels_recovered':0,'role':'historic_context_only','current_occupancy_label':False}],{'source_url':cfg['historic_westwood_report'],'received_at_utc':r['received_at_utc'],'raw_sha256':r['sha256'],'bytes':r['bytes'],'not_substituted_with_existing_venice_report':True}
    save('historical_westwood','historic_study_not_current_labels',historical,'Official City Planning staff report; factual reference/page index only. No raw current occupancy truth recovered.')
    report['additional_blockers']={'hammer_event_times':'Sample official event HTML encodes 12:30Z while displaying 12:30 PM local; timezone semantics unresolved. Not normalized into exact-time predictors.',
        'current_restrictions':'No complete verified posted-sign/temporary-rule feed. Sweeping polygons and PWRS reservations are evidence leads; no legal capacity inferred.',
        'historical_availability':'First observed receipt is the earliest usable availability timestamp for current listings/rules; source edits do not prove historical publication.'}
    report['request_manifest']=str(s.root/'manifest.jsonl')
    out=Path('reports/westwood_context');out.mkdir(parents=True,exist_ok=True);(out/'coverage.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    lines=['# Westwood public context acquisition','','| Source | Role | Status | Rows |','|---|---|---|---:|']
    for name,r in report['sources'].items():lines.append(f"| {name} | {r['role']} | {r['status']} | {r.get('rows','unavailable')} |")
    lines+=['','Current listings and rules remain prospective context. No occupancy labels, historical test rows or serving models were changed. Unknown timezone, curb side, effective rules and capacity remain unknown. Full request/response provenance and normalized snapshots stay local; coverage.json records source receipts, fields and blockers.']
    (out/'coverage.md').write_text('\n'.join(lines)+'\n',encoding='utf8');return report


def features_asof(requests,coverage):
    """Receipt-gated context candidates only; never an eligibility decision."""
    from shapely.geometry import Point,shape
    from shapely.ops import transform
    from pyproj import Transformer
    from .signals import distance_m
    project=Transformer.from_crs(4326,26911,always_xy=True).transform
    rows=[];cache={};west,south,east,north=coverage['bbox']
    for request in requests:
        issue=pd.Timestamp(request['issued_at_utc']);arrival=pd.Timestamp(request['arrival_time_utc'])
        if issue.tzinfo is None or arrival.tzinfo is None or arrival<issue:raise ValueError('Ordered aware forecast times required')
        point=Point(request['longitude'],request['latitude']);result={'request_id':request['request_id'],'sweeping_route_candidate_count':None,'pwrs_reservation_candidate_count':None,'geolocated_timed_event_count':None,'legal_eligibility':'unknown','feature_available_at_utc':None};receipts=[]
        if not west<=point.x<=east or not south<=point.y<=north:result['context_status']='outside_bounded_geography';rows.append(result);continue
        result['context_status']='receipt_gated_context_not_complete_rules'
        for name,source in coverage['sources'].items():
            if source['status']!='acquired' or not source.get('received_at_utc') or pd.Timestamp(source['received_at_utc'])>issue or issue-pd.Timestamp(source['received_at_utc'])>pd.Timedelta('48h'):continue
            if name not in cache:cache[name]=json.loads(Path(source['normalized_path']).read_text(encoding='utf8'))
            records=cache[name];receipts.append(source['received_at_utc'])
            if name=='sweeping':result['sweeping_route_candidate_count']=sum(shape(r['geometry']).covers(point) for r in records)
            if name.startswith('pwrs'):
                projected=transform(project,point)
                n=sum(transform(project,shape(r['geometry'])).distance(projected)<=15 for r in records if r.get('geometry'))
                result['pwrs_reservation_candidate_count']=(result['pwrs_reservation_candidate_count'] or 0)+n
            if name in ['ucla_events','westwood_events']:
                usable=[r for r in records if r.get('start_utc') and r.get('latitude') is not None]
                if usable:
                    n=sum(abs((pd.Timestamp(r['start_utc'])-arrival).total_seconds())<=7200 and distance_m(r['latitude'],r['longitude'],point.y,point.x)<=1000 for r in usable)
                    result['geolocated_timed_event_count']=(result['geolocated_timed_event_count'] or 0)+n
        if receipts:result['feature_available_at_utc']=max(receipts,key=pd.Timestamp)
        rows.append(result)
    return rows
