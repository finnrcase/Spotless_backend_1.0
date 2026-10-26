"""Local capture intake, blinded review and collection economics; no CV promotion."""
import hashlib,html,json,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,model_validator
from PIL import Image
from .product_evaluation import block,stamp


class MediaCapture(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    capture_id:str
    block_face_id:str
    session_id:str
    visit_id:str
    source:Literal['manual_count','walking_camera','passenger_camera','future_drone','historic_aerial']
    media_path:str | None=None
    manual_observation_id:str | None=None
    capture_at_utc:AwareDatetime | None=None
    capture_date:str | None=None
    time_precision:Literal['exact_offset','date_only','local_without_offset','unknown']='unknown'
    latitude:float | None=Field(default=None,ge=-90,le=90)
    longitude:float | None=Field(default=None,ge=-180,le=180)
    geolocation_method:Literal['exif_gps','sidecar_gps','confirmed_map_pin','unknown']='unknown'
    source_received_at_utc:AwareDatetime | None=None
    frame_offset_seconds:float | None=Field(default=None,ge=0)
    visible_fraction:float | None=Field(default=None,ge=0,le=1)
    occlusion: list[Literal['tree','shadow','traffic','other','unmeasured']]=Field(default_factory=lambda:['unmeasured'])
    occupied_visible:int | None=Field(default=None,ge=0)
    physical_capacity:int | None=Field(default=None,ge=0)
    legal_capacity:int | None=Field(default=None,ge=0)
    legal_capacity_status:Literal['verified','uncertain','unknown']='unknown'
    vehicle_class:str='standard_passenger'
    permit_class:str | None=None
    intended_duration_minutes:int | None=Field(default=None,gt=0)
    restriction_evidence:str=''
    confidence:float | None=Field(default=None,ge=0,le=1)
    privacy_reviewed:bool=False
    identifiers_present:bool | None=None
    detector_count_candidate:int | None=Field(default=None,ge=0)
    @model_validator(mode='after')
    def coherent(self):
        if (self.time_precision=='exact_offset')!=(self.capture_at_utc is not None):raise ValueError('Exact offset capture time required together; date-only/local clocks cannot become exact timestamps')
        if (self.latitude is None)!=(self.longitude is None):raise ValueError('Both coordinates or neither required')
        if self.source!='manual_count' and not self.media_path:raise ValueError('Media capture needs an actual local file')
        if self.source=='manual_count' and not self.manual_observation_id:raise ValueError('Manual reference needs its real observation ID')
        if self.legal_capacity_status=='unknown' and self.legal_capacity is not None:raise ValueError('Unknown legal capacity must remain null')
        if self.physical_capacity is not None and self.legal_capacity is not None and self.legal_capacity>self.physical_capacity:raise ValueError('Legal capacity exceeds physical capacity')
        if self.visible_fraction==0 and self.occupied_visible not in [None,0]:raise ValueError('Invisible curb cannot have observed visible vehicles')
        if self.legal_capacity_status=='verified' and (self.legal_capacity is None or not self.restriction_evidence.strip() or self.intended_duration_minutes is None):raise ValueError('Verified legal capacity requires a value, stay/profile and restriction evidence')
        return self


class MediaReview(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    review_id:str
    capture_id:str
    reviewer_code:str
    reviewed_at_utc:AwareDatetime
    independent_blind_count:bool=False
    human_counted:bool=False
    capture_time_verified:bool=False
    location_verified:bool=False
    occupied_visible:int | None=Field(default=None,ge=0)
    visible_fraction:float | None=Field(default=None,ge=0,le=1)
    full_face_visible:bool=False
    privacy_verified:bool=False
    visible_scope_id:str=Field(min_length=1)
    masks:list[dict]=Field(default_factory=list)
    physical_capacity:int | None=Field(default=None,ge=0)
    legal_capacity:int | None=Field(default=None,ge=0)
    legal_capacity_status:Literal['verified','uncertain','unknown']='unknown'
    restriction_evidence:str=''
    confidence:float | None=Field(default=None,ge=0,le=1)
    adjudicated:bool=False
    notes:str=''
    @model_validator(mode='after')
    def visible(self):
        if self.full_face_visible and self.visible_fraction!=1:raise ValueError('Full-face review requires explicitly complete visibility')
        if self.legal_capacity_status=='unknown' and self.legal_capacity is not None:raise ValueError('Unknown legal capacity must remain null')
        for m in self.masks:
            if set(m)!={'kind','xyxy'} or m['kind'] not in ['visible_curb','tree','shadow','other']:raise ValueError('Unknown mask schema/class')
            v=m['xyxy']
            if len(v)!=4 or any(not np.isfinite(x) or x<0 for x in v) or not v[0]<v[2] or not v[1]<v[3]:raise ValueError('Mask rectangle requires ordered finite pixel coordinates')
        return self


def digest_file(path,max_bytes=250_000_000):
    p=Path(path)
    if p.stat().st_size>max_bytes:raise ValueError('Capture exceeds 250 MB per-file budget; supply a bounded reviewed clip/frame')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def metadata_suggestions(path):
    """Suggestions only. No filename/mtime date inference; no face/plate analysis."""
    out={'capture_at_utc':None,'time_precision':'unknown','latitude':None,'longitude':None,'metadata_needs_review':True}
    if Path(path).suffix.lower() not in ['.jpg','.jpeg','.png','.tif','.tiff']:return {**out,'blocker':'Video needs an explicit timestamp/geolocation sidecar and frame offset; no decoder silently inferred.'}
    with Image.open(path) as image:
        exif=image.getexif();original=exif.get(36867);offset=exif.get(36881)
        if original and offset:
            try:out.update(capture_at_utc=datetime.fromisoformat(datetime.strptime(str(original),'%Y:%m:%d %H:%M:%S').isoformat()+str(offset)).astimezone(timezone.utc).isoformat(),time_precision='exact_offset')
            except ValueError:out['time_precision']='local_without_offset'
        elif original:out['time_precision']='local_without_offset'
        try:
            gps=exif.get_ifd(34853)
            def decimal(parts,reference):
                value=sum(float(v)/scale for v,scale in zip(parts,[1,60,3600]));return -value if reference in ['S','W',b'S',b'W'] else value
            if all(k in gps for k in [1,2,3,4]):out.update(latitude=decimal(gps[2],gps[1]),longitude=decimal(gps[4],gps[3]))
        except (KeyError,ValueError,TypeError,AttributeError):pass
        out['width'],out['height']=image.size
    return out


def connect(directory='data/observations/captures'):
    root=Path(directory);root.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(root/'captures.sqlite3')
    db.executescript('CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY, fingerprint TEXT, body TEXT); CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,capture_id TEXT,reviewer TEXT,body TEXT,UNIQUE(capture_id,reviewer)); CREATE TABLE IF NOT EXISTS effort(id TEXT PRIMARY KEY,body TEXT);')
    return db


def protected(row):
    # The prior helper also guards all earlier reservations; unknown times cannot
    # establish a temporal label but reserved physical blocks stay protected.
    for path in ['config/field_holdouts.json','config/coverage_v4_field_holdouts.json']:
        p=Path(path)
        if p.exists():
            r=json.loads(p.read_text());held=set(r['unseen_physical_blocks'])|set(r.get('known_future_physical_blocks',[]))
            if block(row['block_face_id']) in held or row['session_id'] in r['reserved_session_ids']:return True
    if row.get('capture_at_utc'):
        from .sensor_capture import protected_period
        return protected_period(row['capture_at_utc'])
    return False


def import_captures(manifest,directory='data/observations/captures',inventory_path='data/processed/block_faces.parquet'):
    rows=[json.loads(line) for line in Path(manifest).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if len(rows)>200:raise ValueError('At most 200 captures per bounded batch')
    faces=set(pd.read_parquet(inventory_path,columns=['block_face_id']).block_face_id);db=connect(directory);accepted=duplicate=0
    try:
        with db:
            for raw in rows:
                c=MediaCapture.model_validate(raw);body=c.model_dump(mode='json')
                if c.block_face_id not in faces:raise ValueError('Unknown block face; use the generated plan IDs')
                sha=digest_file(c.media_path) if c.media_path else None
                body['file_sha256']=sha;fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
                old=db.execute('SELECT fingerprint FROM captures WHERE id=?',(c.capture_id,)).fetchone()
                if old:
                    if old[0]!=fingerprint:raise ValueError('Conflicting capture ID; existing metadata was preserved')
                    duplicate+=1;continue
                previous=[json.loads(r[0]) for r in db.execute('SELECT body FROM captures')]
                same_file=next((r for r in previous if sha is not None and r.get('file_sha256')==sha),None)
                body['duplicate_of']=same_file['capture_id'] if same_file else None
                # Adjacent frames of the same visit are one unit, even with
                # different file hashes. Repeat visits need different visit IDs.
                unit=f'{c.session_id}|{c.visit_id}|{c.block_face_id}|{c.source}'
                body['sample_unit_id']=same_file['sample_unit_id'] if same_file else hashlib.sha256(unit.encode()).hexdigest()[:20]
                body['received_at_utc']=datetime.now(timezone.utc).isoformat();body['protected_holdout']=protected(body);body['automatically_trusted_label']=False
                if c.media_path and Path(c.media_path).suffix.lower() in ['.jpg','.jpeg','.png','.tif','.tiff']:body['exif_suggestions']=metadata_suggestions(c.media_path)
                if c.capture_at_utc and stamp(c.capture_at_utc)>stamp(body['received_at_utc']):raise ValueError('Capture time is after actual receipt')
                db.execute('INSERT INTO captures VALUES (?,?,?)',(c.capture_id,fingerprint,json.dumps(body)));accepted+=1
    finally:db.close()
    return {'accepted':accepted,'duplicate_identical_ids':duplicate,'automatic_cv_labels':0,'raw_media_copied_or_committed':False}


def import_reviews(path,directory='data/observations/captures'):
    db=connect(directory);accepted=0
    try:
        with db:
            for line in Path(path).read_text(encoding='utf8').splitlines():
                if not line.strip():continue
                r=MediaReview.model_validate_json(line);found=db.execute('SELECT body FROM captures WHERE id=?',(r.capture_id,)).fetchone()
                if not found:raise ValueError('Review references unknown capture')
                capture=json.loads(found[0])
                if capture['protected_holdout']:raise ValueError('Reserved captures remain quarantined; no development review')
                if stamp(r.reviewed_at_utc)<stamp(capture['received_at_utc']):raise ValueError('Review predates receipt')
                body=r.model_dump_json();old=db.execute('SELECT body FROM reviews WHERE id=?',(r.review_id,)).fetchone()
                if old:
                    if json.loads(old[0])!=json.loads(body):raise ValueError('Conflicting review ID')
                    continue
                db.execute('INSERT INTO reviews VALUES (?,?,?,?)',(r.review_id,r.capture_id,r.reviewer_code,body));accepted+=1
    finally:db.close()
    return {'accepted_reviews':accepted,'cv_counts_promoted':0}


def import_effort(path,directory='data/observations/captures'):
    db=connect(directory);rows=[json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    try:
        with db:
            existing=[json.loads(r[0]) for r in db.execute('SELECT body FROM effort')]
            for r in rows:
                if set(r)!={'effort_id','operator_code','start_utc','end_utc','activity'} or r['activity'] not in ['travel','capture','manual_count','review']:raise ValueError('Use explicit operator effort intervals and activity')
                a,b=stamp(r['start_utc']),stamp(r['end_utc'])
                if b<=a:raise ValueError('Effort interval must be positive')
                for old in existing:
                    if old['effort_id']==r['effort_id']:
                        if old!=r:raise ValueError('Conflicting effort ID')
                        break
                    if old['operator_code']==r['operator_code'] and a<stamp(old['end_utc']) and stamp(old['start_utc'])<b:raise ValueError('Overlapping operator effort would double-count hours')
                else:db.execute('INSERT INTO effort VALUES (?,?)',(r['effort_id'],json.dumps(r)));existing.append(r)
    finally:db.close()
    return {'effort_intervals':len(rows)}


def audit(directory='data/observations/captures',output='reports/collection'):
    db=connect(directory);captures=[json.loads(r[0]) for r in db.execute('SELECT body FROM captures')];reviews=[json.loads(r[0]) for r in db.execute('SELECT body FROM reviews')];effort=[json.loads(r[0]) for r in db.execute('SELECT body FROM effort')];db.close()
    queue=[];agreement={};usable=set();frame_pairs=0
    for c in captures:
        if c['protected_holdout']:continue
        rs=[r for r in reviews if r['capture_id']==c['capture_id'] and r['human_counted'] and r['independent_blind_count'] and r['privacy_verified'] and r['occupied_visible'] is not None]
        reasons=[]
        if c['duplicate_of']:reasons.append('Exact-byte duplicate: not independent')
        if not c['capture_at_utc'] or c['time_precision']!='exact_offset':reasons.append('Exact capture clock unavailable')
        if c['latitude'] is None:reasons.append('Geolocation unavailable')
        if c['identifiers_present'] is True or not ((c['privacy_reviewed'] and c['identifiers_present'] is False) or len(rs)>=2):reasons.append('Privacy review/redaction required')
        if len(rs)<2:reasons.append('Two blinded independent human counts required')
        if rs and not all(r['capture_time_verified'] and r['location_verified'] for r in rs):reasons.append('Time/location verification incomplete')
        adjudicated=len(rs)>=3 and any(r['adjudicated'] and r['notes'].strip() for r in rs)
        for i,a in enumerate(rs):
            for b in rs[i+1:]:
                if a['visible_scope_id']==b['visible_scope_id'] and a['masks']==b['masks']:
                    agreement.setdefault(c['sample_unit_id'],[]).append(abs(a['occupied_visible']-b['occupied_visible']));frame_pairs+=1
                    if a['occupied_visible']!=b['occupied_visible'] and not adjudicated:reasons.append('Count disagreement needs explicit adjudication')
        if rs and not all(r['full_face_visible'] and r['visible_fraction']==1 for r in rs):reasons.append('Hidden curb remains unknown; visible-only counts')
        if not reasons and len(rs)>=2 and all(r['visible_scope_id']==rs[0]['visible_scope_id'] and r['masks']==rs[0]['masks'] for r in rs):usable.add(c['sample_unit_id'])
        # Shared masks are visible to the next rater; earlier counts are not.
        blinded={k:v for k,v in c.items() if k not in ['occupied_visible','detector_count_candidate']}
        queue.append({'capture':blinded,'reasons':reasons or ['Count unit ready; rules/capacity still require separate review'],'shared_masks':rs[0]['masks'] if rs else []})
    hours=sum((stamp(r['end_utc'])-stamp(r['start_utc'])).total_seconds()/3600 for r in effort)
    report={'captures':len(captures),'quarantined':sum(c['protected_holdout'] for c in captures),'unique_sample_units':len({c['sample_unit_id'] for c in captures}),
        'exact_byte_duplicate_captures':sum(c['duplicate_of'] is not None for c in captures),'count_agreement_sample_units':len(agreement),'count_agreement_frame_pairs':frame_pairs,
        'independent_count_mae_equal_weight_per_unit':float(np.mean([np.mean(v) for v in agreement.values()])) if agreement else None,'reviewed_full_face_count_units':len(usable),
        'operator_hours_recorded':hours if hours else None,'usable_count_units_per_operator_hour':len(usable)/hours if hours else None,
        'effort_completeness':'Self-reported travel/capture/count/review intervals; completeness not independently established. No yield claim without recorded effort.',
        'legal_vacancy_labels_promoted':0,'detector_count_mae':None,'detection_precision':None,'detection_recall':None,
        'detector_blocker':'No suitable time-specific supplied imagery with independent reference detections has been evaluated. Existing NAIP is 2022 date-only imagery, not prospective truth.',
        'status':'review_workflow_ready_metrics_unavailable' if not captures else 'local_capture_review_audit','queue_items':len(queue),'models_changed':False}
    out=Path(output);out.mkdir(parents=True,exist_ok=True);(out/'audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    (out/'review_queue.json').write_text(json.dumps(queue,indent=2)+'\n',encoding='utf8')
    template=Path('web/capture_review.html').read_text(encoding='utf8');(out/'review_queue.html').write_text(template.replace('/*__QUEUE__*/',json.dumps(queue).replace('<','\\u003c')),encoding='utf8')
    return report
