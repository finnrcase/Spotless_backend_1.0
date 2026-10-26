"""Two-stage, direct-label A/B/C/D experiment; frozen tests never select models."""
import hashlib,json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.tree import DecisionTreeRegressor
from .evaluation import regression_metrics,probability_metrics
from .model_features import calendar_features,CALENDAR
from .product_evaluation import guard_manifest,reserved_development,stamp

TARGETS={'occupancy_rate':'occupancy_rate','vacant_count':'available_count','legal_vacancy':'at_least_one'}
RECENT=['recent_rate','recent_vacant','recent_binary','recent_age_minutes','recent_confidence']
MOVEMENT=['arrivals_per_minute','departures_per_minute','movement_continuous']


def config():return json.loads(Path('config/controlled_observations_v1.json').read_text())
def metric(y,p,target):return probability_metrics(y,p) if target=='legal_vacancy' else regression_metrics(y,p)


def readiness(output='reports/controlled_observations'):
    cfg=config();rows=[{'axis':axis,'parking_type':kind,'horizon_minutes':h,'variant':variant,'n':0,'r2':None,'mae':None,'brier_score':None,'coverage':None,'uncertainty_95':None} for axis in ['known_block_future','unseen_block_future'] for kind in ['metered','unmetered'] for h in cfg['horizons_minutes'] for variant in cfg['variants']]
    report={'version':cfg['version'],'status':'awaiting_adequate_reviewed_direct_labels','comparisons':rows,'minimum_requirements':cfg['minimum_rows'],
        'minimum_training_blocks':cfg['minimum_training_blocks'],'minimum_unseen_test_blocks':cfg['minimum_unseen_test_blocks'],'incumbent_suitable_space_prediction_coverage':0,
        'serving_incumbent':cfg['serving_incumbent'],'learning_curves':None,'hierarchical_validation_benefit':None,'movement_validation_benefit':None,
        'holdout_outcomes_opened':False,'models_trained':False,'models_promoted':False,'reason':'No direct reviewed experiment cohort/splits supplied. Existing meter panels cannot fill missing full-face or unmetered truth.'}
    out=Path(output);out.mkdir(parents=True,exist_ok=True);(out/'readiness.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    lines=['# Controlled direct-observation experiment','','Status: **unavailable pending reviewed direct labels**. No outcome stores opened, models fit or final tests inspected.','',
        'A: current suitable-space incumbent abstains; compatible A_reference additionally compares training mean, weekhour, persistence and hierarchical/small tabular baselines. B adds verified as-of public context, C adds recent direct observations, D combines them. No proxy is relabeled as suitable truth.','',
        '| Axis | Population | Horizon | A/B/C/D R² / MAE / Brier | n |','|---|---|---:|---|---:|']
    for axis in ['known_block_future','unseen_block_future']:
        for kind in ['metered','unmetered']:
            for h in cfg['horizons_minutes']:lines.append(f'| {axis} | {kind} | {h} min | unavailable | 0 |')
    lines+=['','Learning curves, arrivals/departures benefit and hierarchical-model benefit are also unavailable. Minimum per population/axis: 40 training, 12 validation, 12 calibration and 12 final-test direct observations, at least four training blocks and three independent unseen test blocks. Repeats are dependent; these are workflow floors, not statistical power or product acceptance guarantees. Start with eight counts for quality, then accumulate independent blocks and sessions. Preserve all prior reservations. See docs/controlled_observations.md.']
    (out/'readiness.md').write_text('\n'.join(lines)+'\n',encoding='utf8');return report


