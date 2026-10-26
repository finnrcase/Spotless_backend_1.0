"""Inner geographic + rolling temporal selection, with fixed legacy diagnostics."""
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone
import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier,ExtraTreesRegressor,ExtraTreesClassifier
from threadpoolctl import threadpool_limits
from .model_features import CALENDAR
from .modeling import utc,TARGETS
from .evaluation import regression_metrics,probability_metrics
from .temporal_experiment import digest_rows,check_registered_inputs
from .transfer_context import ROOT,enrich,HOUSING_FEATURES,EMPLOYMENT,GEOMETRY

REPORT=Path('reports/modeling');NEIGHBORS=['transfer_neighbor_300','transfer_neighbor_600','transfer_neighbor_count_300','transfer_neighbor_count_600']
COLS=['block_face_id','block_id','issued_at_utc','arrival_time_utc','source_month','horizon_minutes','spatial_role','panel_sensor_count','target_occupancy_rate','target_available_count','target_any_panel_vacant','target_coverage_fraction']+CALENDAR


def columns(variant):
    mapping={'calendar':CALENDAR,'plus_neighbors':CALENDAR+NEIGHBORS,'plus_housing':CALENDAR+NEIGHBORS+HOUSING_FEATURES,
        'plus_workplaces':CALENDAR+NEIGHBORS+HOUSING_FEATURES+EMPLOYMENT,'plus_geometry':CALENDAR+NEIGHBORS+HOUSING_FEATURES+EMPLOYMENT+GEOMETRY,
        'minus_neighbors':CALENDAR+HOUSING_FEATURES+EMPLOYMENT+GEOMETRY,'minus_housing':CALENDAR+NEIGHBORS+EMPLOYMENT+GEOMETRY,
        'minus_workplaces':CALENDAR+NEIGHBORS+HOUSING_FEATURES+GEOMETRY}
    return mapping[variant]


class NeighborHistory:
    def __init__(self,history,context):
        h=history.copy();h['issue']=h.interval_start_utc+pd.Timedelta('15min')
        h.loc[h.issue<h.roster_available_at_utc,'history_rate']=np.nan
        self.wide=h.pivot(index='issue',columns='block_face_id',values='history_rate').sort_index()
        self.blocks=np.array([f.rsplit(':',1)[0] for f in self.wide.columns]);ctx=context.set_index('segment_id')
        self.xy=ctx.loc[self.blocks,['x','y']].to_numpy();self.cache={}
    def transform(self,frame,allowed_blocks):
        key=tuple(sorted(allowed_blocks))
        if key not in self.cache:
            a=self.wide.to_numpy();valid=np.isfinite(a);dist=np.linalg.norm(self.xy[:,None,:]-self.xy[None,:,:],axis=2);out={}
            for radius in [300,600]:
                weights=(dist<=radius)&(self.blocks[:,None]!=self.blocks[None,:])&np.isin(self.blocks,list(allowed_blocks))[None,:]
                n=valid.astype(float)@weights.T;value=np.divide(np.nan_to_num(a)@weights.T,n,out=np.full_like(a,np.nan),where=n>0)
                ix=pd.MultiIndex.from_product([self.wide.index,self.wide.columns]);out['transfer_neighbor_'+str(radius)]=pd.Series(value.ravel(),index=ix)
                out['transfer_neighbor_count_'+str(radius)]=pd.Series(n.ravel(),index=ix)
            self.cache[key]=out
        index=pd.MultiIndex.from_arrays([frame.issued_at_utc,frame.block_face_id]);result=frame.copy()
        for col,lookup in self.cache[key].items():result[col]=lookup.reindex(index).to_numpy()
        return result


def model_choices(cfg):
    return [('ridge',{'alpha':a}) for a in cfg['ridge_alpha']]+[('boosted',v) for v in cfg['boosted_candidates']]+[('extra_trees',cfg['extra_trees'])]


