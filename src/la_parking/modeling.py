"""Executable baseline -> regularized -> boosted experiments on supported panels."""
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge,LogisticRegression,PoissonRegressor
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits
from .evaluation import regression_metrics,probability_metrics
from .model_features import CALENDAR,HISTORY,CONTEXT

TARGETS={'occupancy_rate':'target_occupancy_rate','available_count':'target_available_count','any_panel_vacant':'target_any_panel_vacant'}


def utc(value): return pd.Timestamp(value,tz='America/Los_Angeles').tz_convert('UTC')


def prep_scenario(frame,axis):
    f=frame.copy()
    if axis!='future_time':
        # No held-out own-face histories or outcomes enter geographic transfer.
        for c in HISTORY:
            if c not in ['neighbor_rate_300','neighbor_rate_600']: f[c]=np.nan
        for r in [300,600]: f[f'neighbor_rate_{r}']=f[f'neighbor_train_only_{r}']
    else:
        for r in [300,600]: f[f'neighbor_rate_{r}']=f[f'neighbor_all_{r}']
    return f


class PooledMean:
    """Empirical shrinkage of face and neighborhood/time-week means to global mean."""
    def __init__(self,strength=30,face=True): self.strength=strength;self.face=face
    @staticmethod
    def keys(x):
        local=x.arrival_time_utc.dt.tz_convert('America/Los_Angeles')
        return pd.DataFrame({'area':x.area,'weekday':local.dt.dayofweek,'hour':local.dt.hour},index=x.index)
    def fit(self,x,y):
        self.mean=float(np.mean(y)); k=self.keys(x);k['y']=np.asarray(y)
        g=k.groupby(['area','weekday','hour']).y.agg(['sum','count'])
        self.area=((g['sum']+self.strength*self.mean)/(g['count']+self.strength)).to_dict()
        q=pd.DataFrame({'face':x.block_face_id.to_numpy(),'y':np.asarray(y)})
        g=q.groupby('face').y.agg(['sum','count']); self.faces=((g['sum']+self.strength*self.mean)/(g['count']+self.strength)).to_dict()
        return self
    def predict(self,x):
        keys=self.keys(x);p=np.array([self.area.get(tuple(r),self.mean) for r in keys.itertuples(index=False,name=None)])
        if self.face:
            f=np.array([self.faces.get(k,self.mean) for k in x.block_face_id]);p=.5*p+.5*f
        return p


def estimator(kind,target,features,parameter,seed):
    if kind=='regularized':
        model=LogisticRegression(C=1/parameter,max_iter=300,random_state=seed) if target=='any_panel_vacant' else PoissonRegressor(alpha=parameter,max_iter=500) if target=='available_count' else Ridge(alpha=parameter)
        return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),model)
    cls=HistGradientBoostingClassifier if target=='any_panel_vacant' else HistGradientBoostingRegressor
    # Random early-stopping splits would break temporal ordering, so disable them.
    options={'loss':'poisson'} if target=='available_count' else {}
    return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),cls(max_iter=100,max_leaf_nodes=int(parameter),learning_rate=.06,l2_regularization=10,min_samples_leaf=40,early_stopping=False,random_state=seed,**options))


def predict_head(bundle,frame):
    model=bundle['model'];target=bundle['target']
    if bundle['kind'] in ['pooled','time_week']: pred=model.predict(frame)
    elif bundle['kind']=='constant': pred=np.repeat(model,len(frame))
    elif target=='any_panel_vacant': pred=model.predict_proba(frame[bundle['features']])[:,1]
    else: pred=model.predict(frame[bundle['features']])
    if target in ['occupancy_rate','any_panel_vacant']: pred=np.clip(pred,0,1)
    else: pred=np.clip(pred,0,frame.panel_sensor_count.to_numpy())
    if bundle.get('calibrator') is not None:
        logits=np.log(np.clip(pred,1e-6,1-1e-6)/(1-np.clip(pred,1e-6,1-1e-6))).reshape(-1,1)
        pred=bundle['calibrator'].predict_proba(logits)[:,1]
    return pred