def validate_labels(frame):
    required={'source_id','observation_id','block_face_id','block_id','parking_type','observed_at_utc','window_end_utc','retrieved_at_utc','label_available_at_utc','label_reviewed','label_evidence','capacity_verified','survey_session_id','intended_duration_minutes','vehicle_class','permit_class'}|set(TARGETS.values())
    if not required.issubset(frame):raise ValueError('Prepare direct reviewed labels first; missing '+str(sorted(required-set(frame))))
    f=frame.copy()
    if f.observation_id.duplicated().any() or not f.label_reviewed.eq(True).all() or not f.label_evidence.eq('direct_reviewed_full_face').all():raise ValueError('Only unique reviewed direct full-face labels; no meter panels or CV proposals')
    if not f.source_id.isin(['manual_phone','manual_field','manual_map_ui','reviewed_survey']).all():raise ValueError('Sensor/vendor/CV proxies cannot supply direct experiment labels')
    for col in ['observed_at_utc','window_end_utc','retrieved_at_utc','label_available_at_utc']:
        f[col]=pd.to_datetime([stamp(v) for v in f[col]],utc=True)
    if (f.label_available_at_utc<f.window_end_utc).any() or (f.window_end_utc<f.observed_at_utc).any():raise ValueError('Invalid capture/review chronology')
    if (f.label_available_at_utc<f.retrieved_at_utc).any():raise ValueError('Label availability precedes actual receipt')
    if not f.parking_type.isin(['metered','unmetered']).all():raise ValueError('Separate verified parking populations required')
    if f.survey_session_id.isna().any():raise ValueError('Session IDs required for learning curves and clustered uncertainty')
    if not f.block_face_id.str.rsplit(':',n=1).str[0].eq(f.block_id).all():raise ValueError('Physical blocks must group both canonical curb sides')
    for name in TARGETS.values():
        values=pd.to_numeric(f[name],errors='coerce');valid=values.isna()|np.isfinite(values)
        if name=='occupancy_rate':valid&=values.isna()|values.between(0,1)
        elif name=='at_least_one':valid&=values.isna()|values.isin([0,1])
        else:valid&=values.isna()|(values.ge(0)&values.eq(np.floor(values)))
        if not valid.all():raise ValueError('Invalid direct target')
        f[name]=values
    f.loc[~f.capacity_verified.eq(True),['occupancy_rate','available_count']]=np.nan
    return f


def make_design(labels,context,horizon,cfg):
    """Recent observations are issue-time inputs, never the same target capture."""
    f=labels.copy().reset_index(drop=True);f['issued_at_utc']=f.observed_at_utc-pd.Timedelta(minutes=horizon);f['arrival_time_utc']=f.observed_at_utc
    for c,v in calendar_features(f.arrival_time_utc).items():f[c]=v
    for name in cfg['context_features']+RECENT+MOVEMENT:f[name]=np.nan
    f['context_supported']=False;f['recent_supported']=False
    if len(context):
        needed={'observation_id','horizon_minutes','available_at_utc','received_at_utc'}|set(cfg['context_features'])
        if not needed.issubset(context):raise ValueError('Context needs explicit receipt/availability and every declared field, with null for missing values')
        ctx=context.loc[context.horizon_minutes.eq(horizon)].copy()
        if ctx.observation_id.duplicated().any():raise ValueError('Duplicate horizon/context target')
        ctx=ctx.set_index('observation_id')
        for i,r in f.iterrows():
            if r.observation_id not in ctx.index:continue
            c=ctx.loc[r.observation_id]
            if max(stamp(c.available_at_utc),stamp(c.received_at_utc))>r.issued_at_utc:continue
            for name in cfg['context_features']:
                value=c[name]
                if pd.notna(value) and not np.isfinite(float(value)):raise ValueError('Nonfinite context')
                f.loc[i,name]=value
            f.loc[i,'context_supported']=any(pd.notna(c[name]) for name in cfg['context_features'])
    for face,queries in f.groupby('block_face_id'):
        history=labels.loc[labels.block_face_id.eq(face)].sort_values('observed_at_utc')
        for i,q in queries.iterrows():
            h=history.loc[history.window_end_utc.le(q.issued_at_utc)&history.label_available_at_utc.le(q.issued_at_utc)&history.observation_id.ne(q.observation_id)]
            for key in ['source_record_id','sample_unit_id']:
                if key in h and pd.notna(q.get(key)):h=h.loc[h[key].ne(q[key])]
            for key in ['vehicle_class','permit_class','intended_duration_minutes']:
                h=h.loc[h[key].fillna('<none>').eq(q[key] if pd.notna(q[key]) else '<none>')]
            if h.empty:continue
            r=h.iloc[-1];age=(q.issued_at_utc-r.observed_at_utc).total_seconds()/60
            if age>cfg['recent_max_age_minutes']:continue
            f.loc[i,RECENT]=[r.occupancy_rate,r.available_count,r.at_least_one,age,r.get('observer_confidence',np.nan)]
            f.loc[i,'recent_supported']=True
            if r.get('movement_coverage') in ['partial','continuous'] and pd.notna(r.get('movement_end_utc')) and stamp(r.movement_end_utc)<=q.issued_at_utc:
                duration=(stamp(r.movement_end_utc)-stamp(r.movement_start_utc)).total_seconds()/60
                if duration>0:f.loc[i,MOVEMENT]=[float(r['arrivals_observed'])/duration if pd.notna(r.get('arrivals_observed')) else np.nan,float(r['departures_observed'])/duration if pd.notna(r.get('departures_observed')) else np.nan,float(r.movement_coverage=='continuous')]
    return f


