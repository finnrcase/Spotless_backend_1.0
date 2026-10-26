"""Unmetered-first controlled comparison, gated on actual reviewed labels.

Missing labels produce an unavailable report. Feature values never create labels.
The existing partial metered sensor panels are not silently relabelled as full
block observations. All model choices use unmetered validation, never test rows.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits
from .evaluation import regression_metrics,probability_metrics


def config():return json.loads(Path('config/unmetered_experiment.json').read_text())


def unavailable_report(observation_path='data/observations/manual_observations.parquet',output='reports/unmetered'):
    path=Path(observation_path);df=pd.read_parquet(path) if path.exists() else pd.DataFrame()
    n=int(df.parking_type.eq('unmetered').sum()) if 'parking_type' in df else 0
    report={'version':config()['version'],'status':'awaiting_direct_unmetered_labels_and_frozen_splits',
        'accepted_manual_records':len(df),'field_identified_unmetered_records':n,'reviewed_unmetered_test_labels':0,
        'unmetered_is_core_target':True,'metered_training_improves_unmetered':'not_evaluated',
        'reason':'No reviewed unmetered train/validation/test labels and as-of predictor table have been supplied. Existing metered proxy scores cannot answer this question.',
        'comparisons':{axis:{name:{'test_r2':None,'mae':None,'brier_score':None,'test_population':'directly observed unmetered only'} for name in ['unmetered_mean','unmetered_time_week','unmetered_face_mean','unmetered_persistence_with_mean_fallback','unmetered_only','unmetered_plus_metered']} for axis in ['future_time','unseen_block']},
        'predictor_families':['demand','curb_supply','time_dependent_restrictions','causal_observation_history'],
        'predictors_substitute_for_labels':False,'production_transfer_authorized':False}
    write_report(report,output);return report


def write_report(report,output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    (out/'comparison.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf8')
    lines=['# Unmetered prediction comparison','',f"Status: **{report['status']}**.",'','Unmetered streets are a core target. Demand, curb supply and time-dependent restrictions are predictors; only direct reviewed observations provide test occupancy labels.','']
    if report.get('reason'):lines.append(report['reason'])
    for axis,groups in report.get('comparisons',{}).items():
        lines+=['',f'## {axis}','','| Training / baseline | Target | Test N | R² | MAE | Brier |','|---|---|---:|---:|---:|---:|']
        for name,targets in groups.items():
            if 'test_r2' in targets:lines.append(f'| {name} | unavailable | 0 | unavailable | unavailable | unavailable |');continue
            for target,m in targets.items():
                fmt=lambda n:'unavailable' if n is None else f'{n:.4f}'
                lines.append(f"| {name} | {target} | {m.get('n',0)} | {fmt(m.get('r2'))} | {fmt(m.get('mae'))} | {fmt(m.get('brier_score'))} |")
        if axis in report.get('paired_transfer_differences',{}):
            lines+=['','Paired changes on the same unmetered test rows (positive favors adding metered labels):','', '| Target | Loss | Mean reduction | Block-bootstrap 95% interval |','|---|---|---:|---|']
            for target,effect in report['paired_transfer_differences'][axis].items():
                lo,hi=effect['block_bootstrap_95_percent_interval']
                lines.append(f"| {target} | {effect['metric']} | {effect['paired_mean_reduction']:.4f} | [{lo:.4f}, {hi:.4f}] |")
    lines+=['','Brier score, log loss, ECE and reliability-bin counts are retained in JSON for every binary model/baseline. Coverage, test block IDs/dates, training populations, capacity-basis strata and selection history are also retained. Unseen-block testing here uses later dates as well: it measures future predictions on new blocks, not an isolated same-time spatial effect.'] if report.get('coverage') else []
    lines+=['','Transfer is not assumed beneficial. Inspect paired unmetered metric changes, uncertainty and coverage for each axis before choosing a training population. This experiment does not automatically publish a model or enable numerical unmetered service forecasts.','', 'No fixed R² target. Earlier rough ranges were speculative, not measured benchmarks or acceptance criteria.']
    (out/'comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf8')


def reviewed_labels(observations,reviews):
    """Separate explicit review from intake acceptance; preserve rejected reasons."""
    required={'observation_id','counts_verified','location_verified','capacity_verified','rules_verified','reviewed_by','reviewed_at_utc'}
    if not required.issubset(reviews):raise ValueError(f'Review table requires {sorted(required)}')
    if observations.observation_id.duplicated().any() or reviews.observation_id.duplicated().any():raise ValueError('Duplicate observation/review IDs')
    unknown=set(reviews.observation_id)-set(observations.observation_id)
    if unknown:raise ValueError('Review references unknown observations')
    f=observations.merge(reviews,on='observation_id',how='left',validate='one_to_one')
    rows=[];rejected=[]
    for _,r in f.iterrows():
        reason=None;label_available=None
        if r.parking_type not in ['unmetered','metered']:reason='Parking population unverified or mixed'
        elif pd.isna(r.complete_face) or r.complete_face!=True:reason='Partial observation is not a full-face label'
        elif any(pd.isna(r[k]) or r[k]!=True for k in ['counts_verified','location_verified','capacity_verified','rules_verified']):reason='Independent review incomplete'
        elif pd.isna(r.reviewed_by) or not str(r.reviewed_by).strip():reason='Reviewer missing'
        elif pd.isna(r.rules_checked) or r.rules_checked!=True:reason='Rules not checked for this observation/profile'
        elif r.get('capacity_basis','unknown') not in ['marked_spaces','estimated_positions']:reason='Capacity basis unknown'
        elif pd.isna(r.get('intended_duration_minutes')) or r.intended_duration_minutes<=0:reason='Intended stay missing for eligible-space labels'
        else:
            try:
                t=pd.Timestamp(r.reviewed_at_utc);end=pd.Timestamp(r.survey_end_utc)
                if pd.isna(t) or t.tzinfo is None or end.tzinfo is None or t<end:reason='Invalid review timestamp'
                else:
                    received=pd.Timestamp(r.get('retrieved_at_utc',r.survey_end_utc))
                    if pd.isna(received) or received.tzinfo is None:reason='Invalid observation availability timestamp'
                    else:label_available=max(t,end,received).isoformat()
            except (ValueError,TypeError):reason='Invalid review timestamp'
        counts=[r.occupied,r.vacant_legal,r.unsuitable,r.surveyed_capacity]
        if reason is None and (any(pd.isna(v) or v<0 or v!=int(v) for v in counts) or sum(counts[:3])!=counts[3] or counts[3]<=0):reason='Counts/denominator do not reconcile'
        if reason:rejected.append({'observation_id':r.observation_id,'reason':reason});continue
        record=r.to_dict();record.update(occupancy_rate=r.occupied/r.surveyed_capacity,available_count=r.vacant_legal,at_least_one=int(r.vacant_legal>0),label_evidence='direct_reviewed_full_face',label_reviewed=True,
            observed_at_utc=r.survey_start_utc,window_end_utc=r.survey_end_utc,label_available_at_utc=label_available)
        rows.append(record)
    return pd.DataFrame(rows),rejected


def prepare_table(observations,reviews,predictors,inventory):
    """Join approved real labels, physical-block lineage and independent predictors.

    Predictors are supplied separately: current context cannot be assumed to have
    been available historically. They may not overwrite any reviewed label field.
    The comparison manifest later declares exactly which predictors are used.
    """
    labels,rejected=reviewed_labels(observations,reviews)
    if not len(labels):raise ValueError('No reviewed full-face labels; collect/review observations before preparing training data')
    if 'observation_id' not in predictors or predictors.observation_id.duplicated().any():raise ValueError('Unique predictor observation IDs required')
    collisions=((set(labels)|{'block_id'})&set(predictors))-{'observation_id'}
    if collisions:raise ValueError(f'Predictors cannot overwrite reviewed label fields: {sorted(collisions)}')
    if not set(labels.observation_id).issubset(set(predictors.observation_id)):raise ValueError('Every approved label requires an explicit as-of predictor row, even if values are missing')
    if inventory.block_face_id.duplicated().any():raise ValueError('Duplicate inventory block-face IDs')
    if not set(labels.block_face_id).issubset(set(inventory.block_face_id)):raise ValueError('Unknown reviewed block-face ID')
    blocks=inventory.set_index('block_face_id').segment_id
    labels['block_id']=labels.block_face_id.map(blocks)
    return labels.merge(predictors,on='observation_id',validate='one_to_one',how='left'),rejected


def prepare(reviews_path,predictors_path,output='data/modeling/unmetered_reviewed.parquet',
            observations_path='data/observations/manual_observations.parquet',inventory_path='data/processed/block_faces.parquet'):
    def read(path):return pd.read_parquet(path) if str(path).endswith('.parquet') else pd.read_csv(path)
    if not Path(observations_path).exists():raise ValueError('No manual observations have been imported; use the phone collector and observations intake first')
    frame,rejected=prepare_table(read(observations_path),read(reviews_path),read(predictors_path),read(inventory_path))
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True);frame.to_parquet(path,index=False)
    audit={'prepared_rows':len(frame),'by_population':frame.parking_type.value_counts().to_dict(),'rejected':rejected,
        'source_sha256':{str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [observations_path,reviews_path,predictors_path,inventory_path]},
        'does_not_train_or_enable_forecasts':True}
    path.with_suffix('.audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8');return audit


def validate_experiment(frame,manifest,feature_names,cfg):
    required={'observation_id','block_face_id','block_id','parking_type','observed_at_utc','window_end_utc','prediction_issued_at_utc','feature_available_at_utc','label_available_at_utc','label_evidence','label_reviewed','intended_duration_minutes','vehicle_class','permit_class'}
    if not required.issubset(frame):raise ValueError(f'Experiment table missing {sorted(required-set(frame))}')
    if frame[list(required-{'permit_class'})].isna().any().any():raise ValueError('Missing experiment identity, evidence, eligibility context or timestamp fields')
    if not frame[['observation_id','block_face_id','block_id']].map(lambda x:isinstance(x,str) and bool(x.strip())).all().all():raise ValueError('Nonempty string observation/physical-block identifiers required')
    if not len(frame) or frame.observation_id.duplicated().any():raise ValueError('Nonempty, unique observation IDs required')
    if not frame.parking_type.isin(['unmetered','metered']).all():raise ValueError('Only explicit metered/unmetered populations may enter this comparison')
    if not frame.label_evidence.eq('direct_reviewed_full_face').all() or not frame.label_reviewed.eq(True).all():raise ValueError('Direct, reviewed full-face labels required; partial meter panels and predictor proxies are incompatible labels')
    if not feature_names or any(c not in frame for c in feature_names):raise ValueError('Declared as-of feature columns missing')
    if any(c in cfg['outcomes'] or c.startswith(('target_','pred_')) or c in ['occupied','vacant_legal','unsuitable','surveyed_capacity'] for c in feature_names):raise ValueError('Target/observation leakage in predictors')
    f=frame.copy().reset_index(drop=True)
    duration=pd.to_numeric(f.intended_duration_minutes,errors='coerce')
    if not (np.isfinite(duration)&duration.gt(0)&duration.eq(np.floor(duration))).all():raise ValueError('Positive integer intended stays required')
    if len(f[['intended_duration_minutes','vehicle_class','permit_class']].fillna('<none>').drop_duplicates())!=1:raise ValueError('Run separate duration/vehicle/permit strata; this first comparison must not mix eligibility targets')
    for name in ['observed_at_utc','window_end_utc','prediction_issued_at_utc','feature_available_at_utc','label_available_at_utc']:
        values=[pd.Timestamp(v) for v in f[name]]
        if any(pd.isna(v) or v.tzinfo is None for v in values):raise ValueError('All experiment timestamps must be aware')
        f[name]=pd.to_datetime(values,utc=True)
    if (f.feature_available_at_utc>f.prediction_issued_at_utc).any() or (f.prediction_issued_at_utc>f.observed_at_utc).any():raise ValueError('Feature/issue timestamp leakage')
    if (f.window_end_utc<f.observed_at_utc).any():raise ValueError('Reversed observation window')
    if (f.label_available_at_utc<f.window_end_utc).any():raise ValueError('Label cannot be available before its observation window ends')
    if (f.block_face_id==f.block_id).any():raise ValueError('Block IDs must group both curb sides')
    for face,g in f.groupby('block_face_id'):
        if g.block_id.nunique()!=1:raise ValueError('Inconsistent physical block lineage')
        if face.startswith('la:boe:') and any(face!=block+':left' and face!=block+':right' for block in g.block_id.unique()):raise ValueError('Block grouping disagrees with canonical City inventory')
    if not {'demand','curb_supply','time_dependent_restrictions'}.issubset(set(manifest.get('feature_families',{}))):raise ValueError('Demand, curb supply and time-dependent restriction families must be declared, even if explicitly unavailable')
    declared={c for cols in manifest['feature_families'].values() for c in cols}
    if not set(feature_names).issubset(declared):raise ValueError('Every used feature needs a declared family')
    for family in ['demand','curb_supply','time_dependent_restrictions']:
        used=set(manifest['feature_families'][family])&set(feature_names)
        if (not used or not f[list(used)].notna().any().any()) and not manifest.get('unavailable_families',{}).get(family):raise ValueError(f'{family} requires observed predictor values or an explicit unavailable reason')
    for feature in feature_names:
        values=pd.to_numeric(f[feature],errors='coerce')
        if (f[feature].notna()&~np.isfinite(values)).any():raise ValueError('Predictors must be numeric finite values or explicit missingness')
        f[feature]=values
    for target in cfg['outcomes']:
        if target not in f:raise ValueError(f'Missing direct target {target}')
        values=pd.to_numeric(f[target],errors='coerce')
        valid=np.isfinite(values)&(values.isin([0,1]) if target=='at_least_one' else values.between(0,1) if target=='occupancy_rate' else values.ge(0)&values.eq(np.floor(values)))
        if not valid.all():raise ValueError('Missing/invalid target: comparisons must use identical complete target rows')
        f[target]=values
    if not f.at_least_one.eq(f.available_count.gt(0).astype(int)).all():raise ValueError('Binary and available-count labels disagree')
    return f


def split_rows(f,axis,split,cfg):
    if axis not in ['future_time','unseen_block']:raise ValueError('Separate future_time/unseen_block evaluations required')
    required={'train_ids','validation_ids','calibration_ids','test_ids'}
    if not required.issubset(split):raise ValueError('Frozen train/validation/calibration/test ID lists required')
    groups={name:set(split[name+'_ids']) for name in ['train','validation','calibration','test']}
    reservation_path=Path('config/field_holdouts.json')
    if reservation_path.exists():
        reservation=json.loads(reservation_path.read_text());reserved=f.block_id.isin(reservation['unseen_physical_blocks'])
        if 'survey_session_id' in f:reserved|=f.survey_session_id.isin(reservation['reserved_session_ids'])
        if 'assignment_id' in f:reserved|=f.assignment_id.isin(reservation['reserved_assignment_ids'])
        protected=set(f.loc[reserved,'observation_id'])
        if any(groups[name]&protected for name in ['train','validation','calibration']):raise ValueError('Reserved physical blocks or sessions cannot be used for model development')
    for a,ids in groups.items():
        if len(ids)!=len(split[a+'_ids']) or not ids.issubset(set(f.observation_id)):raise ValueError('Duplicate or unknown split IDs')
        for b,other in groups.items():
            if a!=b and ids&other:raise ValueError('Split observation overlap')
    parts={name:f.loc[f.observation_id.isin(ids)].copy() for name,ids in groups.items()}
    for name in ['validation','calibration','test']:
        if not parts[name].parking_type.eq('unmetered').all():raise ValueError('Validation, calibration and test must be exclusively unmetered')
    train,validation,cal,test=[parts[k] for k in ['train','validation','calibration','test']]
    if not len(train) or not len(validation) or not len(cal) or not len(test):raise ValueError('Every frozen partition must be nonempty')
    if cfg['embargo_minutes']<0:raise ValueError('Nonnegative embargo required')
    embargo=pd.Timedelta(f"{cfg['embargo_minutes']}min")
    if validation.prediction_issued_at_utc.min()<=train.label_available_at_utc.max()+embargo:raise ValueError('Training label/review availability crosses the validation origin/embargo')
    if cal.prediction_issued_at_utc.min()<=validation.label_available_at_utc.max()+embargo:raise ValueError('Calibration overlaps validation label/review availability')
    if test.prediction_issued_at_utc.min()<=cal.label_available_at_utc.max()+embargo:raise ValueError('Final test overlaps calibration label/review availability')
    prior=set(train.block_id)|set(validation.block_id)|set(cal.block_id)
    if axis=='unseen_block' and prior&set(test.block_id):raise ValueError('Held-out unmetered blocks leak through a metered/opposite-side or development row')
    if axis=='future_time' and not set(test.block_id).issubset(set(train.loc[train.parking_type.eq('unmetered'),'block_id'])):raise ValueError('Primary future-time test must revisit observed unmetered blocks')
    return parts


def persistence_baseline(test,target,mean,axis,cfg):
    column={'occupancy_rate':'lagged_observed_occupancy','available_count':'lagged_observed_available_count','at_least_one':'lagged_observed_at_least_one'}[target]
    pred=np.repeat(mean,len(test));covered=np.zeros(len(test),dtype=bool)
    if axis=='future_time' and column in test and 'lag_age_minutes' in test:
        lag=pd.to_numeric(test[column],errors='coerce');age=pd.to_numeric(test.lag_age_minutes,errors='coerce')
        bounds=lag.between(0,1) if target=='occupancy_rate' else lag.isin([0,1]) if target=='at_least_one' else lag.ge(0)&lag.eq(np.floor(lag))
        if (test[column].notna()&~(np.isfinite(lag)&bounds)).any():raise ValueError('Invalid direct-observation persistence value')
        covered=(lag.notna()&age.between(0,cfg['persistence_max_age_minutes'])).to_numpy()
        pred[covered]=lag.to_numpy()[covered]
    return pred,float(covered.mean())


def _fit(frame,target,features,leaf,seed,balanced=False,meter_weight=1.):
    f=frame.loc[frame[target].notna()].copy();y=f[target].to_numpy(float)
    if not len(f):return None
    if target=='at_least_one' and len(np.unique(y))<2:return ('constant',float(y.mean()),None)
    weights=np.ones(len(f));unmetered=f.parking_type.eq('unmetered').to_numpy()
    if balanced and (~unmetered).any():weights[~unmetered]=meter_weight*unmetered.sum()/(~unmetered).sum()
    cls=HistGradientBoostingClassifier if target=='at_least_one' else HistGradientBoostingRegressor
    model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),cls(max_iter=80,max_leaf_nodes=leaf,min_samples_leaf=5,l2_regularization=10,learning_rate=.06,early_stopping=False,random_state=seed))
    name=model.steps[-1][0];model.fit(f[features],y,**{name+'__sample_weight':weights})
    return ('model',model,None)


def _predict(bundle,frame,target,features):
    kind,model,calibrator=bundle
    if kind=='constant':p=np.repeat(model,len(frame))
    else:p=model.predict_proba(frame[features])[:,1] if target=='at_least_one' else model.predict(frame[features])
    if target in ['at_least_one','occupancy_rate']:p=np.clip(p,0,1)
    else:p=np.maximum(p,0)
    if calibrator is not None:
        z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1);p=calibrator.predict_proba(z)[:,1]
    return p


def _score(y,p,target):return probability_metrics(y,p) if target=='at_least_one' else regression_metrics(y,p)


def validation_objective(metric,target):
    """Select on unmetered validation MSE; calibration has its own Brier objective."""
    return metric['brier_score'] if target=='at_least_one' else metric['rmse']**2


def compare(frame,manifest,cfg=None):
    cfg=cfg or config();features=manifest['features'];f=validate_experiment(frame,manifest,features,cfg)
    report={'version':cfg['version'],'status':'evaluated_on_held_out_unmetered_only','comparisons':{},'paired_transfer_differences':{},'selection':{},
        'test_population':'direct reviewed unmetered observations only','metered_training_improves_unmetered':'inspect paired effects per target/axis; not assumed',
        'production_transfer_authorized':False,'predictors_substitute_for_labels':False,'feature_families':manifest['feature_families'],'feature_unavailable':manifest.get('unavailable_families',{}),'coverage':{},
        'unmetered_is_core_target':True,'metered_scores':'Separate auxiliary experiment: reports/modeling/results_report.md',
        'aspirational_unmetered_test_r2':cfg['unmetered_r2_aspiration'],'aspiration_is_acceptance_criterion':False,
        'spatial_test_design':'Later unseen-block forecasts; includes temporal shift. Does not isolate a same-time spatial effect.'}
    report['target_context']={k:frame[k].iloc[0] for k in ['intended_duration_minutes','vehicle_class','permit_class']}
    report['target_context']={k:None if pd.isna(v) else v.item() if isinstance(v,np.generic) else v for k,v in report['target_context'].items()}
    report['comparison_protocol_sha256']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    report['experiment_config']=cfg
    if set(manifest.get('splits',{}))!={'future_time','unseen_block'}:raise ValueError('Supply separate frozen future-time and unseen-block manifests')
    with threadpool_limits(limits=2):
      for axis,split in manifest['splits'].items():
        parts=split_rows(f,axis,split,cfg);train,val,cal,test=[parts[k] for k in ['train','validation','calibration','test']]
        unmetered=train.loc[train.parking_type.eq('unmetered')]
        if len(unmetered)<cfg['minimum_training_rows'] or len(val)<cfg['minimum_validation_rows'] or len(cal)<cfg['minimum_calibration_rows'] or len(test)<cfg['minimum_test_rows']:raise ValueError('Insufficient direct unmetered observations for the predeclared experiment; do not replace them with metered rows')
        if not train.parking_type.eq('metered').any():raise ValueError('Combined-training comparison requires compatible metered training labels')
        if axis=='unseen_block' and test.block_id.nunique()<cfg['minimum_unseen_test_blocks']:raise ValueError('Insufficient independent held-out unmetered blocks')
        if axis=='unseen_block':
            own_history=[c for c in features if c.startswith('lagged_observed_') or c=='lag_age_minutes']
            if own_history and test[own_history].notna().any().any():raise ValueError('Unseen-block test must not consume held-out own-block observation history')
        results={name:{} for name in ['unmetered_mean','unmetered_time_week','unmetered_face_mean','unmetered_persistence_with_mean_fallback','unmetered_only','unmetered_plus_metered']};effects={};selections={}
        report['coverage'][axis]={
            'rows_by_partition_and_population':{name:part.parking_type.value_counts().to_dict() for name,part in parts.items()},
            'test_observation_ids':sorted(test.observation_id.tolist()),'test_block_ids':sorted(test.block_id.unique().tolist()),
            'test_begin_utc':test.observed_at_utc.min().isoformat(),'test_end_utc':test.window_end_utc.max().isoformat(),
            'test_capacity_basis_counts':test.get('capacity_basis',pd.Series('unspecified',index=test.index)).fillna('unspecified').value_counts().to_dict(),
            'test_sampling_method_counts':test.get('sampling_method',pd.Series('unspecified',index=test.index)).fillna('unspecified').value_counts().to_dict(),
            'test_feature_missing_fraction':test[features].isna().mean().to_dict(),
            'scope':'Only the listed directly observed blocks and dates; no citywide claim'}
        for target in cfg['outcomes']:
            predictions={};y=test[target].to_numpy(float);mean=float(unmetered[target].mean())
            predictions['unmetered_mean']=np.repeat(mean,len(test))
            local_train=unmetered.observed_at_utc.dt.tz_convert('America/Los_Angeles');local_test=test.observed_at_utc.dt.tz_convert('America/Los_Angeles')
            groups=unmetered.assign(weekday=local_train.dt.dayofweek,hour=local_train.dt.hour).groupby(['weekday','hour'])[target].mean().to_dict()
            predictions['unmetered_time_week']=np.array([groups.get((t.dayofweek,t.hour),mean) for t in local_test])
            face_means=unmetered.groupby('block_face_id')[target].mean().to_dict()
            predictions['unmetered_face_mean']=np.array([face_means.get(face,mean) for face in test.block_face_id])
            predictions['unmetered_persistence_with_mean_fallback'],persistence_coverage=persistence_baseline(test,target,mean,axis,cfg)
            for name in ['unmetered_only','unmetered_plus_metered']:
                best=None;choices=[];weights=[0.] if name=='unmetered_only' else [w for w in cfg['auxiliary_metered_weights'] if w>0]
                if not weights:raise ValueError('Positive auxiliary weights required for an actual combined-training comparison')
                for weight in weights:
                    fitted=unmetered if weight==0 else train
                    for leaf in cfg['parameter_candidates']:
                        bundle=_fit(fitted,target,features,leaf,cfg['seed'],balanced=weight>0,meter_weight=weight)
                        pred=_predict(bundle,val,target,features);metric=_score(val[target],pred,target)
                        loss=validation_objective(metric,target)
                        choices.append({'metered_weight':weight,'leaf_nodes':leaf,'validation_loss':loss,'validation_rmse':metric.get('rmse'),'validation_mae':metric.get('mae'),'objective':'brier' if target=='at_least_one' else 'mse'})
                        if best is None or loss<best[0]:best=(loss,bundle,weight,leaf)
                _,bundle,weight,leaf=best
                if target=='at_least_one' and cal[target].nunique()==2:
                    p=_predict(bundle,cal,target,features);z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1)
                    calibrator=LogisticRegression(C=1,max_iter=200).fit(z,cal[target]);bundle=(bundle[0],bundle[1],calibrator)
                predictions[name]=_predict(bundle,test,target,features)
                selections.setdefault(name,{})[target]={'metered_weight':weight,'leaf_nodes':leaf,'unmetered_validation_choices':choices,'uses_metered_labels':weight>0,'selection_objective':'brier' if target=='at_least_one' else 'mse',
                    'calibration':'logistic_on_separate_unmetered_calibration' if target=='at_least_one' and cal[target].nunique()==2 else 'not_fitted'}
            for name,pred in predictions.items():
                quality={}
                if 'capacity_basis' in test:
                    for basis,group in test.groupby('capacity_basis',dropna=False):
                        mask=test.index.isin(group.index);quality[str(basis)]=_score(y[mask],pred[mask],target)
                results[name][target]={**_score(y,pred,target),'test_blocks':int(test.block_id.nunique()),'test_population':'unmetered','prediction_coverage':1.,'by_capacity_basis':quality}
                if name=='unmetered_persistence_with_mean_fallback':results[name][target].update(recent_state_coverage=persistence_coverage,fallback_fraction=1-persistence_coverage,
                    persistence_note='Previous direct state within configured issue-time freshness, otherwise training mean. Own-block persistence unavailable on unseen blocks.')
            loss=lambda p:np.square(y-p) if target=='at_least_one' else np.abs(y-p)
            delta=loss(predictions['unmetered_only'])-loss(predictions['unmetered_plus_metered'])
            block_delta=pd.DataFrame({'block':test.block_id.to_numpy(),'delta':delta}).groupby('block').delta.agg(['sum','count'])
            rng=np.random.default_rng(cfg['seed']);boot=[]
            for _ in range(cfg['bootstrap_replicates']):
                sample=block_delta.iloc[rng.integers(0,len(block_delta),len(block_delta))];boot.append(float(sample['sum'].sum()/sample['count'].sum()))
            effects[target]={'metric':'Brier reduction' if target=='at_least_one' else 'MAE reduction','positive_favors_metered':True,'paired_mean_reduction':float(delta.mean()),
                'block_bootstrap_95_percent_interval':[float(np.quantile(boot,.025)),float(np.quantile(boot,.975))],
                'independent_test_blocks':len(block_delta),'warning':'Few blocks or sampling bias can make this interval unreliable; no automatic deployment approval'}
        report['comparisons'][axis]=results;report['paired_transfer_differences'][axis]=effects;report['selection'][axis]=selections
    return report


def run(table=None,manifest_path=None,output='reports/unmetered'):
    if table is None:return unavailable_report(output=output)
    if manifest_path is None:raise ValueError('Explicit frozen split/feature manifest required')
    path=Path(table);frame=pd.read_parquet(path) if path.suffix=='.parquet' else pd.read_csv(path)
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf8'))
    report=compare(frame,manifest);report['input_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();write_report(report,output);return report
