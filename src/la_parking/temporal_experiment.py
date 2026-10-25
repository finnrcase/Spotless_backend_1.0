"""Versioned, row-paired temporal experiments. Never overwrites the v1 service."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits
from .model_features import CALENDAR,HISTORY,calendar_features
from .modeling import utc,prep_scenario,predict_head,PooledMean,TARGETS
from .evaluation import regression_metrics,probability_metrics
from .temporal_features import OWN,PATTERNS,TrainingPatterns,add_dynamic
from .temporal_predictors import HOUSING,JOBS,asof_context

ROOT=Path('data/modeling/temporal_v2'); REPORT=Path('reports/modeling')
NEW=CALENDAR+HISTORY+OWN+PATTERNS+['v2_neighbor_300','v2_neighbor_600']
VARIANTS=['rmse_original_grid','pooled_face_patterns','causal_temporal','consecutive_history','broader_tuning','asof_context','without_housing','without_jobs']
INPUT_COLUMNS=list(dict.fromkeys(['block_face_id','block_id','issued_at_utc','arrival_time_utc','horizon_minutes','source_month','spatial_role','area',
    'panel_sensor_count','target_occupancy_rate','target_available_count','target_any_panel_vacant','target_coverage_fraction']+CALENDAR+HISTORY+OWN+
    [f'{name}_{radius}' for name in ['neighbor_all','neighbor_train_only','v2_neighbor_all','v2_neighbor_train'] for radius in [300,600]]))
INPUT_COLUMNS=[c for c in INPUT_COLUMNS if c not in ['neighbor_rate_300','neighbor_rate_600']]


def digest_rows(frame,col):
    keys=['block_face_id','issued_at_utc','arrival_time_utc',col]
    return hashlib.sha256(pd.util.hash_pandas_object(frame[keys],index=False).values.tobytes()).hexdigest()


def check_registered_inputs():
    protocol=json.loads(Path('reports/modeling/temporal_v2_protocol.json').read_text())
    if hashlib.sha256(Path('config/temporal_v2.json').read_bytes()).hexdigest()!=protocol['config_sha256']:
        raise ValueError('Experiment configuration differs from the registered protocol')
    for name,expected in protocol['legacy_fingerprints'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Frozen legacy input changed: '+name)
    return protocol


def extra_design(horizon,legacy):
    path=ROOT/f'extended_h{horizon}.parquet'
    if path.exists():return pd.read_parquet(path)
    ctx=pd.read_parquet('data/modeling/current_context.parquet');hist=[pd.read_parquet(ROOT/'history_legacy.parquet')]
    for month in ['2026_06','2026_07']:
        print('Design',horizon,month,flush=True)
        p=ROOT/f'history_{month}.parquet'
        if p.exists():hist.append(pd.read_parquet(p))
    history=pd.concat(hist,ignore_index=True);parts=[]
    split=json.loads(Path('reports/modeling/spatial_split.json').read_text())
    for month in ['2026_06','2026_07']:
        pathpanel=ROOT/f'panel_{month}.parquet'
        if not pathpanel.exists():continue
        p=pd.read_parquet(pathpanel);p=p.merge(ctx,left_on='block_id',right_on='segment_id',validate='many_to_one')
        p['spatial_role']=np.where(p.block_id.isin(split['test_blocks']),'test',np.where(p.block_id.isin(split['train_blocks']),'train','buffer'))
        p['issued_at_utc']=p.interval_start_utc;p['arrival_time_utc']=p.issued_at_utc+pd.Timedelta(minutes=horizon)
        target=p[['block_face_id','interval_start_utc','occupancy_rate','coverage_fraction','panel_available_count','panel_any_vacant']].rename(columns={
            'interval_start_utc':'arrival_time_utc','occupancy_rate':'target_occupancy_rate','coverage_fraction':'target_coverage_fraction','panel_available_count':'target_available_count','panel_any_vacant':'target_any_panel_vacant'})
        p=p.merge(target,on=['block_face_id','arrival_time_utc'],how='left',validate='one_to_one')
        p.loc[p.target_coverage_fraction<.25,'target_occupancy_rate']=np.nan;p['horizon_minutes']=horizon
        for col in HISTORY:p[col]=np.nan
        cf=calendar_features(p.arrival_time_utc)
        for col in CALENDAR:p[col]=cf[col].to_numpy()
        p=add_dynamic(p,history,ctx)
        # Same causal dynamic definitions for added months; legacy rows remain unchanged.
        for radius in [300,600]:p[f'v2_neighbor_all_{radius}']=p[f'v2_neighbor_{radius}']
        train_only=add_dynamic(p[['block_face_id','block_id','issued_at_utc','arrival_time_utc']],history,ctx,set(split['train_blocks']))
        for radius in [300,600]:
            p[f'v2_neighbor_train_{radius}']=train_only[f'v2_neighbor_{radius}'].to_numpy()
            p[f'neighbor_train_only_{radius}']=p[f'v2_neighbor_train_{radius}']
            p[f'neighbor_all_{radius}']=p[f'v2_neighbor_all_{radius}']
        h=history.set_index(['block_face_id','interval_start_utc'])
        for lag in [15,30,60]:
            ix=pd.MultiIndex.from_arrays([p.block_face_id,p.issued_at_utc-pd.Timedelta(minutes=lag)]);p[f'lag_rate_{lag}']=h.history_rate.reindex(ix).to_numpy()
        ix=pd.MultiIndex.from_arrays([p.block_face_id,p.issued_at_utc-pd.Timedelta('15min')]);p['lag_coverage']=h.coverage_fraction.reindex(ix).to_numpy()
        for name in ['arrivals','departures']:p[name+'_60']=p.groupby('block_face_id')[name].transform(lambda x:x.shift(1).rolling(4,min_periods=1).sum())
        p['occupancy_week_ago']=p.own_previous_week
        p['hour_x_lag']=p.hour_sin*p.lag_rate_15
        parts.append(p)
    added=pd.concat(parts,ignore_index=True) if parts else legacy.iloc[:0]
    added.to_parquet(path,index=False);return added


def prepare(frame,axis):
    f=prep_scenario(frame,axis)
    role='all' if axis=='known_blocks' else 'train'
    # prep_scenario uses its old spelling; restore known-block histories explicitly.
    if axis=='known_blocks':f=prep_scenario(frame,'future_time')
    else:
        for col in OWN:f[col]=np.nan
    for radius in [300,600]:
        f[f'v2_neighbor_{radius}']=f[f'v2_neighbor_{role}_{radius}']
        # Added months have the same completed-bin neighborhood source.
        m=f.source_month.isin(['2026_06','2026_07']);f.loc[m,f'neighbor_rate_{radius}']=f.loc[m,f'v2_neighbor_{radius}']
    return f


def candidates(variant,cfg):
    if variant=='pooled_face_patterns':return [('pattern',{'strength':s}) for s in cfg['pattern_shrinkage_strengths']]
    broad=variant in ['broader_tuning','asof_context','without_housing','without_jobs']
    ridge=cfg['ridge_alpha'] if broad else [1,10,100]
    boosted=cfg['boosted_candidates'] if broad else [dict(max_leaf_nodes=n,learning_rate=.06,max_iter=100,l2_regularization=10,min_samples_leaf=40) for n in [7,15]]
    return [('ridge',{'alpha':a}) for a in ridge]+[('boosted',b) for b in boosted]


def features_for(variant):
    if variant=='rmse_original_grid':return CALENDAR+HISTORY
    cols=NEW.copy()
    if variant in ['asof_context','without_jobs']:cols+=HOUSING
    if variant in ['asof_context','without_housing']:cols+=JOBS
    return cols


def pattern_pair(train,query,strength=50,unseen=False):
    patterns=TrainingPatterns(strength).fit(train)
    result=[]
    for frame in [train,query]:
        frame=frame.reset_index(drop=True).copy();enc=patterns.transform(frame,unseen=unseen)
        for col in PATTERNS:frame[col]=enc[col].to_numpy()
        result.append(frame)
    return result


def fit_model(train,target,kind,param,features,cfg):
    y=train[TARGETS[target]].to_numpy();columns=list(dict.fromkeys(features+(['panel_sensor_count'] if target!='occupancy_rate' else [])))
    if kind=='pattern':return {'kind':kind,'model':None,'features':columns,'target':target,'parameter':param}
    if target=='any_panel_vacant' and len(np.unique(y))<2:return {'kind':'constant','model':float(y.mean()),'features':columns,'target':target}
    if kind=='ridge':
        est=LogisticRegression(C=1/param['alpha'],max_iter=500,random_state=cfg['seed']) if target=='any_panel_vacant' else Ridge(alpha=param['alpha'])
        model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),est)
    else:
        cls=HistGradientBoostingClassifier if target=='any_panel_vacant' else HistGradientBoostingRegressor
        model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),cls(**param,early_stopping=False,random_state=cfg['seed']))
    model.fit(train[columns],y)
    return {'kind':kind,'model':model,'features':columns,'target':target,'parameter':param}


def predict(bundle,frame,calibrated=False):
    target=bundle['target'];kind=bundle['kind']
    if kind=='constant':p=np.full(len(frame),bundle['model'])
    elif kind=='pattern':p=frame.hist_face_weekhour_mean.fillna(frame.hist_global_mean).to_numpy()
    elif target=='any_panel_vacant':p=bundle['model'].predict_proba(frame[bundle['features']])[:,1]
    else:p=bundle['model'].predict(frame[bundle['features']])
    maximum=frame.panel_sensor_count.to_numpy() if target=='available_count' else 1
    p=np.clip(p,0,maximum)
    if calibrated and bundle.get('calibrator') is not None:
        z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1)
        p=bundle['calibrator'].predict_proba(z)[:,1]
    if not np.isfinite(p).all():raise ValueError('Missing predictions; retain all fixed evaluation rows')
    return p


def folds(frame,cfg):
    for boundary in cfg['rolling_origins_local']:
        origin=utc(boundary);end=frame.arrival_time_utc+pd.Timedelta('15min')
        train=frame.loc[end<origin-pd.Timedelta(minutes=cfg['embargo_minutes'])].reset_index(drop=True)
        val=frame.loc[(frame.issued_at_utc>=origin)&(frame.issued_at_utc<origin+pd.Timedelta(days=cfg['rolling_validation_days']))].reset_index(drop=True)
        yield str(origin),train,val


def tune_variant(frame,variant,axis,cfg,target='occupancy_rate'):
    col=TARGETS[target];frame=frame.loc[frame[col].notna()].reset_index(drop=True);cols=features_for(variant)
    options=candidates(variant,cfg);scores=[];preds={i:[] for i in range(len(options))}
    fold_cache={}
    for origin,tr,va in folds(frame,cfg):
        if len(tr)<50 or len(va)<20:continue
        # Rate encodings use only fold-local rate labels, even for auxiliary heads.
        strengths=cfg['pattern_shrinkage_strengths'] if variant=='pooled_face_patterns' else [50]
        for strength in strengths:fold_cache[(origin,strength)]=pattern_pair(tr,va,strength,axis!='known_blocks')
        for i,(kind,param) in enumerate(options):
            strength=param.get('strength',50);train,val=fold_cache[(origin,strength)]
            bundle=fit_model(train,target,kind,param,cols,cfg);p=predict(bundle,val);y=val[col].to_numpy()
            m=probability_metrics(y,p) if target=='any_panel_vacant' else regression_metrics(y,p)
            scores.append({'candidate':i,'kind':kind,'parameter':param,'origin':origin,'train_n':len(train),**m})
            preds[i].append((y,p))
    loss={}
    for i,parts in preds.items():
        if parts:
            y=np.concatenate([v[0] for v in parts]);p=np.concatenate([v[1] for v in parts]);loss[i]=float(np.mean((y-p)**2))
    if not loss:raise ValueError('No chronological validation support')
    best=min(loss,key=loss.get);y=np.concatenate([v[0] for v in preds[best]]);p=np.concatenate([v[1] for v in preds[best]])
    validation=probability_metrics(y,p) if target=='any_panel_vacant' else regression_metrics(y,p)
    return options[best],validation,scores


def paired_interval(frame,y,new,old,cfg):
    """Paired physical-block/day cluster bootstrap, conditional on these labels."""
    group=frame.block_id.astype(str)+'|'+frame.arrival_time_utc.dt.tz_convert('America/Los_Angeles').dt.strftime('%Y-%m-%d')
    g=pd.DataFrame({'group':group.to_numpy(),'n':1,'sy':y,'sy2':y*y,'new':(y-new)**2,'old':(y-old)**2}).groupby('group').sum()
    a=g.to_numpy();rng=np.random.default_rng(cfg['seed']);values=[]
    for _ in range(cfg['bootstrap_replicates']):
        n,sy,sy2,se_new,se_old=a[rng.integers(0,len(a),len(a))].sum(axis=0);sst=sy2-sy*sy/n
        if sst>0:values.append((se_old-se_new)/sst)
    return {'paired_delta_r2_95pct':np.quantile(values,[.025,.975]).tolist(),'clusters':len(g),'method':'physical-block/local-day bootstrap; conditional on proxy labels, not sensor truth or citywide accuracy'}


def baseline_rows(data,original,masks,axis,horizon,cfg):
    col=TARGETS['occupancy_rate'];rows=[]
    for kind in ['time_week','pooled','persistence']:
        ys=[];ps=[]
        for _,train,val in folds(data.loc[data[col].notna()],cfg):
            model=PooledMean(face=kind!='time_week' and axis=='known_blocks').fit(train,train[col]);p=model.predict(val)
            if kind=='persistence':p=np.where(val.lag_rate_15.notna(),val.lag_rate_15,p)
            ys.extend(val[col]);ps.extend(p)
        validation=regression_metrics(ys,ps)
        train=data.loc[(data.arrival_time_utc+pd.Timedelta('15min')<utc(cfg['training_end_local'])-pd.Timedelta(minutes=cfg['embargo_minutes']))&data[col].notna()]
        model=PooledMean(face=kind!='time_week' and axis=='known_blocks').fit(train,train[col])
        for name,mask in masks.items():
            held=original.loc[mask&original[col].notna()];p=model.predict(held)
            persistence_fraction=float(held.lag_rate_15.notna().mean()) if kind=='persistence' else None
            if kind=='persistence':p=np.where(held.lag_rate_15.notna(),held.lag_rate_15,p)
            rows.append({'horizon':horizon,'axis':name,'variant':'baseline_'+kind,'target':'occupancy_rate','validation_rmse':validation['rmse'],'validation_r2':validation['r2'],'validation_mae':validation['mae'],'validation_n':validation['n'],**regression_metrics(held[col],p),'blocks':int(held.block_id.nunique()),'faces':int(held.block_face_id.nunique()),'candidate_rows':int(mask.sum()),'coverage':len(held)/max(1,mask.sum()),'row_sha256':digest_rows(held,col),'persistence_direct_fraction':persistence_fraction})
    return rows


def run(horizons=None,resume=False,report_directory=None):
    global REPORT
    if report_directory is not None:REPORT=Path(report_directory)
    REPORT.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(Path('config/temporal_v2.json').read_text());out=Path('artifacts/models/temporal_v2');out.mkdir(parents=True,exist_ok=True)
    # Never silently reselect after a completed run / legacy inspection.
    if (REPORT/'temporal_v2_complete.json').exists():raise RuntimeError('Completed experiment exists. Use its reports; register a new protocol before new selection.')
    check_registered_inputs()
    context=pd.read_parquet(ROOT/'context_asof.parquet')
    horizons=cfg['horizons_minutes'] if horizons is None else horizons
    prediction_path=ROOT/('predictions.parquet' if report_directory is None else 'predictions_'+REPORT.name+'.parquet')
    if not set(horizons)<=set(cfg['horizons_minutes']):raise ValueError('Unregistered horizon')
    completed=set(cfg['horizons_minutes'])-set(horizons)
    def restore(name):
        path=REPORT/name
        return [r for r in json.loads(path.read_text()) if r['horizon'] in completed] if resume and path.exists() else []
    results=restore('temporal_v2_results.json');tuning=[];selections=[];predictions=[]
    if resume:
        for name,destination in [('temporal_v2_tuning.json',tuning),('temporal_v2_selections.json',selections)]:
            destination.extend(json.loads((REPORT/name).read_text()))
    prior_selections={(s['horizon'],s['axis'],s['variant']):s for s in selections}
    if resume and prediction_path.exists():
        p=pd.read_parquet(prediction_path);predictions.append(p.loc[p.horizon_minutes.isin(completed)])
    end=utc(cfg['training_end_local']);teststart=utc(cfg['legacy_test_start_local']);testend=utc(cfg['legacy_test_end_local']);embargo=pd.Timedelta(minutes=cfg['embargo_minutes'])
    lock={'registered_before_fits_utc':datetime.now(timezone.utc).isoformat(),'protocol_sha256':hashlib.sha256(Path('config/temporal_v2.json').read_bytes()).hexdigest(),
        'variants':VARIANTS,'selection':'pooled chronological squared error; binary Brier separately','unseen_validation':'chronological folds restricted to south training geography; north never used for tuning. Unseen-block validation not independently estimated.',
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'new_holdout_opened':False}
    if resume:
        lock['prior_run']=json.loads((REPORT/'temporal_v2_run_protocol.json').read_text())
        lock['continuation']='Read one horizon and required columns at a time; trim unused pattern source columns. No feature, split, candidate or objective changes. Prior completed horizon retained.'
    (REPORT/'temporal_v2_run_protocol.json').write_text(json.dumps(lock,indent=2))
    with threadpool_limits(limits=2):
      for horizon in horizons:
        legacy=pd.read_parquet(ROOT/'legacy_enhanced.parquet',columns=INPUT_COLUMNS,filters=[('horizon_minutes','=',horizon)]).reset_index(drop=True)
        legacy=asof_context(legacy,context)
        extra=asof_context(extra_design(horizon,legacy)[INPUT_COLUMNS],context)
        for axis in ['known_blocks','unseen_blocks']:
            original=prepare(legacy,axis);added=prepare(extra,axis)
            region=original.spatial_role.eq('train') if axis!='known_blocks' else pd.Series(True,index=original.index)
            base=original.loc[region].reset_index(drop=True)
            extended=pd.concat([base,added.loc[added.spatial_role.eq('train')] if axis!='known_blocks' else added],ignore_index=True)
            col=TARGETS['occupancy_rate'];labelend=original.arrival_time_utc+pd.Timedelta('15min')
            # Frozen v1 known-block membership, even if expanded history adds faces.
            oldtrain=base.loc[base.arrival_time_utc+pd.Timedelta('15min')<end-embargo]
            masks={'future_time_known':(original.issued_at_utc>=teststart)&(labelend<testend)&original.block_id.isin(set(oldtrain.block_id))} if axis=='known_blocks' else {
                'unseen_block':(labelend<end-embargo)&original.spatial_role.eq('test'),
                'future_time_unseen':(original.issued_at_utc>=teststart)&(labelend<testend)&original.spatial_role.eq('test')}
            legacy_axis='future_time' if axis=='known_blocks' else 'unseen_area'
            frozen=joblib.load(Path('artifacts/models')/f'{legacy_axis}_h{horizon}_occupancy_rate_boosted.joblib')
            frozen_p={name:predict_head(frozen,original.loc[mask&original[col].notna()]) for name,mask in masks.items()}
            results.extend(baseline_rows(base,original,masks,axis,horizon,cfg))
            for name,mask in masks.items():
                held=original.loc[mask&original[col].notna()];m=regression_metrics(held[col],frozen_p[name])
                results.append({'horizon':horizon,'axis':name,'variant':'frozen_v1_boosted','target':'occupancy_rate',**m,'blocks':int(held.block_id.nunique()),'faces':int(held.block_face_id.nunique()),'candidate_rows':int(mask.sum()),'coverage':len(held)/max(1,mask.sum()),'row_sha256':digest_rows(held,col)})
            for variant in VARIANTS:
                print('Tune',horizon,axis,variant,flush=True)
                data=extended if variant in VARIANTS[3:] else base
                model_path=out/f'{axis}_h{horizon}_{variant}.joblib'
                cached=prior_selections.get((horizon,axis,variant)) if model_path.exists() else None
                if cached:
                    selected=cached['selection'];validation=cached['validation'];print('Reuse completed choice/model',horizon,axis,variant,flush=True)
                else:
                    selected,validation,trials=tune_variant(data,variant,axis,cfg)
                    tuning.extend([{'horizon':horizon,'axis':axis,'variant':variant,**r} for r in trials])
                    # Persist validation-only decision BEFORE evaluating legacy rows.
                    record={'horizon':horizon,'axis':axis,'variant':variant,'selection':selected,'validation':validation}
                    selections.append(record);(REPORT/'temporal_v2_selections.json').write_text(json.dumps(selections,indent=2))
                train=data.loc[(data.arrival_time_utc+pd.Timedelta('15min')<end-embargo)&data[col].notna()].reset_index(drop=True)
                query=original.reset_index(drop=True);strength=selected[1].get('strength',50)
                tr,query=pattern_pair(train,query,strength,axis!='known_blocks')
                if cached:bundle=joblib.load(model_path)
                else:
                    bundle=fit_model(tr,'occupancy_rate',*selected,features_for(variant),cfg)
                    bundle.update(training_patterns=TrainingPatterns(strength).fit(train),scope='metered sensor-panel proxy; legacy benchmark only',available_features=features_for(variant),version=cfg['version'])
                    joblib.dump(bundle,model_path)
                for name,mask in masks.items():
                    held=query.loc[mask.to_numpy()&query[col].notna().to_numpy()].reset_index(drop=True);p=predict(bundle,held);y=held[col].to_numpy();m=regression_metrics(y,p)
                    m.update(paired_interval(held,y,p,frozen_p[name],cfg))
                    results.append({'horizon':horizon,'axis':name,'variant':variant,'target':'occupancy_rate','validation_rmse':validation['rmse'],'validation_r2':validation['r2'],'validation_mae':validation['mae'],'validation_n':validation['n'],
                        **m,'blocks':int(held.block_id.nunique()),'faces':int(held.block_face_id.nunique()),'candidate_rows':int(masks[name].sum()),'coverage':len(held)/max(1,masks[name].sum()),'row_sha256':digest_rows(held,col),'train_n':len(train),'population':'metered_sensor_panel','unmetered_validated':False})
                    saved=held[['block_face_id','block_id','issued_at_utc','arrival_time_utc','horizon_minutes','target_coverage_fraction']].copy();saved['actual']=y;saved['prediction']=p;saved['variant']=variant;saved['axis']=name;predictions.append(saved)
                (REPORT/'temporal_v2_results.json').write_text(json.dumps(results,indent=2))
                pd.DataFrame(tuning).to_json(REPORT/'temporal_v2_tuning.json',orient='records',indent=2)
            # Auxiliary count and probability heads: separate selection objectives.
            auxiliary(extended,original,masks,axis,horizon,cfg,results,selections,out)
        pd.DataFrame([{k:v for k,v in r.items() if k!='paired_delta_r2_95pct'} for r in results]).to_csv(REPORT/'temporal_v2_experiments.csv',index=False)
        pd.concat(predictions,ignore_index=True).to_parquet(prediction_path,index=False)
    if set(horizons)==set(cfg['horizons_minutes']):
        add_block_uncertainty(results,pd.concat(predictions,ignore_index=True))
        package_auxiliary_patterns(cfg)
        write_catalog(selections)
    (REPORT/'temporal_v2_results.json').write_text(json.dumps(results,indent=2))
    pd.DataFrame(results).to_csv(REPORT/'temporal_v2_experiments.csv',index=False)
    completion={'completed_at_utc':datetime.now(timezone.utc).isoformat(),'completed_horizons':horizons,'new_holdout_opened':False,'test_status':'legacy; not fresh','selected_by':'validation MSE only; binary Brier separate','unmetered_labels':0,'models_promoted_to_service':False}
    (REPORT/'temporal_v2_complete.json').write_text(json.dumps(completion,indent=2));write_report(results,cfg)
    family_validation(tuning,selections)
    return results


def collate(parts):
    """Merge disjoint horizon runs without re-selection, re-fitting, or averaging scores."""
    global REPORT
    REPORT=Path('reports/modeling');check_registered_inputs()
    results=[];choices=[];trials=[];protocols=[];predictions=[]
    for directory,horizons in parts:
        directory=Path(directory)
        for filename,dest in [('temporal_v2_results.json',results),('temporal_v2_selections.json',choices),('temporal_v2_tuning.json',trials)]:
            dest.extend(r for r in json.loads((directory/filename).read_text()) if r['horizon'] in horizons)
        protocols.append(json.loads((directory/'temporal_v2_run_protocol.json').read_text()))
        prediction_path=ROOT/('predictions.parquet' if directory==REPORT else 'predictions_'+directory.name+'.parquet')
        p=pd.read_parquet(prediction_path);predictions.append(p.loc[p.horizon_minutes.isin(horizons)])
    all_predictions=pd.concat(predictions,ignore_index=True)
    add_block_uncertainty(results,all_predictions)
    frame=pd.DataFrame(results)
    for row in results:
        if row['variant']=='frozen_v1_boosted' and row['target']!='occupancy_rate':
            # New-head validation/calibration diagnostics do not describe v1.
            for field in ['validation_rmse','validation_brier','uncalibrated_brier']:row[field]=None
    frame=pd.DataFrame(results)
    if set(frame.horizon)!={0,15,30,60,120} or frame.duplicated(['horizon','axis','variant','target']).any():raise ValueError('Incomplete or overlapping horizon runs')
    for name,destination in [('temporal_v2_results.json',results),('temporal_v2_selections.json',choices),('temporal_v2_tuning.json',trials)]:
        (REPORT/name).write_text(json.dumps(destination,indent=2),encoding='utf8')
    frame.drop(columns=['paired_delta_r2_95pct'],errors='ignore').to_csv(REPORT/'temporal_v2_experiments.csv',index=False)
    all_predictions.to_parquet(ROOT/'predictions.parquet',index=False)
    cfg=json.loads(Path('config/temporal_v2.json').read_text());write_report(results,cfg)
    family_validation(trials,choices)
    manifest={'completed_at_utc':datetime.now(timezone.utc).isoformat(),'new_holdout_opened':False,'unmetered_labels':0,'models_promoted_to_service':False,
        'test_status':'previously inspected legacy benchmark','selection':'chronological validation MSE; probability Brier separate','horizon_partitions':[(str(p),h) for p,h in parts],
        'run_protocols':protocols,'code_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/la_parking').glob('temporal_*.py')}}
    (REPORT/'temporal_v2_complete.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    package_auxiliary_patterns(cfg)
    write_catalog(choices)
    return results


def write_catalog(choices):
    catalog=[]
    for choice in choices:
        variant=choice['variant'];head=variant.removeprefix('auxiliary_')
        file=f"{choice['axis']}_h{choice['horizon']}_{head}.joblib";path=Path('artifacts/models/temporal_v2')/file
        if not path.exists():raise ValueError('Missing fitted model: '+file)
        catalog.append({'file':file,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**choice,
            'scope':'Westwood metered sensor-panel replay proxy','unmetered_validated':False,'full_curb_suitability_validated':False,'service_promoted':False})
    Path('artifacts/models/temporal_v2/catalog.json').write_text(json.dumps(catalog,indent=2),encoding='utf8')
    return catalog


def add_block_uncertainty(results,predictions):
    """Also resample entire blocks, retaining all days within each sampled block."""
    cfg=json.loads(Path('config/temporal_v2.json').read_text());keys=['block_face_id','issued_at_utc','arrival_time_utc']
    lookup={(r['horizon'],r['axis'],r['variant']):r for r in results if r['target']=='occupancy_rate'}
    for horizon,groups in predictions.groupby('horizon_minutes'):
        source=pd.read_parquet(ROOT/'legacy_enhanced.parquet',columns=INPUT_COLUMNS,filters=[('horizon_minutes','=',int(horizon))]);source=source.loc[source.target_occupancy_rate.notna()]
        for mode in ['known_blocks','unseen_blocks']:
            f=prepare(source,mode);old_axis='future_time' if mode=='known_blocks' else 'unseen_area'
            b=joblib.load(Path('artifacts/models')/f'{old_axis}_h{horizon}_occupancy_rate_boosted.joblib')
            old=f[keys].copy();old['old_prediction']=predict_head(b,f)
            chosen=groups.loc[groups.axis.eq('future_time_known')] if mode=='known_blocks' else groups.loc[~groups.axis.eq('future_time_known')]
            joined=chosen.merge(old,on=keys,how='left',validate='many_to_one')
            if joined.old_prediction.isna().any():raise ValueError('Missing paired v1 reference')
            for (axis,variant),g in joined.groupby(['axis','variant']):
                a=pd.DataFrame({'block':g.block_id,'n':1,'sy':g.actual,'sy2':g.actual**2,'new':(g.actual-g.prediction)**2,'old':(g.actual-g.old_prediction)**2}).groupby('block').sum().to_numpy()
                rng=np.random.default_rng(cfg['seed']);values=[]
                for _ in range(cfg['bootstrap_replicates']):
                    n,sy,sy2,se_new,se_old=a[rng.integers(0,len(a),len(a))].sum(axis=0);sst=sy2-sy*sy/n
                    if sst>0:values.append((se_old-se_new)/sst)
                row=lookup[(int(horizon),axis,variant)];row.update(paired_delta_r2_block_95pct=np.quantile(values,[.025,.975]).tolist(),
                    block_bootstrap_n_blocks=len(a),block_bootstrap_undefined_draws=cfg['bootstrap_replicates']-len(values),
                    block_uncertainty_note='Whole physical blocks resampled, all their days retained. Few blocks and cross-block dependence limit this descriptive interval; no sensor-validity or citywide claim.')


def package_auxiliary_patterns(cfg):
    """Add inference metadata to auxiliary bundles; estimators/choices stay unchanged."""
    columns=['block_face_id','issued_at_utc','arrival_time_utc','spatial_role','target_occupancy_rate','target_available_count','target_any_panel_vacant']
    for horizon in cfg['horizons_minutes']:
        legacy=pd.read_parquet(ROOT/'legacy_enhanced.parquet',columns=columns,filters=[('horizon_minutes','=',horizon)])
        extra=pd.read_parquet(ROOT/f'extended_h{horizon}.parquet',columns=columns)
        data=pd.concat([legacy,extra],ignore_index=True)
        train=data.loc[data.arrival_time_utc+pd.Timedelta('15min')<utc(cfg['training_end_local'])-pd.Timedelta(minutes=cfg['embargo_minutes'])]
        for axis in ['known_blocks','unseen_blocks']:
            region=train if axis=='known_blocks' else train.loc[train.spatial_role.eq('train')]
            for target in ['available_count','any_panel_vacant']:
                path=Path('artifacts/models/temporal_v2')/f'{axis}_h{horizon}_{target}.joblib';bundle=joblib.load(path)
                if 'training_patterns' not in bundle:
                    bundle.update(training_patterns=TrainingPatterns(50).fit(region.loc[region[TARGETS[target]].notna()]),
                        version=cfg['version'],scope='metered sensor-panel proxy; not full-curb suitability or unmetered validation',
                        metadata_packaging='Pattern source retained for inference; fitted estimator and calibrator unchanged.')
                    joblib.dump(bundle,path)


def family_validation(trials,choices):
    best=[]
    frame=pd.DataFrame(trials)
    frame['parameter_json']=frame.parameter.map(lambda x:json.dumps(x,sort_keys=True))
    for keys,g in frame.groupby(['horizon','axis','variant','kind']):
        candidates=[]
        for parameter,rows in g.groupby('parameter_json'):
            n=rows.n.sum();rmse=float(np.sqrt(np.sum(rows.n*rows.rmse**2)/n));mae=float(np.sum(rows.n*rows.mae)/n)
            candidates.append({'horizon':keys[0],'axis':keys[1],'variant':keys[2],'model_family':keys[3],'parameter':parameter,'validation_rmse':rmse,'validation_mae':mae,'validation_n':int(n)})
        best.append(min(candidates,key=lambda r:r['validation_rmse']))
    pd.DataFrame(best).to_csv(REPORT/'temporal_v2_family_validation.csv',index=False)


def auxiliary(data,original,masks,axis,horizon,cfg,results,selections,out):
    end=utc(cfg['training_end_local'])-pd.Timedelta(minutes=cfg['embargo_minutes']);cols=features_for('asof_context')
    for target in ['available_count','any_panel_vacant']:
        col=TARGETS[target];print('Auxiliary',horizon,axis,target,flush=True)
        selected,val,trials=tune_variant(data,'asof_context',axis,cfg,target)
        selections.append({'horizon':horizon,'axis':axis,'variant':'auxiliary_'+target,'selection':selected,'validation':val});(REPORT/'temporal_v2_selections.json').write_text(json.dumps(selections,indent=2))
        train=data.loc[(data.arrival_time_utc+pd.Timedelta('15min')<end)&data[col].notna()].reset_index(drop=True)
        tr,query=pattern_pair(train,original,50,axis!='known_blocks');bundle=fit_model(tr,target,*selected,cols,cfg)
        cal=query.loc[(query.issued_at_utc>=utc(cfg['calibration_start_local']))&(query.arrival_time_utc+pd.Timedelta('15min')<utc(cfg['calibration_end_local']))&query[col].notna()]
        if axis!='known_blocks':cal=cal.loc[cal.spatial_role.eq('train')]
        calibrator=None;radius=None
        if len(cal)>=20:
            p=predict(bundle,cal)
            if target=='any_panel_vacant' and cal[col].nunique()==2:
                z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1);calibrator=LogisticRegression().fit(z,cal[col])
            elif target=='available_count':radius=float(np.quantile(np.abs(cal[col]-p),min(1,np.ceil((len(cal)+1)*.9)/len(cal)),method='higher'))
        bundle.update(calibrator=calibrator,conformal_radius=radius,training_patterns=TrainingPatterns(50).fit(train),version=cfg['version'],scope='metered sensor-panel proxy only')
        joblib.dump(bundle,out/f'{axis}_h{horizon}_{target}.joblib')
        legacy_axis='future_time' if axis=='known_blocks' else 'unseen_area'
        old=joblib.load(Path('artifacts/models')/f'{legacy_axis}_h{horizon}_{target}_boosted.joblib')
        for name,mask in masks.items():
            held=query.loc[mask.to_numpy()&query[col].notna().to_numpy()].reset_index(drop=True)
            if not len(held):continue
            raw=predict(bundle,held);p=raw
            if calibrator is not None:
                z=np.log(np.clip(raw,1e-6,1-1e-6)/(1-np.clip(raw,1e-6,1-1e-6))).reshape(-1,1);p=calibrator.predict_proba(z)[:,1]
            metric=probability_metrics if target=='any_panel_vacant' else regression_metrics
            for variant,pr in [('frozen_v1_boosted',predict_head(old,held)),('asof_context_auxiliary',p)]:
                m=metric(held[col],pr)
                if radius is not None and variant!='frozen_v1_boosted':m['interval_coverage_90pct']=float(((held[col]>=np.maximum(0,pr-radius))&(held[col]<=np.minimum(held.panel_sensor_count,pr+radius))).mean())
                results.append({'horizon':horizon,'axis':name,'variant':variant,'target':target,**m,'blocks':int(held.block_id.nunique()),'faces':int(held.block_face_id.nunique()),'candidate_rows':int(mask.sum()),'coverage':len(held)/max(1,mask.sum()),'row_sha256':digest_rows(held,col),'validation_rmse':val.get('rmse') if variant!='frozen_v1_boosted' else None,'validation_brier':val.get('brier_score') if variant!='frozen_v1_boosted' else None,'uncalibrated_brier':float(np.mean((held[col]-raw)**2)) if target=='any_panel_vacant' and variant!='frozen_v1_boosted' else None})


def write_report(results,cfg):
    rows=[r for r in results if r['horizon']==60 and r['target']=='occupancy_rate']
    lines=['# Temporal v2: fixed-target legacy benchmark','',
        'All numeric results below concern partial metered sensor panels in Westwood. The August 25–31 test was already inspected before this experiment. It is a legacy benchmark, not an untouched test. No unmetered accuracy or citywide accuracy is validated. The 15-minute label policy and exact evaluation rows are unchanged.','',
        'Selection uses pooled chronological validation squared error (RMSE below), never legacy-test R². The northern geographic holdout is never used for tuning. Its validation score is temporal validation within the southern training geography, not a measured unseen-block validation score.','',
        '| Evaluation | Change | Validation RMSE | Legacy R² | Legacy RMSE | Legacy MAE | n / blocks | Label coverage |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        fmt=lambda v:'—' if v is None else f'{v:.4f}'
        lines.append(f"| {r['axis']} | {r['variant']} | {fmt(r.get('validation_rmse'))} | {fmt(r['r2'])} | {fmt(r['rmse'])} | {fmt(r['mae'])} | {r['n']} / {r['blocks']} | {r['coverage']:.1%} |")
    lines+=['','All five horizons, count heads, probability reliability bins, paired block/day bootstrap intervals, fixed-row hashes and candidate metrics are in the companion CSV/JSON. Bootstrap intervals are conditional on the uncertain sensor labels. They do not measure sensor accuracy.','',
        'The new September 21–30 archive holdout remains unopened and is not yet published in the checked official catalog. Lock all choices before its first evaluation. November 7–14 manual sessions and entirely new blocks are reserved prospectively, with no observations yet.','',
        'Remaining gaps: no independent sensor truth, no verified reporting heartbeat/SLA or historical sensor relocation map, no unmetered occupancy labels, no historically complete legal curb supply/sign rules, no pre-issue business/event versions. Housing/vehicles/employment are demand predictors only. Models are saved separately and are not automatically promoted into the app.']
    lines+=['','## Known blocks across horizons','','Lowest validation RMSE across the declared comparisons; no legacy metric selects the row. Whole-block intervals resample all days of each physical block together. Few blocks and neighboring-block dependence still limit interpretation.','',
        '| Minutes | Validation-selected comparison | Validation RMSE | V1 legacy R² | Selected legacy R² | Selected legacy MAE | n / blocks | Paired ΔR² 95% whole-block interval |','|---:|---|---:|---:|---:|---:|---:|---|']
    for horizon in cfg['horizons_minutes']:
        candidates=[r for r in results if r['horizon']==horizon and r['axis']=='future_time_known' and r['target']=='occupancy_rate']
        eligible=[r for r in candidates if r.get('validation_rmse') is not None]
        if not eligible:continue
        chosen=min(eligible,key=lambda r:r['validation_rmse']);old=next(r for r in candidates if r['variant']=='frozen_v1_boosted');interval=chosen.get('paired_delta_r2_block_95pct');ci='not computed' if interval is None else f'[{interval[0]:.3f}, {interval[1]:.3f}]'
        lines.append(f"| {horizon} | {chosen['variant']} | {chosen['validation_rmse']:.4f} | {old['r2']:.4f} | {chosen['r2']:.4f} | {chosen['mae']:.4f} | {chosen['n']} / {chosen['blocks']} | {ci} |")
    lines+=['','## Changes and evidence gaps','','| Variant | Implemented change | Remaining gap |','|---|---|---|',
        '| rmse_original_grid | Original features/grid; select on squared error | Sparse histories and uncertain labels |',
        '| pooled_face_patterns | Training-only face/hour/day/week-hour shrinkage | Few repeated days per block |',
        '| causal_temporal | Day/week lags, rolling trends, age and quality, expanding training-only patterns | Event delivery assumed immediate |',
        '| consecutive_history | June and July added with the same candidate grid | Reporting roster churn; historical mapping unverified |',
        '| broader_tuning | Wider Ridge and boosted complexity/learning/regularization settings | Two validation origins; selection uncertainty |',
        '| asof_context | Housing, vehicle ownership, employment with publication gates | No verified legal supply or historical business/events |',
        '| without_housing / without_jobs | Demand-family ablations | Demand predictors do not supply missing occupancy truth |',
        '', 'All test metrics are conditional on the fixed 15-minute label policy. The pure unseen-block axis overlaps historical training dates and is retrospective geographic transfer, not future-time validation. The future/unseen axis tests both together. Geographic tuning uses chronological folds inside the training geography; independent unseen-block validation remains unavailable.',
        '', '**Sensor availability limitation:** histories are causal by event time assuming immediate delivery. Monthly archive publication lags two months; actual historical live-feed delivery was not recorded. These benchmarks do not validate an archive-only operational pipeline.',
        '', '## Complete-panel count at 60 minutes','','| Axis | Version | Validation RMSE | Legacy R² | Legacy MAE | n / blocks | Label coverage |','|---|---|---:|---:|---:|---:|---:|']
    fmt=lambda v:'—' if v is None else f'{v:.4f}'
    for r in results:
        if r['horizon']==60 and r['target']=='available_count':lines.append(f"| {r['axis']} | {r['variant']} | {fmt(r.get('validation_rmse'))} | {fmt(r['r2'])} | {fmt(r['mae'])} | {r['n']} / {r['blocks']} | {r['coverage']:.1%} |")
    lines+=['','## Complete-panel vacancy probability at 60 minutes','','This binary target is at least one monitored bay vacant, not at least one legally suitable full-curb space. Calibration is fitted separately; reliability bins and sample sizes are in temporal_v2_results.json.','',
        '| Axis | Version | Validation Brier | Legacy Brier | ECE | n / blocks | Label coverage |','|---|---|---:|---:|---:|---:|---:|']
    for r in results:
        if r['horizon']==60 and r['target']=='any_panel_vacant':lines.append(f"| {r['axis']} | {r['variant']} | {fmt(r.get('validation_brier'))} | {fmt(r['brier_score'])} | {fmt(r['ece'])} | {r['n']} / {r['blocks']} | {r['coverage']:.1%} |")
    lines+=['','## Unmetered and next observations','','Unmetered held-out n = 0; R², MAE, count accuracy and suitable-space calibration are unavailable. Metered training benefit on unmetered observations remains untested. The existing unmetered-only versus mixed workflow is preserved.','',
        'Start the eight-count development batch using the field-route button, export/import and review it. Add independent metered bay checks to investigate sensor validity. Keep whole reserved blocks and November 7–14 sessions untouched. Wait for the reserved September archive, then lock the model before its first evaluation. No purchase, key or public deployment is needed.']
    (REPORT/'TEMPORAL_V2.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