def features(variant,cfg):
    return CALENDAR+(cfg['context_features'] if variant in ['B_context','D_combined','D_movement_validation'] else [])+(RECENT if variant in ['C_recent','D_combined','D_movement_validation'] else [])+(MOVEMENT if variant=='D_movement_validation' else [])


def fit(train,target,kind,cols,cfg):
    y=train[TARGETS[target]].to_numpy();bundle={'kind':kind,'target':target,'columns':cols,'training':train.copy()}
    if kind in ['ridge','small_tree']:
        estimator=Ridge(alpha=cfg['ridge_alpha']) if kind=='ridge' else DecisionTreeRegressor(max_depth=cfg['tree_max_depth'],min_samples_leaf=cfg['tree_min_samples_leaf'],random_state=cfg['seed'])
        model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),StandardScaler(),estimator)
        bundle['model']=model.fit(train[cols],y)
    return bundle


def predict(bundle,query,calibrated=True):
    train=bundle['training'];col=TARGETS[bundle['target']];mean=float(train[col].mean());kind=bundle['kind']
    if kind in ['ridge','small_tree']:p=bundle['model'].predict(query[bundle['columns']])
    else:
        p=[]
        for _,q in query.iterrows():
            # Fitted baseline statistics use only that fold's training rows.
            h=train.loc[train.label_available_at_utc<=q.issued_at_utc];prior=float(h[col].mean()) if len(h) else mean
            if kind=='persistence':
                key={'occupancy_rate':'recent_rate','vacant_count':'recent_vacant','legal_vacancy':'recent_binary'}[bundle['target']];v=q.get(key,np.nan) if key in bundle['columns'] else np.nan;value=v if pd.notna(v) else prior
            elif kind=='hierarchical':
                own=h.loc[h.block_id.eq(q.block_id),col];value=(own.sum()+10*prior)/(len(own)+10)
            elif kind=='weekhour':
                t=q.arrival_time_utc.tz_convert('America/Los_Angeles');local=h.arrival_time_utc.dt.tz_convert('America/Los_Angeles');own=h.loc[local.dt.dayofweek.eq(t.dayofweek)&local.dt.hour.eq(t.hour),col];value=(own.sum()+10*prior)/(len(own)+10)
            else:value=prior
            p.append(value)
    p=np.maximum(0,np.asarray(p));p=np.minimum(1,p) if bundle['target']!='vacant_count' else p
    if calibrated and bundle.get('calibrator') is not None:
        p=bundle['calibrator'].predict_proba(np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1))[:,1]
    return p


