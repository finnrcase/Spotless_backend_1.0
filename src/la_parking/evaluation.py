"""Leakage checks and honest held-out reporting. No fitted model or labels invented.

Each input row represents one block-face observation/window. Block grouping must
join both sides to the same physical block; do not hold out sides independently.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

TARGETS=['occupancy_rate','occupied_count','available_count']
KINDS=['metered','unmetered','mixed','unknown']
REQUIRED=['observation_id','block_id','block_face_id','parking_type','observed_at_utc','window_end_utc','prediction_issued_at_utc','feature_available_at_utc']


def _times(frame):
    frame=frame.copy().reset_index(drop=True)
    for field in ['observed_at_utc','window_end_utc','prediction_issued_at_utc','feature_available_at_utc']:
        # Reject naive input rather than silently assuming it was stored in UTC.
        stamps=[pd.Timestamp(x) for x in frame[field]]
        if any(pd.isna(x) or x.tzinfo is None for x in stamps): raise ValueError(f'{field} requires timezone-aware timestamps')
        frame[field]=pd.to_datetime(stamps,utc=True)
    if (frame.window_end_utc<frame.observed_at_utc).any(): raise ValueError('Label window end precedes observation')
    if (frame.prediction_issued_at_utc>frame.observed_at_utc).any(): raise ValueError('Prediction issued after its target observation')
    if (frame.feature_available_at_utc>frame.prediction_issued_at_utc).any(): raise ValueError('Feature leakage: data unavailable at prediction issue time')
    return frame


def validate_split(train,test,axis,embargo_minutes=60):
    if axis not in ['future_time','unseen_block']: raise ValueError('Choose future_time or unseen_block explicitly')
    if not len(train) or not len(test): raise ValueError('Nonempty train and held-out test tables required')
    for name,f in [('train',train),('test',test)]:
        missing=set(REQUIRED)-set(f.columns)
        if missing: raise ValueError(f'{name} missing columns: {sorted(missing)}')
        if f[REQUIRED].isna().any().any(): raise ValueError(f'{name} has missing IDs, type or timestamps')
        if f.observation_id.duplicated().any(): raise ValueError(f'{name} has duplicate observation IDs')
        if not f.parking_type.isin(KINDS).all(): raise ValueError('Parking type must be explicit')
        if (f.block_id==f.block_face_id).any(): raise ValueError('Physical block ID must group both face sides; do not use face ID as block ID')
    if set(train.observation_id)&set(test.observation_id): raise ValueError('Train/test observation overlap')
    lineage=pd.concat([train[['block_face_id','block_id']],test[['block_face_id','block_id']]],ignore_index=True)
    if (lineage.groupby('block_face_id').block_id.nunique()>1).any(): raise ValueError('A block face has conflicting physical block IDs')
    train,test=_times(train),_times(test)
    block_overlap=set(train.block_id)&set(test.block_id)
    if axis=='future_time':
        if embargo_minutes<0: raise ValueError('Embargo must be nonnegative')
        if test.prediction_issued_at_utc.min()<=train.window_end_utc.max()+pd.Timedelta(minutes=embargo_minutes): raise ValueError('Future-time test must follow training label windows plus embargo')
        if not set(test.block_id).issubset(set(train.block_id)): raise ValueError('Primary future-time test uses previously observed blocks; report new-block future tests separately')
    elif block_overlap: raise ValueError('Unseen-block test leaks physical blocks across train/test')
    return train,test


def regression_metrics(y,prediction):
    y=np.asarray(y,dtype=float); p=np.asarray(prediction,dtype=float)
    if y.ndim!=1 or p.ndim!=1 or len(y)!=len(p) or not np.isfinite(y).all() or not np.isfinite(p).all(): raise ValueError('Regression metric inputs must be paired finite vectors')
    if not len(y): return {'n':0,'r2':None,'mae':None,'rmse':None,'r2_note':'No paired predictions'}
    denominator=float(np.square(y-y.mean()).sum())
    # Keep negative R². Never convert undefined constant-target R² into 0 or 1.
    r2=None if len(y)<2 or denominator==0 else float(1-np.square(y-p).sum()/denominator)
    return {'n':len(y),'r2':r2,'mae':float(np.abs(y-p).mean()),'rmse':float(np.sqrt(np.square(y-p).mean())),
            'r2_note':'Undefined for fewer than two samples or constant target' if r2 is None else None}


def probability_metrics(y,p,bins=10):
    y=np.asarray(y,dtype=float); p=np.asarray(p,dtype=float)
    if y.ndim!=1 or p.ndim!=1 or len(y)!=len(p) or not np.isfinite(y).all() or not np.isfinite(p).all(): raise ValueError('Probability metric inputs must be paired finite vectors')
    if not isinstance(bins,int) or bins<1: raise ValueError('Positive integer calibration bin count required')
    if not len(y): return {'n':0,'brier_score':None,'log_loss':None,'ece':None,'reliability_bins':[]}
    if not np.isin(y,[0,1]).all() or not ((p>=0)&(p<=1)).all(): raise ValueError('Invalid binary targets or probabilities')
    bin_ids=np.minimum((p*bins).astype(int),bins-1); reliability=[]; ece=0.
    for b in range(bins):
        selected=bin_ids==b; n=int(selected.sum())
        mean=float(p[selected].mean()) if n else None; freq=float(y[selected].mean()) if n else None
        reliability.append({'lower':b/bins,'upper':(b+1)/bins,'n':n,'mean_probability':mean,'observed_frequency':freq})
        if n: ece+=n/len(y)*abs(mean-freq)
    clipped=np.clip(p,1e-15,1-1e-15)
    return {'n':len(y),'positive_rate':float(y.mean()),'brier_score':float(np.square(y-p).mean()),
            'log_loss':float(-(y*np.log(clipped)+(1-y)*np.log(1-clipped)).mean()),'ece':float(ece),'reliability_bins':reliability,
            'calibration_note':'Reliability is descriptive at this sample size; Brier/log loss also measure discrimination.'}


def _target_valid(series,target):
    values=pd.to_numeric(series,errors='coerce')
    finite=np.isfinite(values)
    bounds=values.between(0,1) if target=='occupancy_rate' else values.ge(0)&values.eq(np.floor(values))
    if (series.notna()&~(finite&bounds)).any(): raise ValueError(f'Invalid observed {target}')
    return values


def evaluate(train,test,axis,embargo_minutes=60):
    train,test=validate_split(train,test,axis,embargo_minutes)
    report={'axis':axis,'embargo_minutes':embargo_minutes if axis=='future_time' else None,
            'scope':'observed held-out blocks only; no validated citywide claim',
            'aspirational_unmetered_test_r2':None,'aspiration_is_acceptance_criterion':False,
            'train_rows':len(train),'test_rows':len(test),'test_blocks':int(test.block_id.nunique()),
            'train_window_end_max_utc':str(train.window_end_utc.max()),'test_issue_min_utc':str(test.prediction_issued_at_utc.min()),
            'time_generalization_validated':axis=='future_time','by_parking_type':{}}
    for kind in KINDS:
        fit=train[train.parking_type==kind].copy(); held=test[test.parking_type==kind].copy()
        item={'status':'evaluated' if len(held) else 'no_held_out_labels','test_rows':len(held),'test_blocks':int(held.block_id.nunique()),
              'test_block_ids':sorted(str(v) for v in held.block_id.unique()),
              'label_evidence_counts':held.get('label_evidence',pd.Series('unspecified',index=held.index)).fillna('unspecified').value_counts().to_dict(),
              'capacity_basis_counts':held.get('capacity_basis',pd.Series('unspecified',index=held.index)).fillna('unspecified').value_counts().to_dict(),
              'regression':{},'finding_at_least_one_space':None}
        if not len(held): report['by_parking_type'][kind]=item; continue
        local=pd.to_datetime(held.observed_at_utc,utc=True).dt.tz_convert('America/Los_Angeles')
        train_local=pd.to_datetime(fit.observed_at_utc,utc=True).dt.tz_convert('America/Los_Angeles')
        for target in TARGETS:
            if target not in held: continue
            y=_target_valid(held[target],target)
            prediction=pd.to_numeric(held.get('pred_'+target,pd.Series(np.nan,index=held.index)),errors='coerce')
            supplied=held.get('pred_'+target,pd.Series(np.nan,index=held.index))
            if (supplied.notna()&~np.isfinite(prediction)).any(): raise ValueError('Nonfinite or nonnumeric prediction')
            selected=y.notna()&prediction.notna(); score=regression_metrics(y[selected],prediction[selected])
            score.update(observed_targets=int(y.notna().sum()),prediction_coverage=float(selected.sum()/y.notna().sum()) if y.notna().sum() else None,baselines={})
            if target in fit:
                fitted=_target_valid(fit[target],target).dropna()
                if len(fitted) and selected.any():
                    mean=float(fitted.mean())
                    score['baselines']['train_mean']=regression_metrics(y[selected],np.repeat(mean,selected.sum()))
                    historical=fit.loc[fitted.index,['block_face_id']].copy(); historical['y']=fitted
                    historical['weekday']=train_local.loc[fitted.index].dt.dayofweek; historical['hour']=train_local.loc[fitted.index].dt.hour
                    hour_means=historical.groupby(['weekday','hour']).y.mean().to_dict(); face_means=historical.groupby('block_face_id').y.mean().to_dict()
                    hourly=[hour_means.get((local.loc[i].dayofweek,local.loc[i].hour),mean) for i in held.index[selected]]
                    face_pred=[face_means.get(held.loc[i,'block_face_id'],mean) for i in held.index[selected]]
                    score['baselines']['train_time_of_week']=regression_metrics(y[selected],hourly)
                    score['baselines']['train_face_mean_global_fallback']=regression_metrics(y[selected],face_pred)
                    score['mae_improvement_over_train_mean']=score['baselines']['train_mean']['mae']-score['mae']
            item['regression'][target]=score
        if 'at_least_one' in held:
            y=pd.to_numeric(held.at_least_one,errors='coerce'); p=pd.to_numeric(held.get('pred_at_least_one',pd.Series(np.nan,index=held.index)),errors='coerce')
            supplied=held.get('pred_at_least_one',pd.Series(np.nan,index=held.index))
            if (supplied.notna()&p.isna()).any(): raise ValueError('Nonnumeric probability prediction')
            if (held.at_least_one.notna()&~y.isin([0,1])).any(): raise ValueError('Invalid at-least-one observed target')
            if (p.notna()&(~np.isfinite(p)|~p.between(0,1))).any(): raise ValueError('Invalid probability prediction')
            selected=y.notna()&p.notna(); score=probability_metrics(y[selected],p[selected]); score['observed_targets']=int(y.notna().sum())
            score['prediction_coverage']=float(selected.sum()/y.notna().sum()) if y.notna().sum() else None
            if 'at_least_one' in fit:
                f=pd.to_numeric(fit.at_least_one,errors='coerce').dropna()
                if not f.isin([0,1]).all(): raise ValueError('Invalid training probability labels')
                if len(f) and selected.any(): score['train_prevalence_baseline']=probability_metrics(y[selected],np.repeat(f.mean(),selected.sum()))
            item['finding_at_least_one_space']=score
        report['by_parking_type'][kind]=item
    return report


def run_evaluation(train_path,test_path,axis,output='reports/evaluation.json',embargo_minutes=60):
    def read(path): return pd.read_parquet(path) if str(path).endswith('.parquet') else pd.read_csv(path)
    report=evaluate(read(train_path),read(test_path),axis,embargo_minutes)
    path=Path(output); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf8')
    lines=[f'# Held-out evaluation: {axis}','','Scope: observed held-out blocks only. No validated citywide accuracy claim.','', '| Parking type | Target | Paired test N | Test R² | MAE | Train-mean baseline MAE | Prediction coverage |','|---|---|---:|---:|---:|---:|---:|']
    for kind,item in report['by_parking_type'].items():
        if item['status']=='no_held_out_labels': lines.append(f'| {kind} | No held-out labels | 0 | — | — | — | — |')
        for target,m in item['regression'].items():
            fmt=lambda n:'—' if n is None else f'{n:.4f}'
            lines.append(f"| {kind} | {target} | {m['n']} | {fmt(m['r2'])} | {fmt(m['mae'])} | {fmt(m['baselines'].get('train_mean',{}).get('mae'))} | {fmt(m['prediction_coverage'])} |")
    lines+=['','| Parking type | Probability N | Brier | Log loss | ECE | Train-prevalence Brier |','|---|---:|---:|---:|---:|---:|']
    for kind,item in report['by_parking_type'].items():
        m=item['finding_at_least_one_space']
        if m:
            fmt=lambda n:'—' if n is None else f'{n:.4f}'
            lines.append(f"| {kind} | {m['n']} | {fmt(m['brier_score'])} | {fmt(m['log_loss'])} | {fmt(m['ece'])} | {fmt(m.get('train_prevalence_baseline',{}).get('brier_score'))} |")
        else: lines.append(f'| {kind} | 0 | — | — | — | — |')
    lines+=['','Reliability bins, their sample counts and probability prediction coverage are in the adjacent JSON. Empty rows remain unsupported.','', 'No fixed R² target; earlier rough ranges were speculative. Negative and undefined R² remain visible.']
    path.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return report


def write_readiness(output='reports/evaluation_readiness.json'):
    source=Path('data/observations/manual_observations.parquet')
    observations=pd.read_parquet(source) if source.exists() else pd.DataFrame()
    unmetered=int(observations.parking_type.eq('unmetered').sum()) if 'parking_type' in observations else 0
    model_catalog=Path('artifacts/models/catalog.json')
    trained=model_catalog.exists()
    report={'status':'experimental_metered_sensor_panel_models_available' if trained else 'no_trained_model_or_held_out_predictions','accepted_manual_observations':len(observations),
            'field_identified_unmetered_observations':unmetered,'reviewed_unmetered_test_labels':'not established',
            'axes':{a:{k:{'test_r2':None,'mae':None,'probability_calibration':None,'reason':'No verified full-curb suitability labels; experimental sensor-panel metrics are separate' if trained else 'No trained model, frozen split and held-out prediction table supplied'} for k in KINDS} for a in ['future_time','unseen_block']},
            'aspirational_unmetered_test_r2':None,'aspiration_is_acceptance_criterion':False,
            'validated_citywide_accuracy':False}
    if trained: report['experimental_sensor_panel_metrics']='reports/modeling/results.json'
    path=Path(output); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(report,indent=2),encoding='utf8')
    return report