def fit_head(train,calibration,target,kind,features,parameter,cfg):
    if target in ['available_count','any_panel_vacant']: features=list(dict.fromkeys(features+['panel_sensor_count']))
    col=TARGETS[target];train=train.loc[train[col].notna()].copy();cal=calibration.loc[calibration[col].notna()].copy()
    if len(train)<20: return None
    y=train[col].to_numpy(); model_kind=kind
    if kind in ['pooled','time_week']: model=PooledMean(face=kind=='pooled').fit(train,y)
    elif (target=='any_panel_vacant' and len(np.unique(y))<2) or (target=='available_count' and not np.any(y>0)): model=float(np.mean(y));model_kind='constant'
    else: model=estimator(kind,target,features,parameter,cfg['seed']).fit(train[features],y)
    bundle={'model':model,'kind':model_kind,'target':target,'features':features,'parameter':parameter,'calibrator':None,'conformal_radius':None,'train_rows':len(train),'calibration_rows':len(cal)}
    if len(cal)>=20:
        p=predict_head(bundle,cal)
        if target=='any_panel_vacant' and cal[col].nunique()==2:
            z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1)
            bundle['calibrator']=LogisticRegression(C=1,max_iter=200).fit(z,cal[col])
        elif target!='any_panel_vacant':
            residual=np.abs(cal[col].to_numpy()-p);q=min(1,np.ceil((len(residual)+1)*cfg['prediction_interval_nominal_coverage'])/len(residual))
            bundle['conformal_radius']=float(np.quantile(residual,q,method='higher'))
    return bundle


def score_head(bundle,test,target):
    col=TARGETS[target];valid=test[col].notna();used=test.loc[valid]
    if bundle is None or not len(used): return {'n':0,'status':'insufficient_labels'},None
    p=predict_head(bundle,used);y=used[col].to_numpy()
    score=probability_metrics(y,p) if target=='any_panel_vacant' else regression_metrics(y,p)
    score.update(status='sensor_panel_proxy_only',label_coverage_fraction=float(valid.mean()),test_blocks=int(used.block_id.nunique()),test_faces=int(used.block_face_id.nunique()),candidate_rows=len(test))
    result=used[['block_face_id','block_id','issued_at_utc','arrival_time_utc','horizon_minutes','target_coverage_fraction','area','panel_sensor_count']].copy()
    result['target']=target;result['actual']=y;result['prediction']=p
    if target!='any_panel_vacant' and bundle.get('conformal_radius') is not None:
        maximum=1 if target=='occupancy_rate' else used.panel_sensor_count.to_numpy()
        low=np.maximum(0,p-bundle['conformal_radius']); high=np.minimum(maximum,p+bundle['conformal_radius'])
        score['interval_coverage']=float(((y>=low)&(y<=high)).mean());score['interval_mean_width']=float((high-low).mean())
        score['nominal_interval_coverage']=.9;result['lower']=low;result['upper']=high
    # Report variation by area, time and label coverage; no pooled unsupported population.
    result['local_hour']=result.arrival_time_utc.dt.tz_convert('America/Los_Angeles').dt.hour
    result['sensor_coverage_band']=pd.cut(result.target_coverage_fraction,[0,.5,.8,1.00001],labels=['25-50%','50-80%','80-100%'],include_lowest=True)
    strata={}
    for field in ['area','local_hour','sensor_coverage_band']:
        rows=[]
        for key,g in result.groupby(field,observed=True):
            metric=probability_metrics(g.actual,g.prediction) if target=='any_panel_vacant' else regression_metrics(g.actual,g.prediction)
            rows.append({'group':str(key),**metric})
        strata[field]=rows
    score['strata']=strata
    return score,result