def interval(frame,values,cfg,group='block_day'):
    keys=frame.block_id.astype(str) if group=='block' else frame.arrival_time_utc.dt.tz_convert('America/Los_Angeles').dt.strftime('%Y-%m-%d')
    if group=='block_day':keys=frame.block_id.astype(str)+'|'+keys
    stats=pd.DataFrame({'key':keys.to_numpy(),'value':values,'n':1}).groupby('key').agg(total=('value','sum'),n=('n','sum')).to_numpy()
    if len(stats)<3:return None
    rng=np.random.default_rng(cfg['seed']);samples=[]
    for _ in range(cfg['bootstrap_replicates']):
        a=stats[rng.integers(0,len(stats),len(stats))].sum(axis=0);samples.append(a[0]/a[1])
    return np.quantile(samples,[.025,.975]).tolist()


def select(train,val,target,variant,cfg):
    choices=[];predictions={};col=TARGETS[target]
    for kind in cfg['candidates']:
        b=fit(train,target,kind,features(variant,cfg),cfg);p=predict(b,val);loss=(val[col].to_numpy()-p)**2
        choices.append({'kind':kind,'validation_mse_or_brier':float(np.mean(loss)),**metric(val[col],p,target)});predictions[kind]=p
    best=min(choices,key=lambda r:r['validation_mse_or_brier']);bestloss=(val[col].to_numpy()-predictions[best['kind']])**2;selected=best['kind']
    for kind in cfg['candidates']:
        difference=(val[col].to_numpy()-predictions[kind])**2-bestloss;ci=interval(val,difference,cfg)
        if kind==best['kind'] or ci is not None and ci[0]<=0<=ci[1]:selected=kind;break
    if interval(val,bestloss,cfg) is None:selected=cfg['candidates'][0]
    return fit(train,target,selected,features(variant,cfg),cfg),choices


def partitions(frame,split,axis,cfg):
    names=['train','validation','calibration','test'];groups={k:set(split.get(k+'_ids',[])) for k in names}
    for i,a in enumerate(names):
        if len(groups[a])!=len(split.get(a+'_ids',[])):raise ValueError('Duplicate split IDs')
        for b in names[i+1:]:
            if groups[a]&groups[b]:raise ValueError('Observation overlap across partitions')
    parts={name:frame.loc[frame.observation_id.isin(ids)].copy() for name,ids in groups.items()}
    for a,b in zip(names,names[1:]):
        if len(parts[a]) and len(parts[b]) and parts[a].label_available_at_utc.max()+pd.Timedelta(minutes=cfg['embargo_minutes'])>=parts[b].issued_at_utc.min():raise ValueError('Chronology/review embargo violation')
    known=set(parts['train'].block_id)|set(parts['validation'].block_id)|set(parts['calibration'].block_id)
    if axis=='unseen_block_future' and known&set(parts['test'].block_id):raise ValueError('Unseen-block leakage through either side')
    if axis=='known_block_future' and not set(parts['test'].block_id).issubset(set(parts['train'].block_id)):raise ValueError('Known-block test contains new blocks')
    return parts


