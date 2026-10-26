"""Record delivery separately from provider event time; quarantine reserved periods."""
import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime,timezone
import uuid
import pandas as pd
from .http import Store


def reservation_windows(config_path='config/spatial_v3.json'):
    cfg=json.loads(Path(config_path).read_text())
    windows=[cfg[k] for k in ['new_untouched_archive_holdout','new_untouched_manual_holdout']]
    old_path=Path('config/temporal_v2.json')
    if old_path.exists():
        old=json.loads(old_path.read_text());windows.extend(old[k] for k in ['new_archive_holdout','prospective_manual_holdout'])
    return windows


def protected_period(at,config_path='config/spatial_v3.json'):
    local=pd.Timestamp(at).tz_convert('America/Los_Angeles')
    return any(pd.Timestamp(w['start_local'],tz='America/Los_Angeles')<=local<pd.Timestamp(w['end_local'],tz='America/Los_Angeles') for w in reservation_windows(config_path))


class Capture:
    def __init__(self,directory='data/observations/sensor_capture'):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.directory/'delivery.sqlite3')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS polls (id TEXT PRIMARY KEY, checked_at TEXT NOT NULL, status TEXT NOT NULL, rows INTEGER, new_events INTEGER, unchanged_rows INTEGER, sha256 TEXT, raw_path TEXT, quarantined INTEGER NOT NULL, error TEXT);
          CREATE TABLE IF NOT EXISTS events (space_id TEXT, event_time TEXT, state TEXT, first_seen_at TEXT, last_seen_at TEXT, PRIMARY KEY(space_id,event_time,state));''')
    def record(self,rows,at,raw_path=None,quarantined=False,error=None):
        at=pd.Timestamp(at)
        if at.tzinfo is None:raise ValueError('Aware capture time required')
        stamp=at.tz_convert('UTC').isoformat();ident=str(uuid.uuid4());new=unchanged=future=0
        if not quarantined and error is None:
            with self.db:
                for row in rows:
                    event=pd.Timestamp(row['eventtime'])
                    if event.tzinfo is None:event=event.tz_localize('UTC') # official dictionary specifies UTC
                    event=event.tz_convert('UTC')
                    if event>at:
                        future+=1;continue # retained raw, not evidence
                    state=row.get('occupancystate','UNKNOWN');state=state if state in ['OCCUPIED','VACANT'] else 'UNKNOWN'
                    key=(str(row['spaceid']),event.isoformat(),state);exists=self.db.execute('SELECT 1 FROM events WHERE space_id=? AND event_time=? AND state=?',key).fetchone()
                    if exists:
                        self.db.execute('UPDATE events SET first_seen_at=min(first_seen_at,?),last_seen_at=max(last_seen_at,?) WHERE space_id=? AND event_time=? AND state=?',(stamp,stamp)+key);unchanged+=1
                    else:
                        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',key+(stamp,stamp));new+=1
        sha=hashlib.sha256(Path(raw_path).read_bytes()).hexdigest() if raw_path else None
        status='unavailable' if error else 'quarantined' if quarantined else 'captured'
        with self.db:self.db.execute('INSERT INTO polls VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,stamp,status,None if rows is None else len(rows),None if quarantined else new,None if quarantined else unchanged,sha,str(raw_path) if raw_path else None,int(quarantined),error))
        return {'poll_id':ident,'checked_at_utc':stamp,'status':status,'rows':None if rows is None else len(rows),'new_provider_transactions':None if quarantined else new,'unchanged_poll_rows':None if quarantined else unchanged,'quarantined_outcomes':quarantined,'sha256':sha,'error':error,
            'rejected_future_timestamp_rows':None if quarantined else future,'interpretation':'A poll is not a sensor heartbeat. Unchanged poll rows do not refresh occupancy event age. Failure is a source-poll failure, not proof of individual sensor outages.'}
    def latest_asof(self,space_id,at):
        stamp=pd.Timestamp(at).tz_convert('UTC').isoformat()
        rows=self.db.execute('SELECT event_time,state,first_seen_at FROM events WHERE space_id=? AND event_time<=? AND first_seen_at<=? ORDER BY event_time DESC',(space_id,stamp,stamp)).fetchall()
        if not rows:return None
        latest=[r for r in rows if r[0]==rows[0][0]];states={r[1] for r in latest}
        return {'event_time':rows[0][0],'state':next(iter(states)) if len(states)==1 else 'UNKNOWN','first_seen_at':min(r[2] for r in latest),'conflict':len(states)>1}
    def status(self):
        return {'polls':self.db.execute('SELECT status,count(*) FROM polls GROUP BY status').fetchall(),'last_poll':self.db.execute('SELECT checked_at,status,error FROM polls ORDER BY checked_at DESC LIMIT 1').fetchone(),
            'parsed_provider_transactions':self.db.execute('SELECT count(*) FROM events').fetchone()[0],'quarantined_rows_used_for_features':False}
    def release_for_locked_evaluation(self,poll_id,lock_path='reports/modeling/spatial_v3_locked_models.json',now=None):
        """Release into a separate evaluation database, never the live feature store."""
        row=self.db.execute('SELECT checked_at,raw_path,sha256,quarantined FROM polls WHERE id=?',(poll_id,)).fetchone()
        if row is None or not row[3]:raise ValueError('A quarantined poll ID is required')
        captured=pd.Timestamp(row[0]);current=pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert('UTC')
        ends=[pd.Timestamp(w['end_local'],tz='America/Los_Angeles') for w in reservation_windows() if pd.Timestamp(w['start_local'],tz='America/Los_Angeles')<=captured<pd.Timestamp(w['end_local'],tz='America/Los_Angeles')]
        if ends and current<max(ends):raise ValueError('Reserved evaluation period has not ended; outcomes remain unopened')
        lock=json.loads(Path(lock_path).read_text())
        if not lock.get('checks_passed') or not lock.get('new_holdouts_unopened'):raise ValueError('Verified frozen model lock required')
        for p,sha in lock['models_sha256'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha:raise ValueError('Locked model changed; release refused')
        raw=Path(row[1])
        if hashlib.sha256(raw.read_bytes()).hexdigest()!=row[2]:raise ValueError('Quarantined snapshot hash mismatch')
        destination=self.directory/'locked_evaluation'/hashlib.sha256(Path(lock_path).read_bytes()).hexdigest()[:12]
        evaluation=Capture(destination)
        try:result=evaluation.record(json.loads(raw.read_bytes()),captured,raw)
        finally:evaluation.close()
        result.update(purpose='locked_evaluation_only',evaluation_directory=str(destination),live_feature_database_unchanged=True)
        return result
    def close(self):self.db.close()


def poll(directory='data/observations/sensor_capture',quarantine=False,store=None,clock=None):
    at=pd.Timestamp(clock() if clock else datetime.now(timezone.utc));capture=Capture(directory)
    if protected_period(at) and not quarantine:
        capture.close();raise ValueError('Current time is in a reserved holdout. Use --quarantine to save a blind snapshot; no labels will enter the feature store.')
    store=store or Store(refresh=True,max_mb=4);url='https://data.lacity.org/resource/e7h6-4a3e.json'
    raw=None
    try:
        count,_=store.json(url,{'$select':'count(*)'});n=int(count[0]['count'])
        if n>10000:raise ValueError('Source exceeds the 10000-row poll budget; no truncation accepted')
        raw,record=store.get(url,{'$limit':max(1,n),'$order':':id'},max_mb=4)
        rows=json.loads(raw.read_bytes())
        if not isinstance(rows,list) or len(rows)!=n:raise ValueError('Incomplete source poll')
        # Reserved outcomes are preserved blind; no states/timestamps are inspected.
        received=pd.Timestamp(clock() if clock else datetime.now(timezone.utc));quarantine=quarantine or protected_period(received)
        result=capture.record(rows if not quarantine else [None]*len(rows),received,raw,quarantine)
        result['source_poll_started_at_utc']=at.isoformat()
    except Exception as exc:result=capture.record(None,pd.Timestamp(clock() if clock else datetime.now(timezone.utc)),raw_path=raw,error=str(exc))
    finally:capture.close()
    return result


def compare_manual(capture,observations,reviewed_pairs=()):
    approved=set(reviewed_pairs);cases=[];candidates=0
    for record in observations:
        bays=record.get('meter_bays');bays=[] if bays is None or isinstance(bays,float) else list(bays)
        for bay in bays:
            candidates+=1
            if (record['observation_id'],bay['space_id']) not in approved or not bay.get('identity_verified') or bay['state']=='UNKNOWN':continue
            at=pd.Timestamp(bay['observed_at_utc']);source=capture.latest_asof(bay['space_id'],at)
            age=(at-pd.Timestamp(source['event_time'])).total_seconds()/60 if source else None
            cases.append({'actual':bay['state'],'source':source,'age':age})
    policies=[];common=[c for c in cases if c['source'] and c['source']['state']!='UNKNOWN' and 0<=c['age']<=5]
    for minutes in [5,15,60,180]:
        used=[c for c in cases if c['source'] and c['source']['state']!='UNKNOWN' and 0<=c['age']<=minutes]
        policies.append({'expiry_minutes':minutes,'reviewed_cases':len(cases),'supported':len(used),'coverage':len(used)/len(cases) if cases else None,
            'agreement':sum(c['source']['state']==c['actual'] for c in used)/len(used) if used else None,'common_case_n':len(common),
            'common_case_agreement':sum(c['source']['state']==c['actual'] for c in common)/len(common) if common else None,
            'occupied_fraction_in_selected_humans':sum(c['actual']=='OCCUPIED' for c in used)/len(used) if used else None})
    return {'status':'descriptive_reviewed_bay_comparison' if cases else 'awaiting_independent_reviewed_bay_observations','candidate_bays':candidates,'reviewed_eligible_bays':len(cases),'policies':policies,
        'expiry_changed':False,'cutoff_selected_by_r2':False,'rules_or_legal_capacity_validated':False,'limitations':'Delivery must precede observation. UNKNOWN/conflicts and unseen events stay uncertain. This does not certify outages, heartbeat cadence or legal parking.'}