def tune(frame,horizon,features,cfg):
    metrics=[]
    for kind,parameters in [('regularized',cfg['hyperparameters']['ridge_alpha']),('boosted',cfg['hyperparameters']['boosted_max_leaf_nodes'])]:
        for parameter in parameters:
            errors=[]
            for boundary in cfg['rolling_origins_local']:
                origin=utc(boundary); embargo=pd.Timedelta(minutes=cfg['embargo_minutes'])
                train=frame.loc[(frame.arrival_time_utc+pd.Timedelta(minutes=cfg['label_window_minutes'])<origin-embargo)&frame.target_occupancy_rate.notna()]
                val=frame.loc[(frame.issued_at_utc>=origin)&(frame.issued_at_utc<origin+pd.Timedelta(days=cfg['rolling_validation_days']))&frame.target_occupancy_rate.notna()]
                if len(train)<50 or len(val)<20: continue
                b=fit_head(train,val.iloc[:0],'occupancy_rate',kind,features,parameter,cfg)
                p=predict_head(b,val);metric=regression_metrics(val.target_occupancy_rate,p)
                errors.append(metric['mae']);metrics.append({'horizon':horizon,'kind':kind,'parameter':parameter,'rolling_origin':str(origin),'train_n':len(train),'validation_n':len(val),**metric})
            if not errors: metrics.append({'horizon':horizon,'kind':kind,'parameter':parameter,'mae':None})
    selected={}
    for kind in ['regularized','boosted']:
        choices=[r for r in metrics if r['kind']==kind and r.get('mae') is not None]
        means=pd.DataFrame(choices).groupby('parameter').mae.mean() if choices else pd.Series(dtype=float)
        selected[kind]=float(means.idxmin()) if len(means) else (10 if kind=='regularized' else 7)
    return selected,metrics