def fit_development(labels,context,manifest,output='artifacts/models/controlled_observations_v1',cfg=None):
    cfg=cfg or config();labels=validate_labels(labels);root=Path(output)
    if (root/'complete.json').exists():raise ValueError('Development experiment frozen; register a new version')
    # Training/validation/calibration only. Reserved test rows are not loaded.
    used=set(i for split in manifest['splits'].values() for phase in ['train','validation','calibration'] for i in split[phase+'_ids'])
    if set(labels.observation_id)-used:raise ValueError('Do not open test/undeclared labels during development')
    if manifest.get('data_kind')!='synthetic_demo':
        for r in labels.to_dict('records'):
            if reserved_development({**r,'survey_start_utc':r['observed_at_utc']}):raise ValueError('Reserved observation used for development')
    root.mkdir(parents=True,exist_ok=True);results=[];curves=[];bundles={}
    for axis,split in manifest['splits'].items():
        for h in cfg['horizons_minutes']:
            design=make_design(labels,context,h,cfg);parts=partitions(design,{**split,'test_ids':[]},axis,cfg)
            for population in ['metered','unmetered']:
                for target,col in TARGETS.items():
                    p={name:f.loc[f.parking_type.eq(population)&f[col].notna()].reset_index(drop=True) for name,f in parts.items()}
                    enough=all(len(p[k])>=cfg['minimum_rows'][k] for k in ['train','validation','calibration']) and p['train'].block_id.nunique()>=cfg['minimum_training_blocks']
                    if not enough:results.append({'axis':axis,'horizon':h,'population':population,'target':target,'status':'insufficient_direct_labels','sizes':{k:len(v) for k,v in p.items()}});continue
                    for variant in cfg['variants']+['D_movement_validation']:
                        b,trials=select(p['train'],p['validation'],target,variant,cfg);raw=predict(b,p['validation']);validation=metric(p['validation'][col],raw,target)
                        if target=='legal_vacancy' and p['calibration'][col].nunique()==2:
                            z=predict(b,p['calibration']);z=np.log(np.clip(z,1e-6,1-1e-6)/(1-np.clip(z,1e-6,1-1e-6))).reshape(-1,1);b['calibrator']=LogisticRegression(C=1).fit(z,p['calibration'][col])
                        key=f'{axis}_{population}_h{h}_{target}_{variant}';bundles[key]=b
                        results.append({'axis':axis,'horizon':h,'population':population,'target':target,'variant':variant,'kind':b['kind'],'validation':validation,'candidates':trials,
                            'context_coverage':float(p['validation'].context_supported.mean()),'recent_coverage':float(p['validation'].recent_supported.mean()),'movement_adopted':False})
                        sessions=p['train'].groupby('survey_session_id').observed_at_utc.min().sort_values().index.tolist()
                        for fraction in [.25,.5,1.]:
                            selected=sessions[:max(1,int(np.ceil(len(sessions)*fraction)))];small=p['train'].loc[p['train'].survey_session_id.isin(selected)]
                            fitted=fit(small,target,b['kind'],features(variant,cfg),cfg);pred=predict(fitted,p['validation'])
                            curves.append({'key':key,'training_sessions':len(selected),'training_rows':len(small),'validation_only':True,**metric(p['validation'][col],pred,target)})
    for key,b in bundles.items():joblib.dump(b,root/(key+'.joblib'))
    completion={'version':cfg['version'],'data_kind':manifest.get('data_kind','observed'),'manifest':manifest,'config':cfg,'validation_results':results,'learning_curves_validation_only':curves,'models_promoted':False,'test_outcomes_opened':False,
        'artifacts_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.joblib')}}
    (root/'complete.json').write_text(json.dumps(completion,indent=2,default=str)+'\n',encoding='utf8');return completion