def fit(train,target,features,kind,parameter,cfg):
    col=TARGETS[target];names=features+(['panel_sensor_count'] if target!='occupancy_rate' else []);y=train[col].to_numpy()
    bundle={'kind':kind,'parameter':parameter,'features':names,'target':target,'train_n':len(train)}
    if len(np.unique(y))==1:bundle.update(kind='constant',model=float(y[0]));return bundle
    if kind=='ridge':
        model=LogisticRegression(C=1/parameter['alpha'],max_iter=500,random_state=cfg['seed']) if target=='any_panel_vacant' else Ridge(alpha=parameter['alpha'])
        model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),model)
    else:
        if kind=='boosted':
            cls=HistGradientBoostingClassifier if target=='any_panel_vacant' else HistGradientBoostingRegressor
            est=cls(**parameter,early_stopping=False,random_state=cfg['seed'])
        else:
            cls=ExtraTreesClassifier if target=='any_panel_vacant' else ExtraTreesRegressor
            est=cls(**parameter,n_jobs=2,random_state=cfg['seed'])
        model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),est)
    bundle['model']=model.fit(train[names],y);return bundle


def predict(bundle,frame,calibrated=True):
    if bundle['kind']=='constant':p=np.repeat(bundle['model'],len(frame))
    elif bundle['target']=='any_panel_vacant':p=bundle['model'].predict_proba(frame[bundle['features']])[:,1]
    else:p=bundle['model'].predict(frame[bundle['features']])
    maximum=frame.panel_sensor_count.to_numpy() if bundle['target']=='available_count' else 1;p=np.clip(p,0,maximum)
    if calibrated and bundle.get('calibrator') is not None:
        z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1);p=bundle['calibrator'].predict_proba(z)[:,1]
    if not np.isfinite(p).all():raise ValueError('Every supported test target must receive a finite bounded prediction')
    return p


def folds(data,assignment,cfg):
    for origin in cfg['rolling_origins_local']:
        boundary=utc(origin);past=data.arrival_time_utc+pd.Timedelta('15min')<boundary-pd.Timedelta(minutes=cfg['embargo_minutes'])
        future=(data.issued_at_utc>=boundary)&(data.issued_at_utc<boundary+pd.Timedelta(days=cfg['validation_days']))
        for group in sorted(set(assignment.values())):
            held={b for b,v in assignment.items() if v==group}
            yield f'{origin}_geo{group}',held,data.loc[past&~data.block_id.isin(held)],data.loc[future&data.block_id.isin(held)]


def score(y,p,target):return probability_metrics(y,p) if target=='any_panel_vacant' else regression_metrics(y,p)


def tune(fold_data,features,target,cfg):
    trial=[];choices=model_choices(cfg);pooled={i:[] for i in range(len(choices))};col=TARGETS[target]
    for name,tr,va in fold_data:
        train=tr.loc[tr[col].notna()];val=va.loc[va[col].notna()]
        if len(train)<50 or len(val)<10:continue
        for i,(kind,param) in enumerate(choices):
            b=fit(train,target,features,kind,param,cfg);p=predict(b,val);y=val[col].to_numpy();metric=score(y,p,target)
            trial.append({'fold':name,'candidate':i,'kind':kind,'parameter':param,'train_n':len(train),'validation_blocks':val.block_id.nunique(),'row_sha256':digest_rows(val,col),**metric})
            pooled[i].append(pd.DataFrame({'actual':y,'prediction':p,'block_id':val.block_id.to_numpy()}))
    losses={i:float(np.mean((pd.concat(parts).actual-pd.concat(parts).prediction)**2)) for i,parts in pooled.items() if parts}
    if not losses:raise ValueError('Insufficient independent geographic/temporal validation targets')
    selected=min(losses,key=losses.get);pairs=pd.concat(pooled[selected],ignore_index=True);metric=score(pairs.actual,pairs.prediction,target)
    metric['macro_block_mse']=float(pairs.assign(error=(pairs.actual-pairs.prediction)**2).groupby('block_id').error.mean().mean())
    return choices[selected],metric,trial,pairs


def bootstrap(frame,y,p,seed=431):
    x=pd.DataFrame({'block':frame.block_id.to_numpy(),'n':1,'sy':y,'sy2':y*y,'se':(y-p)**2,'ae':np.abs(y-p)}).groupby('block').sum().to_numpy();values=[];rng=np.random.default_rng(seed)
    for _ in range(300):
        n,sy,sy2,se,ae=x[rng.integers(0,len(x),len(x))].sum(axis=0);sst=sy2-sy*sy/n
        if sst>0:values.append([1-se/sst,ae/n])
    return {'r2_block_95pct':np.quantile(np.array(values)[:,0],[.025,.975]).tolist(),'mae_block_95pct':np.quantile(np.array(values)[:,1],[.025,.975]).tolist(),'bootstrap_blocks':len(x),'uncertainty_note':'Physical-block bootstrap conditional on proxy labels; few blocks and geographic dependence limit inference.'}


