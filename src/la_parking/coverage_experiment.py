"""Predeclared Census ablations on identical legacy targets; no model promotion."""
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits
from .census_coverage import ROOT, NEW
from .model_features import CALENDAR, calendar_features
from .modeling import utc, TARGETS
from .spatial_experiment import COLS, fit, predict, score, bootstrap
from .temporal_experiment import digest_rows, check_registered_inputs
from .http import utcnow

REPORT=Path('reports/modeling')
EXISTING=['housing_density','no_vehicle_fraction']


def columns(variant):
    return CALENDAR+([] if variant=='calendar' else EXISTING)+(NEW if variant=='additional_census' else [])


def regional_design(panel, horizon=60):
    """Identical arrival-window target and 25% support policy as the pilot."""
    f=panel[['block_face_id','block_id','region','source_month','panel_sensor_count','interval_start_utc']].copy()
    f['issued_at_utc']=f.interval_start_utc
    f['arrival_time_utc']=f.issued_at_utc+pd.Timedelta(minutes=horizon)
    target=panel[['source_month','block_face_id','interval_start_utc','occupancy_rate','coverage_fraction','panel_available_count','panel_any_vacant']].copy()
    target.loc[target.coverage_fraction.lt(.25),'occupancy_rate']=np.nan
    target=target.rename(columns={'interval_start_utc':'arrival_time_utc','occupancy_rate':'target_occupancy_rate','coverage_fraction':'target_coverage_fraction','panel_available_count':'target_available_count','panel_any_vacant':'target_any_panel_vacant'})
    f=f.merge(target,on=['source_month','block_face_id','arrival_time_utc'],how='left',validate='one_to_one')
    for c,v in calendar_features(f.arrival_time_utc).items():f[c]=v
    f['horizon_minutes']=horizon;f['spatial_role']='train'
    return f.drop(columns='interval_start_utc')


def folds(frame,cfg):
    for origin in cfg['rolling_origins_local']:
        boundary=utc(origin)
        past=frame.arrival_time_utc+pd.Timedelta('15min')<boundary-pd.Timedelta(minutes=cfg['embargo_minutes'])
        future=frame.issued_at_utc.ge(boundary)&frame.issued_at_utc.lt(boundary+pd.Timedelta(days=cfg['validation_days']))
        yield origin,'known_blocks',frame.loc[past],frame.loc[future]
        for region in sorted(frame.region.unique()):
            yield origin+'_'+region,'unseen_neighborhood',frame.loc[past&frame.region.ne(region)],frame.loc[future&frame.region.eq(region)]


def baseline(train,query,target,kind='weekhour'):
    col=TARGETS[target];mean=train[col].mean()
    if kind=='pooled':p=np.repeat(mean,len(query))
    else:
        def keys(f):
            local=f.arrival_time_utc.dt.tz_convert('America/Los_Angeles')
            return pd.MultiIndex.from_arrays([local.dt.dayofweek,local.dt.hour])
        t=pd.DataFrame({'y':train[col].to_numpy()},index=keys(train)).groupby(level=[0,1]).y.agg(['sum','count'])
        lookup=(t['sum']+50*mean)/(t['count']+50)
        p=lookup.reindex(keys(query)).fillna(mean).to_numpy()
    return np.clip(p,0,query.panel_sensor_count if target=='available_count' else 1)


def metrics(frame,p,target):
    y=frame[TARGETS[target]].to_numpy();m=score(y,p,target)
    m['macro_block_mse']=float(pd.DataFrame({'block':frame.block_id.to_numpy(),'se':(y-p)**2}).groupby('block').se.mean().mean())
    m.update(blocks=int(frame.block_id.nunique()),faces=int(frame.block_face_id.nunique()),row_sha256=digest_rows(frame,TARGETS[target]))
    return m


def legacy_masks(frame,cfg):
    end=utc(cfg['training_end_local'])-pd.Timedelta(minutes=cfg['embargo_minutes'])
    labelend=frame.arrival_time_utc+pd.Timedelta('15min')
    future=frame.issued_at_utc.ge(utc(cfg['legacy_test_start_local']))&labelend.lt(utc(cfg['legacy_test_end_local']))
    return {'unseen_block':frame.original_legacy_rows&frame.spatial_role.eq('test')&(labelend<end),
        'future_time_unseen':frame.spatial_role.eq('test')&future,
        'future_time_known':frame.spatial_role.eq('train')&frame.region.eq('Westwood')&future,
        'future_time_Downtown':frame.region.eq('Downtown')&future,
        'future_time_Hollywood':frame.region.eq('Hollywood')&future}