def evaluate_locked(labels,context,manifest,artifacts='artifacts/models/controlled_observations_v1',output='reports/controlled_observations/evaluation.json'):
    completion=json.loads((Path(artifacts)/'complete.json').read_text());cfg=completion['config'];labels=validate_labels(labels);rows=[];digests={}
    for path,digest in completion['artifacts_sha256'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen experiment artifact changed')
    if cfg!=config() and manifest.get('data_kind')!='synthetic_demo':raise ValueError('Config changed; register a new experiment')
    for axis,split in manifest['splits'].items():
        gate={**manifest['release'], 'axis':'future_time' if axis=='known_block_future' else 'unseen_block','train_ids':[], 'evaluation_ids':split['test_ids'],'data_kind':manifest.get('data_kind','observed')}
        guard_manifest(gate)
        for h in cfg['horizons_minutes']:
            design=make_design(labels,context,h,cfg);test=design.loc[design.observation_id.isin(split['test_ids'])]
            expected=completion['manifest']['splits'][axis]
            if split!=expected:raise ValueError('Split membership changed after development freeze')
            known=set(i for phase in ['train','validation','calibration'] for i in split[phase+'_ids'])
            training_blocks=set(labels.loc[labels.observation_id.isin(known),'block_id'])
            if axis=='unseen_block_future' and training_blocks&set(test.block_id):raise ValueError('Whole-block leakage')
            if axis=='known_block_future' and not set(test.block_id).issubset(set(labels.loc[labels.observation_id.isin(split['train_ids']),'block_id'])):raise ValueError('Unknown block in known future evaluation')
            if len(test) and not test.issued_at_utc.between(stamp(gate['evaluation_start_utc']),stamp(gate['evaluation_end_utc']),inclusive='left').all():raise ValueError('Test forecast issue outside frozen release period')
            for population in ['metered','unmetered']:
                for target,col in TARGETS.items():
                    held=test.loc[test.parking_type.eq(population)&test[col].notna()].reset_index(drop=True)
                    enough=len(held)>=cfg['minimum_rows']['test'] and (axis!='unseen_block_future' or held.block_id.nunique()>=cfg['minimum_unseen_test_blocks'])
                    for variant in cfg['variants']:
                        key=f'{axis}_{population}_h{h}_{target}_{variant}';path=Path(artifacts)/(key+'.joblib')
                        missing=set(split['test_ids'])-set(test.observation_id)
                        base={'axis':axis,'population':population,'horizon':h,'target':target,'variant':variant,'n':len(held),
                            'label_coverage':None if missing else len(held)/max(1,len(test.loc[test.parking_type.eq(population)])),
                            'declared_test_ids_all_populations':len(split['test_ids']),'missing_test_rows_all_populations':len(missing),'blocks':int(held.block_id.nunique())}
                        if not enough or not path.exists():rows.append({**base,'status':'insufficient_direct_labels_or_model','r2':None,'mae':None,'brier_score':None});continue
                        b=joblib.load(path)
                        if len(held) and b['training'].label_available_at_utc.max()+pd.Timedelta(minutes=cfg['embargo_minutes'])>=held.issued_at_utc.min():raise ValueError('Test precedes frozen training/review embargo')
                        p=predict(b,held);y=held[col].to_numpy();loss=(y-p)**2
                        digest=hashlib.sha256(pd.util.hash_pandas_object(held[['observation_id',col]],index=False).values.tobytes()).hexdigest();digests[key]=digest
                        rows.append({**base,'status':'scored','data_kind':manifest.get('data_kind','observed'),'row_sha256':digest,**metric(y,p,target),
                            'loss_95_by_block':interval(held,loss,cfg,'block'),'loss_95_by_day':interval(held,loss,cfg,'day'),'loss_95_by_block_day':interval(held,loss,cfg),
                            'context_coverage':float(held.context_supported.mean()),'recent_coverage':float(held.recent_supported.mean())})
    out=Path(output);out.parent.mkdir(parents=True,exist_ok=True);lock=out.with_suffix('.lock.json')
    fingerprint={'artifacts_sha256':completion['artifacts_sha256'],'target_row_sha256':digests}
    if lock.exists() and json.loads(lock.read_text())!=fingerprint:raise ValueError('Previously inspected test or model changed; reserve a new period')
    lock.write_text(json.dumps(fingerprint,indent=2)+'\n',encoding='utf8')
    report={'version':cfg['version'],'data_kind':manifest.get('data_kind','observed'),'results':rows,'models_promoted':False,'test_used_for_selection':False,
        'incumbent_suitable_space_metrics':None,'incumbent_reason':cfg['serving_incumbent'],'learning_curves_validation_only':completion['learning_curves_validation_only'],
        'new_block_recent_evidence_note':'C/D on untrained blocks with recent direct evidence is operational cold start with observations, not pure no-observation geographic transfer.',
        'uncertainty_note':'Conditional grouped bootstrap intervals require >=3 groups; otherwise unavailable. Block/day dependence and label/rule errors remain.'}
    out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8');return report


def run(action='readiness',table=None,context=None,manifest=None,artifacts='artifacts/models/controlled_observations_v1',output=None):
    if action=='readiness':return readiness(output or 'reports/controlled_observations')
    if not table or not manifest:raise ValueError('Explicit reviewed table and frozen split manifest required')
    m=json.loads(Path(manifest).read_text());allowed=set(i for split in m['splits'].values() for phase in (['train','validation','calibration'] if action=='fit' else ['train','validation','calibration','test']) for i in split[phase+'_ids'])
    if action=='fit' and allowed&set(i for split in m['splits'].values() for i in split['test_ids']):raise ValueError('A test ID was declared for development on another axis')
    if action=='evaluate':
        # Release check precedes opening outcome data.
        for axis,split in m['splits'].items():guard_manifest({**m['release'],'axis':'future_time' if axis=='known_block_future' else 'unseen_block','train_ids':[],'evaluation_ids':split['test_ids'],'data_kind':m.get('data_kind','observed')})
    labels=pd.read_parquet(table,filters=[('observation_id','in',list(allowed))])
    ctx=pd.read_parquet(context) if context else pd.DataFrame()
    return fit_development(labels,ctx,m,artifacts) if action=='fit' else evaluate_locked(labels,ctx,m,artifacts,output or 'reports/controlled_observations/evaluation.json')


def prepare(observations,reviews,manifest,output,release_test=False):
    """Convert explicit new suitability reviews into a direct experiment table."""
    from .product_evaluation import reviewed_outcomes
    m=json.loads(Path(manifest).read_text());phases=['train','validation','calibration']+(['test'] if release_test else [])
    ids=set(i for split in m['splits'].values() for phase in phases for i in split[phase+'_ids'])
    if release_test:
        for axis,split in m['splits'].items():guard_manifest({**m['release'],'axis':'future_time' if axis=='known_block_future' else 'unseen_block','train_ids':[],'evaluation_ids':split['test_ids'],'data_kind':m.get('data_kind','observed')})
    if str(observations).endswith('.parquet'):
        f=pd.read_parquet(observations,filters=[('observation_id','in',list(ids))]);raw=json.loads(f.to_json(orient='records',date_format='iso'))
        from .contracts import ManualObservation
        defaults=ManualObservation.model_fields;raw=[{k:v for k,v in r.items() if v is not None or k not in defaults or defaults[k].default is None} for r in raw]
    else:raw=[json.loads(line) for line in Path(observations).read_text(encoding='utf8').splitlines() if line.strip()]
    if set(r['observation_id'] for r in raw)-ids:raise ValueError('Export only the explicit permitted cohort')
    reviewed=[json.loads(line) for line in Path(reviews).read_text(encoding='utf8').splitlines() if line.strip()];labels,rejected=reviewed_outcomes(raw,reviewed,m.get('data_kind','observed'))
    rows=[]
    for r in labels.values():
        if not r['complete_face'] or not r['complete_visibility_reviewed']:continue
        if not release_test and m.get('data_kind')!='synthetic_demo' and reserved_development(r):raise ValueError('Reserved row cannot enter development')
        rows.append({**r,'observed_at_utc':r['survey_start_utc'],'window_end_utc':r['survey_end_utc'],'available_count':r['suitable_count'],
            'label_reviewed':True,'label_evidence':'direct_reviewed_full_face','capacity_verified':r['capacity_reviewed']})
    if not rows:raise ValueError('No qualifying direct reviewed rows; no labels fabricated')
    frame=pd.DataFrame(rows);path=Path(output);path.parent.mkdir(parents=True,exist_ok=True);frame.to_parquet(path,index=False)
    return {'prepared_rows':len(frame),'rejected':rejected,'test_outcomes_included':release_test,'no_model_training':True}
