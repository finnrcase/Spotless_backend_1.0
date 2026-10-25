"""As-of sensor predictors and fold-local, expanding historical pattern features.

Feature-only pre-discovery reconstructions are usable only after roster discovery.
They never replace the frozen v1 targets. Unknown sensor-time remains missing.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .temporal import intervals

OWN=['own_lag_rate','own_rate_1h','own_rate_6h','own_rate_24h','own_trend_1h','own_trend_6h',
    'own_coverage_1h','own_coverage_6h','own_coverage_24h','own_previous_day','own_previous_week',
    'own_previous_day_quality','own_previous_week_quality','own_youngest_report_minutes','own_median_report_minutes',
    'own_oldest_report_minutes','own_fresh_sensor_fraction','own_unknown_state_fraction','own_no_report_fraction']
PATTERNS=['hist_global_mean','hist_face_mean','hist_face_hour_mean','hist_face_dow_mean','hist_face_weekhour_mean',
    'hist_face_count','hist_face_hour_count','hist_face_weekhour_count','hist_face_age_days']


def history_grid(events,mapping,start,end,roster_available):
    """Feature-only grid with exactly the v1 known-second arithmetic."""
    start,end,roster_available=map(pd.Timestamp,[start,end,roster_available])
    if any(t.tzinfo is None for t in [start,end,roster_available]):raise ValueError('Aware history boundaries required')
    events=events.copy();events['observed_at_utc']=pd.to_datetime(events.observed_at_utc,utc=True).astype('datetime64[ns, UTC]')
    ids=set(events.loc[events.observed_at_utc<roster_available,'space_id'])
    m=mapping.loc[mapping.join_status.eq('matched')&mapping.space_id.isin(ids)].copy()
    if m.space_id.duplicated().any():raise ValueError('Ambiguous sensor mapping')
    faces=sorted(m.block_face_id.unique());face_index={f:i for i,f in enumerate(faces)}
    bins=pd.date_range(start,end,freq='15min',inclusive='left').tz_convert('UTC');n=len(bins)
    known=np.zeros((len(faces),n));occupied=np.zeros_like(known)
    e=events.merge(m[['space_id','block_face_id']],on='space_id',validate='many_to_one')
    iv=intervals(e,15,window_end=end);iv=iv.loc[iv.known].merge(m[['space_id','block_face_id']],on='space_id')
    origin=start.timestamp();a=np.maximum(origin,iv.observed_at_utc.astype('int64').to_numpy()/1e9)
    b=np.minimum(end.timestamp(),iv.valid_to_utc.astype('int64').to_numpy()/1e9);valid=b>a
    a,b=a[valid],b[valid];fi=iv.loc[valid,'block_face_id'].map(face_index).to_numpy();oc=iv.loc[valid,'state'].eq('OCCUPIED').to_numpy()
    first=np.floor((a-origin)/900).astype(int);last=np.ceil((b-origin)/900).astype(int)-1
    overlap=np.minimum(b,origin+(first+1)*900)-a
    np.add.at(known,(fi,first),overlap);np.add.at(occupied,(fi,first),overlap*oc)
    second=last>first
    if second.any():
        amount=b[second]-(origin+last[second]*900)
        np.add.at(known,(fi[second],last[second]),amount);np.add.at(occupied,(fi[second],last[second]),amount*oc[second])
    rows=[]
    for face in faces:
        index=face_index[face];sensors=m.loc[m.block_face_id.eq(face),'space_id'];capacity=len(sensors)
        k=known[index];o=occupied[index];rate=np.divide(o,k,out=np.full(n,np.nan),where=k>0)
        frame=pd.DataFrame({'block_face_id':face,'interval_start_utc':bins,'known_seconds':k,'occupied_seconds':o,
            'coverage_fraction':k/(900*capacity),'history_rate':rate,'roster_available_at_utc':roster_available,'usable_as_target':False})
        frame['own_lag_rate']=rate
        for length,label in [(4,'1h'),(24,'6h'),(96,'24h')]:
            kk=pd.Series(k).rolling(length,min_periods=1).sum();oo=pd.Series(o).rolling(length,min_periods=1).sum()
            frame['own_rate_'+label]=oo.div(kk.where(kk>0)).to_numpy()
            frame['own_coverage_'+label]=(kk/(900*capacity*length)).to_numpy()
        frame['own_trend_1h']=frame.own_rate_1h-frame.own_rate_1h.shift(4)
        frame['own_trend_6h']=frame.own_rate_1h-frame.own_rate_6h
        origins=(bins+pd.Timedelta('15min')).asi8
        ages=[];states=[]
        for sensor in sensors:
            q=events.loc[events.space_id.eq(sensor)].drop_duplicates(['observed_at_utc','state']).sort_values('observed_at_utc').copy()
            conflicts=q.groupby('observed_at_utc').state.transform('nunique').gt(1);q.loc[conflicts,'state']='UNKNOWN';q=q.drop_duplicates('observed_at_utc')
            times=q.observed_at_utc.astype('int64').to_numpy();idx=np.searchsorted(times,origins,side='right')-1
            age=np.where(idx>=0,(origins-times[np.maximum(idx,0)])/60e9,np.nan)
            state=np.where(idx>=0,q.state.to_numpy()[np.maximum(idx,0)],'UNKNOWN')
            ages.append(age);states.append(state)
        age=np.array(ages);state=np.array(states);reported=np.isfinite(age)
        # No report is a separate quality state; do not turn NaN into age zero.
        frame['own_youngest_report_minutes']=pd.DataFrame(age).min(axis=0).to_numpy()
        frame['own_median_report_minutes']=pd.DataFrame(age).median(axis=0).to_numpy()
        frame['own_oldest_report_minutes']=pd.DataFrame(age).max(axis=0).to_numpy()
        frame['own_fresh_sensor_fraction']=((age<=15)&reported&(state!='UNKNOWN')).mean(axis=0)
        frame['own_unknown_state_fraction']=((state=='UNKNOWN')&reported).mean(axis=0)
        frame['own_no_report_fraction']=(~reported).mean(axis=0)
        rows.append(frame)
    return pd.concat(rows,ignore_index=True) if rows else pd.DataFrame()


def previous_local_time(times,days):
    times=pd.to_datetime(times,utc=True)
    # DateOffset preserves local clock time across DST; no UTC 24h substitution.
    if isinstance(times,pd.DatetimeIndex):times=pd.Series(times)
    naive=times.dt.tz_convert('America/Los_Angeles').dt.tz_localize(None)-pd.DateOffset(days=days)
    return naive.dt.tz_localize('America/Los_Angeles',ambiguous='NaT',nonexistent='NaT').dt.tz_convert('UTC')


def add_dynamic(frame,history,context,training_blocks=None,unseen=False):
    f=frame.copy();h=history.set_index(['block_face_id','interval_start_utc'])
    key=pd.MultiIndex.from_arrays([f.block_face_id,f.issued_at_utc-pd.Timedelta('15min')])
    cols=[c for c in OWN if c in history]
    values=h[cols+['roster_available_at_utc']].reindex(key);available=values.roster_available_at_utc.to_numpy()<=f.issued_at_utc.to_numpy()
    for col in cols:f[col]=np.where(available,values[col].to_numpy(),np.nan)
    for days,label in [(1,'day'),(7,'week')]:
        when=previous_local_time(f.arrival_time_utc,days)
        ix=pd.MultiIndex.from_arrays([f.block_face_id,when]);rows=h[['history_rate','coverage_fraction','roster_available_at_utc']].reindex(ix)
        safe=(when+pd.Timedelta('15min')<=f.issued_at_utc).to_numpy()&(rows.roster_available_at_utc.to_numpy()<=f.issued_at_utc.to_numpy())
        f['own_previous_'+label]=np.where(safe,rows.history_rate.to_numpy(),np.nan)
        f['own_previous_'+label+'_quality']=np.where(safe,rows.coverage_fraction.to_numpy(),np.nan)
    ctx=context.set_index('segment_id')
    # Neighbor signals are from completed intervals only. Held-out blocks are never sources.
    signals=history.copy();signals['issued_at_utc']=signals.interval_start_utc+pd.Timedelta('15min')
    signals.loc[signals.issued_at_utc<signals.roster_available_at_utc,'history_rate']=np.nan
    mapping=f[['block_face_id','block_id']].drop_duplicates().set_index('block_face_id').block_id
    if mapping.index.duplicated().any():raise ValueError('Conflicting physical block lineage')
    for radius in [300,600]:
        f[f'v2_neighbor_{radius}']=np.nan
        for month,g in signals.groupby(signals.interval_start_utc.dt.strftime('%Y-%m')):
            wide=g.pivot(index='issued_at_utc',columns='block_face_id',values='history_rate')
            face_to_block={face:face.rsplit(':',1)[0] for face in wide.columns}
            blocks=np.array([face_to_block[face] for face in wide.columns]);xy=ctx.loc[blocks,['x','y']].to_numpy()
            distances=np.linalg.norm(xy[:,None,:]-xy[None,:,:],axis=2)
            weights=(distances<=radius)&(blocks[:,None]!=blocks[None,:])
            if training_blocks is not None:weights&=np.isin(blocks,list(training_blocks))[None,:]
            a=wide.to_numpy();valid=np.isfinite(a);denom=valid.astype(float)@weights.T
            p=np.divide(np.nan_to_num(a)@weights.T,denom,out=np.full_like(a,np.nan),where=denom>0)
            index=pd.MultiIndex.from_product([wide.index,wide.columns]);lookup=pd.Series(p.ravel(),index=index)
            mask=f.issued_at_utc.dt.strftime('%Y-%m').eq(month)
            keys=pd.MultiIndex.from_arrays([f.loc[mask,'issued_at_utc'],f.loc[mask,'block_face_id']]);f.loc[mask,f'v2_neighbor_{radius}']=lookup.reindex(keys).to_numpy()
    if unseen:
        for col in OWN:f[col]=np.nan
    return f


def _cumulative_lookup(source,query,by):
    group=by+['label_available_at_utc'];s=source.groupby(group,dropna=False).target_occupancy_rate.agg(['sum','count']).reset_index()
    s=s.sort_values(by+['label_available_at_utc'])
    if by:s[['sum','count']]=s.groupby(by,dropna=False)[['sum','count']].cumsum()
    else:s[['sum','count']]=s[['sum','count']].cumsum()
    left=query[by+['issued_at_utc']].copy();left['_row']=np.arange(len(left))
    joined=pd.merge_asof(left.sort_values('issued_at_utc'),s.sort_values('label_available_at_utc'),
        left_on='issued_at_utc',right_on='label_available_at_utc',by=by or None,direction='backward')
    return joined.sort_values('_row').reset_index(drop=True)


class TrainingPatterns:
    """Fold-local target encodings, causal even on the training rows themselves."""
    def __init__(self,strength=50):self.strength=strength
    @staticmethod
    def keys(frame):
        f=frame.copy();local=f.arrival_time_utc.dt.tz_convert('America/Los_Angeles')
        f['_hour']=local.dt.hour.astype('int64');f['_dow']=local.dt.dayofweek.astype('int64')
        return f
    def fit(self,train):
        # Keep only the sufficient statistics' inputs, not every raw/context column.
        source=self.keys(train[['block_face_id','arrival_time_utc','issued_at_utc','target_occupancy_rate']])
        source['label_available_at_utc']=source.arrival_time_utc+pd.Timedelta('15min')
        self.source=source.loc[source.target_occupancy_rate.notna()].copy()
        return self
    def transform(self,query,unseen=False):
        q=self.keys(query);out=pd.DataFrame(index=q.index)
        global_stat=_cumulative_lookup(self.source,q,[])
        global_mean=(global_stat['sum']/global_stat['count']).fillna(.5).to_numpy()
        out['hist_global_mean']=global_mean
        groups=[('face',['block_face_id']),('face_hour',['block_face_id','_hour']),('face_dow',['block_face_id','_dow']),('face_weekhour',['block_face_id','_dow','_hour'])]
        face_prior=global_mean
        for name,keys in groups:
            stat=_cumulative_lookup(self.source,q,keys);count=stat['count'].fillna(0).to_numpy();sums=stat['sum'].fillna(0).to_numpy()
            prior=face_prior if name!='face' else global_mean
            mean=(sums+self.strength*prior)/(count+self.strength)
            out['hist_'+name+'_mean']=mean
            if name in ['face','face_hour','face_weekhour']:out['hist_'+name+'_count']=count
            if name=='face':
                face_prior=mean;out['hist_face_age_days']=(q.issued_at_utc.reset_index(drop=True)-stat.label_available_at_utc).dt.total_seconds().to_numpy()/86400
        if unseen:
            for col in PATTERNS:
                if col!='hist_global_mean':out[col]=np.nan
        return out


def build_legacy_features():
    """Build new predictors beside, never over, the original design/targets."""
    output=Path('data/modeling/temporal_v2');output.mkdir(parents=True,exist_ok=True)
    source=pd.read_parquet('data/modeling/design.parquet');frames=[]
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet')
    panel=pd.read_parquet('data/modeling/panel_intervals.parquet')
    for month in ['2025_09','2026_08']:
        events=pd.read_parquet(f'data/processed/pilot_history_{month}.parquet')
        year,number=map(int,month.split('_'));start=pd.Timestamp(year=year,month=number,day=1,tz='America/Los_Angeles');end=start+pd.DateOffset(months=1)
        print('Feature history',month,flush=True)
        history=history_grid(events,mapping,start,end,start+pd.DateOffset(days=7));history['source_month']=month;frames.append(history)
        old=panel.loc[panel.source_month.eq(month)].merge(history,on=['block_face_id','interval_start_utc'],suffixes=('_v1','_v2'),validate='one_to_one')
        np.testing.assert_allclose(old.known_seconds_v1,old.known_seconds_v2,atol=.001,rtol=0)
        np.testing.assert_allclose(old.occupancy_rate,old.history_rate,equal_nan=True,atol=1e-7,rtol=0)
    history=pd.concat(frames,ignore_index=True);history.to_parquet(output/'history_legacy.parquet',index=False)
    context=pd.read_parquet('data/modeling/current_context.parquet')
    enhanced=add_dynamic(source,history,context)
    for radius in [300,600]:enhanced[f'v2_neighbor_all_{radius}']=enhanced[f'v2_neighbor_{radius}']
    split=json.loads(Path('reports/modeling/spatial_split.json').read_text())
    training_only=add_dynamic(source[['block_face_id','block_id','issued_at_utc','arrival_time_utc']],history,context,set(split['train_blocks']))
    for radius in [300,600]:enhanced[f'v2_neighbor_train_{radius}']=training_only[f'v2_neighbor_{radius}'].to_numpy()
    for target in ['target_occupancy_rate','target_available_count','target_any_panel_vacant','target_coverage_fraction']:
        np.testing.assert_allclose(enhanced[target],source[target],equal_nan=True)
    enhanced.to_parquet(output/'legacy_enhanced.parquet',index=False)
    report={'rows':len(enhanced),'targets_unchanged':True,'legacy_design_sha256':hashlib.sha256(Path('data/modeling/design.parquet').read_bytes()).hexdigest(),
        'features':OWN+['v2_neighbor_all_300','v2_neighbor_all_600','v2_neighbor_train_300','v2_neighbor_train_600'],
        'pattern_features':PATTERNS,'pattern_fit':'computed separately from training rows within each chronological fold; training encodings are expanding/as-of',
        'history_assumption':'event-time causal under immediate delivery replay; actual feed delivery/latency unverified',
        'pre_discovery_history':'feature-only; usable only after roster discovery. Never trained/scored as new labels.',
        'unmetered_support':False,'new_holdout_opened':False}
    Path('reports/modeling/temporal_v2_features.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print('Feature rows',len(enhanced),'frozen targets preserved',flush=True)
    return enhanced