def train_models(config_path='config/modeling.json'):
    cfg=json.loads(Path(config_path).read_text());d=pd.read_parquet('data/modeling/design.parquet')
    out=Path('artifacts/models');out.mkdir(parents=True,exist_ok=True);rep=Path('reports/modeling');rep.mkdir(exist_ok=True)
    train_end=utc(cfg['final_training_end_local']);calstart=utc(cfg['calibration_start_local']);calend=utc(cfg['calibration_end_local']);teststart=utc(cfg['final_test_start_local']);testend=utc(cfg['final_test_end_local'])
    # Write/freeze source/split configuration before any model is evaluated on final test.
    protocol={'config':cfg,'design_sha256':hashlib.sha256(Path('data/modeling/design.parquet').read_bytes()).hexdigest(),'model_features':{'calendar':CALENDAR,'history':HISTORY,'context':CONTEXT,'count_binary_heads_extra':['panel_sensor_count']},'final_test_tuned_on':False,
              'implementation_revision':'Count heads use nonnegative count loss and known panel size; rate specification unchanged. One preliminary rate result inspection occurred before this methodological count correction; no split, rate feature or hyperparameter choice changed in response to final scores.'}
    (rep/'experiment_protocol.json').write_text(json.dumps(protocol,indent=2))
    results=[];predictions=[];tuning=[];ablations=[];catalog=[]
    with threadpool_limits(limits=2):
      for horizon in cfg['horizons_minutes']:
        original=d.loc[d.horizon_minutes==horizon].copy()
        for axis in ['future_time','unseen_area']:
            f=prep_scenario(original,axis); labelend=f.arrival_time_utc+pd.Timedelta(minutes=cfg['label_window_minutes'])
            region=f.spatial_role.eq('train') if axis=='unseen_area' else pd.Series(True,index=f.index)
            train=f.loc[(labelend<train_end-pd.Timedelta(minutes=cfg['embargo_minutes']))&region]
            cal=f.loc[(f.issued_at_utc>=calstart)&(labelend<calend)&region]
            if axis=='future_time':
                test=f.loc[(f.issued_at_utc>=teststart)&(labelend<testend)&f.block_id.isin(set(train.block_id))]
            else:
                test=f.loc[(labelend<train_end-pd.Timedelta(minutes=cfg['embargo_minutes']))&f.spatial_role.eq('test')]
            features=CALENDAR+HISTORY
            print('Train',axis,'horizon',horizon,'train',len(train),'cal',len(cal),'test',len(test),flush=True)
            selected,folds=tune(f.loc[region],horizon,features,cfg);tuning.extend([{**r,'axis':axis} for r in folds])
            for target in TARGETS:
                for kind in ['time_week','persistence','pooled','regularized','boosted']:
                    if kind=='persistence':
                        # Persistence uses the last completed-bin rate or panel-available count.
                        b=fit_head(train,cal,target,'pooled',features,0,cfg)
                        if b is None: continue
                        for split,part in [('test',test)]:
                            col=TARGETS[target];v=part.loc[part[col].notna()].copy()
                            if not len(v): continue
                            base=predict_head(b,v);lag=v.lag_rate_15.to_numpy()
                            persistence=lag if target=='occupancy_rate' else (1-lag)*v.panel_sensor_count.to_numpy() if target=='available_count' else np.full(len(v),np.nan)
                            # Never turn an expected vacancy count into a probability.
                            if target=='any_panel_vacant': continue
                            pred=np.where(np.isfinite(persistence),persistence,base)
                            m=regression_metrics(v[col],pred);m.update(label_coverage_fraction=float(part[col].notna().mean()),test_blocks=int(v.block_id.nunique()),candidate_rows=len(part))
                            results.append({'axis':axis,'horizon':horizon,'target':target,'model':kind,'population':'metered_sensor_panel','evidence_class':'retrospective_sensor_panel_proxy',**m})
                        continue
                    parameter=selected.get(kind,0)
                    bundle=fit_head(train,cal,target,kind,features,parameter,cfg)
                    metric,p=score_head(bundle,test,target)
                    results.append({'axis':axis,'horizon':horizon,'target':target,'model':kind,'population':'metered_sensor_panel','evidence_class':'retrospective_sensor_panel_proxy',**metric})
                    if bundle is not None:
                        name=f'{axis}_h{horizon}_{target}_{kind}.joblib';joblib.dump(bundle,out/name)
                        catalog.append({'file':name,'axis':axis,'horizon':horizon,'target':target,'kind':kind,'features':features,'train_rows':bundle['train_rows'],'calibration_rows':bundle['calibration_rows']})
                    if p is not None:
                        p['axis']=axis;p['model']=kind;predictions.append(p)
                    if axis=='unseen_area' and bundle is not None:
                        future=f.loc[(f.issued_at_utc>=teststart)&(labelend<testend)&f.spatial_role.eq('test')]
                        metric,_=score_head(bundle,future,target)
                        results.append({'axis':'future_unseen_area','horizon':horizon,'target':target,'model':kind,'population':'metered_sensor_panel','evidence_class':'retrospective_sensor_panel_proxy',**metric})
            # Selected feature-family ablations, all model choices fixed using rolling training folds.
            for label,cols in [('calendar_only',CALENDAR),('no_neighbors',[c for c in features if not c.startswith('neighbor')]),('retrospective_context',features+CONTEXT)]:
                b=fit_head(train,cal,'occupancy_rate','boosted',cols,selected['boosted'],cfg)
                m,_=score_head(b,test,'occupancy_rate');ablations.append({'axis':axis,'horizon':horizon,'family_variant':label,'historical_vintage_valid':label!='retrospective_context',**m})
            # A typical-pattern model deliberately has no recent-state features.
            if horizon==0:
                b=fit_head(train,cal,'occupancy_rate','time_week',CALENDAR,0,cfg)
                joblib.dump(b,out/f'{axis}_typical_pattern.joblib')
        (rep/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False))
        (rep/'rolling_validation.json').write_text(json.dumps(tuning,indent=2,allow_nan=False))
        (rep/'ablations.json').write_text(json.dumps(ablations,indent=2,allow_nan=False))
        (out/'catalog.json').write_text(json.dumps(catalog,indent=2))
    if predictions: pd.concat(predictions,ignore_index=True).to_parquet('data/modeling/test_predictions.parquet',index=False)
    summary=[{k:v for k,v in r.items() if k not in ['strata','reliability_bins']} for r in results]
    pd.DataFrame(summary).to_csv(rep/'metrics.csv',index=False)
    from datetime import datetime,timezone
    import sklearn,sys
    run={'completed_at_utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,'scikit_learn':sklearn.__version__,
         'uv_lock_sha256':hashlib.sha256(Path('uv.lock').read_bytes()).hexdigest(),'models_saved':len(catalog)+2,
         'code_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/la_parking').glob('*.py')},
         'fit_scope':'metered sensor-panel proxy only','final_test_hyperparameter_selection':False}
    (out/'run_manifest.json').write_text(json.dumps(run,indent=2))
    return results
