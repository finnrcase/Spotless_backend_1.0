"""Time-weighted sensor-panel labels; never full-curb or legally eligible labels."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .temporal import intervals


def seconds(values):
    return pd.to_datetime(values,utc=True).astype('datetime64[ns, UTC]').astype('int64').to_numpy()/1e9


def interval_panel(events,mapping,start,end,step_minutes=15,cap_minutes=15,roster_end=None):
    """Roster fixed from discovery period. No backfill or extension past TTL.

    known_seconds/occupied_seconds are sums of interval overlap lengths, not
    transaction counts. Point counts require all roster sensors to be known.
    """
    step=step_minutes*60
    if step_minutes<=0 or cap_minutes<=0: raise ValueError('Positive intervals and persistence caps required')
    start,end=pd.Timestamp(start),pd.Timestamp(end)
    if start.tzinfo is None or end.tzinfo is None or end<=start: raise ValueError('Ordered aware window required')
    roster_end=pd.Timestamp(roster_end) if roster_end is not None else start
    if roster_end>start: raise ValueError('Roster discovery must finish before label window')
    events=events[['space_id','observed_at_utc','state']].copy()
    events.observed_at_utc=pd.to_datetime(events.observed_at_utc,utc=True)
    roster_ids=set(events.loc[events.observed_at_utc<roster_end,'space_id'])
    m=mapping.loc[(mapping.join_status=='matched')&mapping.space_id.isin(roster_ids)].copy()
    if m.space_id.duplicated().any(): raise ValueError('A sensor cannot map to multiple faces')
    faces=sorted(m.block_face_id.unique()); fi={f:i for i,f in enumerate(faces)}
    e=events.merge(m[['space_id','block_face_id']],on='space_id',how='inner',validate='many_to_one')
    bins=pd.date_range(start,end,freq=f'{step_minutes}min',inclusive='left').tz_convert('UTC')
    n=len(bins); shape=(len(faces),n)
    known=np.zeros(shape); occupied=np.zeros(shape); point_known=np.zeros(shape); point_occupied=np.zeros(shape)
    arrivals=np.zeros(shape); departures=np.zeros(shape)
    iv=intervals(e,cap_minutes,window_end=end).merge(m[['space_id','block_face_id']],on='space_id',validate='many_to_one')
    origin=start.timestamp(); finish=end.timestamp()
    # Each clipped persistence interval contributes exact overlaps to at most cap/step+1 bins.
    for r in iv.itertuples(index=False):
        if not r.known: continue
        a=max(origin,r.observed_at_utc.timestamp()); b=min(finish,r.valid_to_utc.timestamp())
        if b<=a: continue
        face=fi[r.block_face_id]; i=max(0,int((a-origin)//step)); last=min(n-1,int(np.ceil((b-origin)/step))-1)
        for k in range(i,last+1):
            overlap=max(0,min(b,origin+(k+1)*step)-max(a,origin+k*step))
            known[face,k]+=overlap
            if r.state=='OCCUPIED': occupied[face,k]+=overlap
        first_point=max(0,int(np.ceil((a-origin)/step))); last_point=min(n-1,int(np.ceil((b-origin)/step))-1)
        if last_point>=first_point:
            point_known[face,first_point:last_point+1]+=1
            if r.state=='OCCUPIED': point_occupied[face,first_point:last_point+1]+=1
    # Transitions count only observed opposite states close enough to avoid spanning a gap.
    e=e.drop_duplicates().sort_values(['space_id','observed_at_utc'])
    conflicts=e.groupby(['space_id','observed_at_utc']).state.transform('nunique')>1
    e.loc[conflicts,'state']='UNKNOWN';e=e.drop_duplicates(['space_id','observed_at_utc'])
    previous=e.groupby('space_id').state.shift(); gap=e.groupby('space_id').observed_at_utc.diff().dt.total_seconds()
    valid=previous.isin(['VACANT','OCCUPIED'])&e.state.isin(['VACANT','OCCUPIED'])&(previous!=e.state)&gap.le(cap_minutes*60)
    for r in e.loc[valid].itertuples(index=False):
        k=int((r.observed_at_utc.timestamp()-origin)//step)
        if 0<=k<n:
            (arrivals if r.state=='OCCUPIED' else departures)[fi[r.block_face_id],k]+=1
    roster=m.groupby('block_face_id').size()
    rows=[]
    for f in faces:
        i=fi[f]; expected=int(roster[f]); frac=known[i]/(expected*step)
        if (frac>1+1e-8).any(): raise ValueError('Overlapping sensor intervals exceed panel capacity')
        complete=np.isclose(point_known[i],expected)
        rate=np.divide(occupied[i],known[i],out=np.full(n,np.nan),where=known[i]>0)
        rows.append(pd.DataFrame({'block_face_id':f,'interval_start_utc':bins,'panel_sensor_count':expected,
            'known_seconds':known[i],'occupied_seconds':occupied[i],'coverage_fraction':frac,'occupancy_rate':rate,
            'point_known_sensors':point_known[i],'panel_occupied_count':np.where(complete,point_occupied[i],np.nan),
            'panel_available_count':np.where(complete,expected-point_occupied[i],np.nan),
            'panel_any_vacant':np.where(complete,(expected-point_occupied[i]>0).astype(float),np.nan),
            'arrivals':arrivals[i],'departures':departures[i],'full_panel_point_label':complete,
            'full_curb_label':False,'persistence_minutes':cap_minutes,'roster_available_at_utc':roster_end.tz_convert('UTC')}))
    result=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame()
    quality={'events':len(events),'mapped_roster_sensors':len(m),'roster_faces':len(faces),'all_face_intervals':len(result),
             'known_sensor_time_fraction':float(known.sum()/(sum(roster)*step*n)) if len(m) and n else 0,
             'complete_panel_points':int(result.full_panel_point_label.sum()) if len(result) else 0,
             'unknown_events':int(events.state.eq('UNKNOWN').sum()),'conflicting_event_rows':int(conflicts.sum()),
             'roster_end_utc':roster_end.isoformat(),'label_start_utc':start.isoformat(),'label_end_utc':end.isoformat()}
    return result,quality


def build_labels(config_path='config/modeling.json'):
    config=json.loads(Path(config_path).read_text()); output=Path('data/modeling'); output.mkdir(parents=True,exist_ok=True)
    reports=Path('reports/modeling');reports.mkdir(parents=True,exist_ok=True)
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet')
    all_frames=[];quality=[];sources={}
    for path in sorted(Path('data/processed').glob('pilot_history_20*.parquet')):
        events=pd.read_parquet(path); label=path.stem.removeprefix('pilot_history_');year,month=map(int,label.split('_'))
        source_start=pd.Timestamp(year=year,month=month,day=1,tz='America/Los_Angeles')
        end=source_start+pd.DateOffset(months=1);discovery=source_start+pd.DateOffset(days=config['roster_discovery_days'])
        sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        for cap in config['persistence_caps_minutes']:
            print('Labels',label,'persistence',cap,flush=True)
            frame,info=interval_panel(events,mapping,discovery,end,config['interval_minutes'],cap,discovery)
            info.update(month=label,persistence_minutes=cap);quality.append(info)
            if cap==config['primary_persistence_minutes']:
                frame['source_month']=label;all_frames.append(frame)
    panel=pd.concat(all_frames,ignore_index=True)
    panel.to_parquet(output/'panel_intervals.parquet',index=False)
    manifest={'config':config,'source_hashes':sources,'mapping_sha256':hashlib.sha256(Path('data/processed/meter_face_mapping.parquet').read_bytes()).hexdigest(),
              'evidence_class':'retrospective_sensor_panel_proxy','assumed_event_delivery':'event timestamp treated as immediate availability; historical ingestion timestamps unavailable',
              'quality':quality,'eligible_capacity':'unknown','physical_capacity':'unknown','true_suitable_space_labels':0,'unmetered_labels':0}
    (reports/'label_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    return panel