def run():
    cfg=json.loads(Path('config/coverage_v4.json').read_text());check_registered_inputs()
    if (REPORT/'coverage_v4_complete.json').exists():raise RuntimeError('Completed experiment frozen; register a new version')
    cfg['seed']=int(cfg['seed']);h=cfg['primary_horizon_minutes']
    old=pd.read_parquet('data/modeling/temporal_v2/legacy_enhanced.parquet',columns=COLS,filters=[('horizon_minutes','=',h)])
    extra=pd.read_parquet(f'data/modeling/temporal_v2/extended_h{h}.parquet',columns=COLS)
    old['region']='Westwood';extra['region']='Westwood'
    old['original_legacy_rows']=True;extra['original_legacy_rows']=False
    regional=pd.concat([regional_design(pd.read_parquet(ROOT/f'panel_{month}.parquet'),h) for month in cfg['sensor_archive_months']],ignore_index=True)
    regional['original_legacy_rows']=False
    context=pd.read_parquet('data/modeling/temporal_v2/context_asof.parquet')[['block_id','tract_id']]
    context=context.merge(pd.read_parquet(ROOT/'tract_features.parquet')[['tract_id']+EXISTING+NEW],on='tract_id',how='left',validate='many_to_one')
    context=pd.concat([context,pd.read_parquet(ROOT/'regional_census.parquet')[['block_id','tract_id']+EXISTING+NEW]],ignore_index=True)
    if context.block_id.duplicated().any():raise ValueError('Duplicate block context')
    allrows=pd.concat([old,extra,regional],ignore_index=True).merge(context,on='block_id',how='left',validate='many_to_one')
    # Source release precedes every issue time; do not backfill before availability.
    allrows.loc[allrows.issued_at_utc<utc(cfg['census_feature_available_at_utc']),EXISTING+NEW]=np.nan
    if allrows.duplicated(['source_month','block_face_id','issued_at_utc']).any():raise ValueError('Duplicate target lineage')
    development=allrows.loc[allrows.spatial_role.eq('train')].reset_index(drop=True)
    masks=legacy_masks(allrows,cfg)
    reference=json.loads((REPORT/'temporal_v2_results.json').read_text())
    # Fail before fitting if acquisition/reporting changes the original benchmark.
    for axis in ['unseen_block','future_time_unseen']:
        for target,col in TARGETS.items():
            held=allrows.loc[masks[axis]&allrows[col].notna()]
            ref=next(r for r in reference if r['horizon']==h and r['target']==target and r['axis']==axis and r['variant']=='frozen_v1_boosted')
            if len(held)!=ref['n'] or digest_rows(held,col)!=ref['row_sha256']:raise ValueError('Original legacy target preflight failed')
    allrows.to_parquet(ROOT/'design.parquet',index=False)
    protocol={'registered_at_utc':utcnow(),'config_sha256':hashlib.sha256(Path('config/coverage_v4.json').read_bytes()).hexdigest(),
        'inputs_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'design.parquet',ROOT/'tract_features.parquet']},
        'methods':'Fixed ExtraTrees; calendar / existing ACS / additional ACS. Training-only pooled/weekhour baselines. No own histories or IDs enter transferable models. Known-block temporal-v2 is retained separately.',
        'regression_selection':'Geographic+chronological validation MSE per target; known-block chronological validation reported separately',
        'probability_selection':'Separate validation Brier objective; chronological calibration Aug17-21; calibration transfer to unseen geography remains unvalidated',
        'untouched_holdouts_opened':False,'models_promoted':False}
    (REPORT/'coverage_v4_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    records=[];pairs={};variants=cfg['variants']+['pooled_mean','weekhour']
    with threadpool_limits(limits=2):
        for name,axis,tr,va in folds(development,cfg):
            print('Validation',name,axis,flush=True)
            for target,col in TARGETS.items():
                train=tr.loc[tr[col].notna()].reset_index(drop=True);val=va.loc[va[col].notna()].reset_index(drop=True)
                if len(train)<50 or len(val)<10:continue
                for variant in variants:
                    if variant in cfg['variants']:
                        b=fit(train,target,columns(variant),'extra_trees',cfg['fixed_extra_trees'],cfg);p=predict(b,val)
                    else:p=baseline(train,val,target,'pooled' if variant=='pooled_mean' else 'weekhour')
                    records.append({'fold':name,'axis':axis,'variant':variant,'target':target,'train_n':len(train),**metrics(val,p,target)})
                    key=(axis,target,variant);r=val[['block_face_id','block_id','issued_at_utc','arrival_time_utc',col]].copy();r['prediction']=p;pairs.setdefault(key,[]).append(r)
        validation=[]
        for (axis,target,variant),parts in pairs.items():
            frame=pd.concat(parts,ignore_index=True);validation.append({'axis':axis,'target':target,'variant':variant,**metrics(frame,frame.prediction.to_numpy(),target)})
        selected={target:min([r for r in validation if r['axis']=='unseen_neighborhood' and r['target']==target and r['variant'] in cfg['variants']],key=lambda r:r['brier_score'] if target=='any_panel_vacant' else r['rmse'])['variant'] for target in TARGETS}
        # Freeze choices before opening legacy diagnostics.
        (REPORT/'coverage_v4_selections.json').write_text(json.dumps({'selected':selected,'validation':validation,'folds':records},indent=2),encoding='utf8')
        end=utc(cfg['training_end_local'])-pd.Timedelta(minutes=cfg['embargo_minutes'])
        results=[];predictions=[];artifacts=Path('artifacts/models/coverage_v4');artifacts.mkdir(parents=True,exist_ok=True)
        for target,col in TARGETS.items():
            train=development.loc[(development.arrival_time_utc+pd.Timedelta('15min')<end)&development[col].notna()].reset_index(drop=True)
            for variant in variants:
                print('Legacy',target,variant,flush=True)
                b=None
                if variant in cfg['variants']:
                    b=fit(train,target,columns(variant),'extra_trees',cfg['fixed_extra_trees'],cfg)
                    cal=development.loc[development.issued_at_utc.ge(utc('2026-08-17'))&(development.arrival_time_utc+pd.Timedelta('15min')<utc('2026-08-21'))&development[col].notna()].reset_index(drop=True)
                    if target=='any_panel_vacant' and len(cal)>=20 and cal[col].nunique()==2:
                        raw=predict(b,cal);z=np.log(np.clip(raw,1e-6,1-1e-6)/(1-np.clip(raw,1e-6,1-1e-6))).reshape(-1,1)
                        b['calibrator']=LogisticRegression(C=1).fit(z,cal[col])
                    joblib.dump(b,artifacts/f'{target}_{variant}.joblib')
                for axis,mask in masks.items():
                    f=allrows.loc[mask&allrows[col].notna()].reset_index(drop=True)
                    if not len(f):continue
                    p=predict(b,f) if b else baseline(train,f,target,'pooled' if variant=='pooled_mean' else 'weekhour')
                    m=metrics(f,p,target)
                    if target!='any_panel_vacant':m.update(bootstrap(f,f[col].to_numpy(),p,cfg['seed']))
                    results.append({'axis':axis,'variant':variant,'target':target,'selected_for_target':variant==selected[target],
                        'candidate_rows':int(mask.sum()),'coverage':len(f)/max(1,int(mask.sum())),**m})
                    f=f[['block_face_id','block_id','issued_at_utc','arrival_time_utc',col]].copy();f['prediction']=p;f['variant']=variant;f['axis']=axis;f['target']=target;predictions.append(f)
    # Explicitly compare original Westwood target identity; no easier rows selected.
    for row in results:
        if row['axis'] not in ['unseen_block','future_time_unseen']:continue
        ref=next(r for r in reference if r['horizon']==h and r['target']==row['target'] and r['axis']==row['axis'] and r['variant']=='frozen_v1_boosted')
        if row['row_sha256']!=ref['row_sha256'] or row['n']!=ref['n']:raise ValueError('Original legacy targets changed')
    (REPORT/'coverage_v4_results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    pd.DataFrame(results).to_csv(REPORT/'coverage_v4_experiments.csv',index=False);pd.concat(predictions,ignore_index=True).to_parquet(ROOT/'predictions.parquet',index=False)
    coverage=allrows.groupby('region').agg(blocks=('block_id','nunique'),faces=('block_face_id','nunique'),candidate_rows=('block_id','size'),rate_rows=('target_occupancy_rate','count'),count_rows=('target_available_count','count'))
    feature_coverage=context.groupby(context.block_id.isin(set(regional.block_id)).map({True:'new_regions',False:'Westwood'}))[EXISTING+NEW].agg(['count','size'])
    completion={'completed_at_utc':utcnow(),'selected':selected,'legacy_rows_match_v1_v2':True,'labels_or_expiry_changed':False,'untouched_holdouts_opened':False,'models_promoted':False,'unmetered_labels':0,'coverage':coverage.reset_index().to_dict('records'),'feature_coverage':json.loads(feature_coverage.to_json())}
    (REPORT/'coverage_v4_complete.json').write_text(json.dumps(completion,indent=2),encoding='utf8')
    return results