def run():
    cfg=json.loads(Path('config/spatial_v3.json').read_text());check_registered_inputs()
    if (REPORT/'spatial_v3_complete.json').exists():raise RuntimeError('Completed experiment is frozen; register a new version before further tuning')
    horizon=cfg['primary_horizon_minutes'];base=pd.read_parquet('data/modeling/temporal_v2/legacy_enhanced.parquet',columns=COLS,filters=[('horizon_minutes','=',horizon)])
    extra=pd.read_parquet(f'data/modeling/temporal_v2/extended_h{horizon}.parquet',columns=COLS)
    # Unknown outcomes do not become labels. Candidate denominators remain in base.
    all_rows=pd.concat([base,extra],ignore_index=True);data=all_rows.loc[all_rows[list(TARGETS.values())].notna().any(axis=1)].reset_index(drop=True)
    data=enrich(data);legacy=enrich(base);ctx=pd.read_parquet('data/modeling/current_context.parquet');split=json.loads((REPORT/'spatial_split.json').read_text());allowed=set(split['train_blocks'])
    development=data.loc[data.spatial_role.eq('train')].reset_index(drop=True);blocks=sorted(development.block_id.unique());xy=ctx.set_index('segment_id').loc[blocks,['x','y']]
    clusters=KMeans(n_clusters=cfg['inner_geographic_clusters'],random_state=cfg['seed'],n_init=10).fit_predict(xy);assignment={b:int(v) for b,v in zip(blocks,clusters)}
    protocol={'registered_at_utc':datetime.now(timezone.utc).isoformat(),'config':cfg,'config_sha256':hashlib.sha256(Path('config/spatial_v3.json').read_bytes()).hexdigest(),'inner_geographic_blocks':assignment,
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'inputs_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('data/modeling/design.parquet'),Path('config/temporal_v2.json'),ROOT/'employment_context.parquet']},'reserved_outcomes_opened':False}
    (REPORT/'spatial_v3_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    history=pd.concat([pd.read_parquet('data/modeling/temporal_v2/history_legacy.parquet')]+[pd.read_parquet(f'data/modeling/temporal_v2/history_{m}.parquet') for m in ['2026_06','2026_07']],ignore_index=True)
    neighbor=NeighborHistory(history,ctx);fold_data=[]
    with threadpool_limits(limits=2):
        for name,held,tr,va in folds(development,assignment,cfg):
            print('Fold',name,'train blocks',tr.block_id.nunique(),'held-out blocks',va.block_id.nunique(),flush=True)
            fold_data.append((name,neighbor.transform(tr,allowed-held),neighbor.transform(va,allowed-held)))
        selected=[];trials=[];validation_pairs={}
        # All variant choices are fixed before any legacy diagnostics are computed.
        for variant in cfg['feature_variants']:
            print('Select',variant,flush=True);choice,m,records,pairs=tune(fold_data,columns(variant),'occupancy_rate',cfg)
            selected.append({'variant':variant,'target':'occupancy_rate','choice':choice,'validation':m});validation_pairs[variant]=pairs
            trials.extend([{'variant':variant,'target':'occupancy_rate',**r} for r in records]);(REPORT/'spatial_v3_selections.json').write_text(json.dumps(selected,indent=2),encoding='utf8')
        best=min(selected,key=lambda r:r['validation']['rmse'])['variant']
        for target in ['available_count','any_panel_vacant']:
            print('Select head',target,flush=True);choice,m,records,pairs=tune(fold_data,columns(best),target,cfg)
            selected.append({'variant':best,'target':target,'choice':choice,'validation':m});trials.extend([{'variant':best,'target':target,**r} for r in records])
        (REPORT/'spatial_v3_selections.json').write_text(json.dumps(selected,indent=2),encoding='utf8')
        (REPORT/'spatial_v3_validation.json').write_text(json.dumps(trials,indent=2),encoding='utf8')
        f=neighbor.transform(legacy,allowed);dev=neighbor.transform(development,allowed);labelend=f.arrival_time_utc+pd.Timedelta('15min');end=utc(cfg['training_end_local'])-pd.Timedelta(minutes=cfg['embargo_minutes'])
        masks={'unseen_block':(labelend<end)&f.spatial_role.eq('test'),'future_time_unseen':(f.issued_at_utc>=utc('2026-08-25'))&(labelend<utc('2026-09-01'))&f.spatial_role.eq('test')}
        results=[];prediction_rows=[];artifacts=Path('artifacts/models/spatial_v3');artifacts.mkdir(parents=True,exist_ok=True)
        for s in selected:
            target=s['target'];col=TARGETS[target];variant=s['variant'];train=dev.loc[(dev.arrival_time_utc+pd.Timedelta('15min')<end)&dev[col].notna()]
            b=fit(train,target,columns(variant),*s['choice'],cfg);b.update(model_version=cfg['version'],validation=s['validation'],scope='experimental Westwood metered sensor-panel transfer; not unmetered or citywide validation',allowed_neighbor_blocks=sorted(allowed),calibrator=None)
            cal=dev.loc[(dev.issued_at_utc>=utc(cfg['calibration_start_local']))&(dev.arrival_time_utc+pd.Timedelta('15min')<utc(cfg['calibration_end_local']))&dev[col].notna()]
            if target=='any_panel_vacant' and len(cal)>=20 and cal[col].nunique()==2:
                p=predict(b,cal,False);z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1);b['calibrator']=LogisticRegression(C=1).fit(z,cal[col])
            if target=='occupancy_rate':b['empirical_geographic_validation_radius_90']=float(np.quantile(np.abs(validation_pairs[variant].actual-validation_pairs[variant].prediction),.9))
            joblib.dump(b,artifacts/f'h{horizon}_{target}_{variant}.joblib')
            for axis,mask in masks.items():
                held=f.loc[mask&f[col].notna()].reset_index(drop=True);p=predict(b,held);y=held[col].to_numpy();m=score(y,p,target)
                if target!='any_panel_vacant':m.update(bootstrap(held,y,p,cfg['seed']))
                row={'variant':variant,'target':target,'horizon':horizon,'axis':axis,'population':'metered_sensor_panel','validation_rmse':s['validation'].get('rmse'),'validation_mae':s['validation'].get('mae'),'validation_r2':s['validation'].get('r2'),'validation_brier':s['validation'].get('brier_score'),**m,'blocks':int(held.block_id.nunique()),'faces':int(held.block_face_id.nunique()),'candidate_rows':int(mask.sum()),'coverage':len(held)/max(1,mask.sum()),'row_sha256':digest_rows(held,col),'retrospective_geometry_features':any(c in GEOMETRY for c in columns(variant)),'validation_selected_primary':variant==best,'new_holdout':False}
                results.append(row);pr=held[['block_face_id','block_id','issued_at_utc','arrival_time_utc']].copy();pr['actual']=y;pr['prediction']=p;pr['axis']=axis;pr['target']=target;pr['variant']=variant;prediction_rows.append(pr)
        (REPORT/'spatial_v3_results.json').write_text(json.dumps(results,indent=2),encoding='utf8');pd.DataFrame(results).to_csv(REPORT/'spatial_v3_experiments.csv',index=False)
        pd.concat(prediction_rows,ignore_index=True).to_parquet(ROOT/'predictions.parquet',index=False)
    # Verify identity against the existing diagnostic targets, not their scores.
    old=json.loads((REPORT/'temporal_v2_results.json').read_text())
    for r in results:
        reference=next(x for x in old if x['horizon']==horizon and x['axis']==r['axis'] and x['target']==r['target'] and x['variant']=='frozen_v1_boosted')
        if r['row_sha256']!=reference['row_sha256'] or r['n']!=reference['n']:raise ValueError('Evaluation identities/targets changed')
    completion={'completed_at_utc':datetime.now(timezone.utc).isoformat(),'primary_variant_selected_before_legacy_scoring':best,'new_holdouts_opened':False,'labels_or_expiry_changed':False,'test_rows_match_v1_v2':True,'unmetered_labels':0,'models_promoted':False}
    (REPORT/'spatial_v3_complete.json').write_text(json.dumps(completion,indent=2),encoding='utf8');report(results,completion)
    return results


def report(rows,completion):
    lines=['# Spatial transfer v3','','Selection uses joint rolling chronological and inner-geographic validation, holding both sides of complete development blocks out. North-area legacy outcomes were not used to select candidates. All targets and evaluation rows match v1/v2.','',
        'Primary 60-minute feature variant: **'+completion['primary_variant_selected_before_legacy_scoring']+'** (selected on validation RMSE before legacy scoring).','',
        '| Axis | Variant | Target | Geo/time validation RMSE | Legacy R² | Legacy MAE | Brier | n / blocks | Coverage |','|---|---|---|---:|---:|---:|---:|---:|---:|']
    fmt=lambda x:'—' if x is None else f'{x:.4f}'
    for r in rows:lines.append(f"| {r['axis']} | {r['variant']} | {r['target']} | {fmt(r.get('validation_rmse'))} | {fmt(r.get('r2'))} | {fmt(r.get('mae'))} | {fmt(r.get('brier_score'))} | {r['n']} / {r['blocks']} | {r['coverage']:.1%} |")
    lines+=['','Known-block results remain in TEMPORAL_V2.md; this experiment adds a distinct transferable model without own-face histories or identity encodings. Whole-block bootstrap intervals, probability calibration bins and ablations are in spatial_v3_results.json. New October 25-31 archive and November 15-21 manual reservations remain unopened, alongside earlier holdouts.','',
        'All numeric measurements are experimental metered-panel proxies in Westwood. Unmetered held-out n = 0; R², MAE and suitable-space probability calibration remain unavailable. Event-time replay assumes immediate delivery. Pure geographic results overlap historical training dates; only future_time_unseen measures forward-time transfer. Geographic probability calibration is not independently validated on new blocks.','',
        'Geometry features use the later October map and are a retrospective exploratory tier. Current business accounts are prospective predictors only; actual activity/hours, complete legal supply, posted restrictions and historical event information remain unavailable. Unknown rules do not mean unrestricted. No model was automatically activated in the app.']
    old=json.loads((REPORT/'temporal_v2_results.json').read_text())
    lines+=['','## Fixed-row references','','V2 selected features using chronological validation within the development geography. V3 uses geographic and chronological validation together, so validation scores are not directly interchangeable. No reference legacy score selected the new variant.','',
        '| Axis | Version | Target | R² | MAE | Brier | ECE | n |','|---|---|---|---:|---:|---:|---:|---:|']
    for axis in ['unseen_block','future_time_unseen']:
        for target in TARGETS:
            previous=[r for r in old if r['horizon']==60 and r['axis']==axis and r['target']==target]
            references=[('v1',next(r for r in previous if r['variant']=='frozen_v1_boosted'))]
            if target=='occupancy_rate':references.append(('v2 validation-selected',min([r for r in previous if r.get('validation_rmse') is not None],key=lambda r:r['validation_rmse'])))
            else:references.append(('v2',next(r for r in previous if r['variant']=='asof_context_auxiliary')))
            references.append(('v3 validation-selected',next(r for r in rows if r['axis']==axis and r['target']==target and r['validation_selected_primary'])))
            for name,r in references:lines.append(f"| {axis} | {name} | {target} | {fmt(r.get('r2'))} | {fmt(r.get('mae'))} | {fmt(r.get('brier_score'))} | {fmt(r.get('ece'))} | {r['n']} |")
    lines+=['','## Interpretation','','The added demand and geometry families did not improve joint geographic/time validation over the calendar model in this sample. V3 occupancy transfer recovered much of the v2 regression, but did not exceed v1 on the forward-time/new-block test; R² remains negative. Forward-time/new-block count error improved, but that test contains only 39 labels on two blocks and still has negative R². Probability reliability is weak in that tiny transferred sample. These results do not authorize numerical unmetered or citywide forecasts.','',
        'Useful completed joins: housing/vehicle predictors, vintage-consistent 2022 employment for September 2025, and later 2023 employment with retail, education, health, arts and food-sector counts. Current active-business counts remain prospective only. Source dates, partial workplace matches and geometry limitations remain explicit in spatial_v3_context.json.','',
        'Collection next: first eight unmetered development counts at 0/15/30/60 minutes; optional independently timestamped meter-bay checks on October 28. Preserve the reserved November 17/21 sessions and three whole new blocks for evaluation. No new occupancy labels have been collected.']
    (REPORT/'SPATIAL_V3.md').write_text('\n'.join(lines)+'\n',encoding='utf8')


def check():
    """Recompute saved metrics and lock artifacts without reading reserved outcomes."""
    check_registered_inputs();cfg=json.loads(Path('config/spatial_v3.json').read_text());protocol=json.loads((REPORT/'spatial_v3_protocol.json').read_text())
    if hashlib.sha256(Path('config/spatial_v3.json').read_bytes()).hexdigest()!=protocol['config_sha256']:raise ValueError('Registered spatial configuration changed')
    rows=json.loads((REPORT/'spatial_v3_results.json').read_text());predictions=pd.read_parquet(ROOT/'predictions.parquet');legacy=json.loads((REPORT/'temporal_v2_results.json').read_text())
    for row in rows:
        p=predictions.loc[predictions.axis.eq(row['axis'])&predictions.target.eq(row['target'])&predictions.variant.eq(row['variant'])]
        actual=score(p.actual,p.prediction,row['target']);reference=next(r for r in legacy if r['horizon']==60 and r['axis']==row['axis'] and r['target']==row['target'] and r['variant']=='frozen_v1_boosted')
        if row['row_sha256']!=reference['row_sha256'] or len(p)!=reference['n']:raise ValueError('Legacy comparison populations differ')
        for key in ['rmse','r2','mae','brier_score','ece']:
            if key in actual and actual[key] is not None and not np.isclose(actual[key],row[key],rtol=1e-9):raise ValueError('Saved metric mismatch: '+key)
        if not np.isfinite(p.prediction).all() or not p.prediction.ge(0).all():raise ValueError('Invalid predictions')
        if row['target']!='available_count' and not p.prediction.le(1).all():raise ValueError('Rate/probability exceeds one')
    validation=json.loads((REPORT/'spatial_v3_validation.json').read_text())
    rate=pd.DataFrame([r for r in validation if r['target']=='occupancy_rate'])
    if any(g.row_sha256.nunique()!=1 for _,g in rate.groupby('fold')):raise ValueError('Feature-family validation rows differ')
    # Verify actual inference consumes saved bundles and causal features, without fitting.
    horizon=cfg['primary_horizon_minutes'];source=pd.read_parquet('data/modeling/temporal_v2/legacy_enhanced.parquet',columns=COLS,filters=[('horizon_minutes','=',horizon)])
    history=pd.concat([pd.read_parquet('data/modeling/temporal_v2/history_legacy.parquet')]+[pd.read_parquet(f'data/modeling/temporal_v2/history_{m}.parquet') for m in ['2026_06','2026_07']],ignore_index=True)
    allowed=set(json.loads((REPORT/'spatial_split.json').read_text())['train_blocks']);f=NeighborHistory(history,pd.read_parquet('data/modeling/current_context.parquet')).transform(enrich(source),allowed)
    complete=json.loads((REPORT/'spatial_v3_complete.json').read_text());primary=complete['primary_variant_selected_before_legacy_scoring']
    for target in TARGETS:
        b=joblib.load(Path('artifacts/models/spatial_v3')/f'h{horizon}_{target}_{primary}.joblib');col=TARGETS[target]
        held=f.loc[f.spatial_role.eq('test')&(f.issued_at_utc>=utc('2026-08-25'))&(f.arrival_time_utc+pd.Timedelta('15min')<utc('2026-09-01'))&f[col].notna()]
        p=predict(b,held)
        if target=='available_count' and not (p<=held.panel_sensor_count).all():raise ValueError('Count bound violated')
        expected=next(r for r in rows if r['target']==target and r['axis']=='future_time_unseen' and r['variant']==primary);metric=score(held[col],p,target)
        key='brier_score' if target=='any_panel_vacant' else 'rmse'
        if not np.isclose(metric[key],expected[key],rtol=1e-9):raise ValueError('Saved bundle inference mismatch')
    models={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('artifacts/models/spatial_v3').glob('*.joblib')}
    lock={'locked_at_utc':datetime.now(timezone.utc).isoformat(),'checks_passed':True,'new_holdouts_unopened':True,'configuration_sha256':protocol['config_sha256'],'models_sha256':models,'legacy_inputs_unchanged':True,'identical_targets_and_observations':True,'saved_inference_reproduced':True,'result_rows':len(rows),'unmetered_test_n':0}
    (REPORT/'spatial_v3_locked_models.json').write_text(json.dumps(lock,indent=2),encoding='utf8');print(json.dumps({k:v for k,v in lock.items() if k!='models_sha256'},indent=2));return lock
