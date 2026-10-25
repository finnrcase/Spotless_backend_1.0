"""Serving adapter around preserved fitted artifacts; does not refit models."""
from datetime import datetime,timedelta,timezone
import numpy as np
import pandas as pd
from ..forecasting import request_forecast
from ..model_features import calendar_features
from .schemas import PanelEstimate

UTC=timezone.utc


class Inference:
    def __init__(self,repository):self.repo=repository

    def evidence(self,face_id,issue,replay=False):
        r=self.repo
        if replay:
            if not r.load_model_data():return {'status':'missing','observation_age_minutes':None,'scope':'historical replay'}
            rows=r.historical.loc[(r.historical.block_face_id==face_id)&(r.historical.observed_at_utc<=issue)]
        else:
            rows=r.current
            if len(rows):
                ids=set(r.mapping.loc[r.mapping.block_face_id==face_id,'space_id'])
                rows=rows.loc[rows.space_id.isin(ids)&(rows.observed_at_utc<=issue)]
        manual=r.manual.loc[(r.manual.block_face_id==face_id)&(r.manual.survey_end_utc<=issue)&(r.manual.retrieved_at_utc<=issue)] if len(r.manual) else pd.DataFrame()
        if len(manual) and (not len(rows) or manual.survey_end_utc.max()>rows.observed_at_utc.max()):
            latest=manual.sort_values('survey_end_utc').iloc[-1];age=max(0,(pd.Timestamp(issue)-latest.survey_end_utc).total_seconds()/60)
            return {'status':'recent' if age<=15 else 'stale','observation_age_minutes':age,'last_observed_at':latest.survey_end_utc.isoformat(),
                'scope':'manual report; location/rules/capacity may require review','sampling_method':latest.get('sampling_method','unspecified'),
                'reported_counts':{k:None if pd.isna(latest[k]) else int(latest[k]) for k in ['occupied','vacant_legal','unsuitable','surveyed_capacity']},
                'location_review_required':bool(latest.get('location_review_required',True)),'label_review_required':bool(latest.get('label_review_required',True)),
                'does_not_label_full_block':not bool(latest.complete_face),'automatic_training':False}
        if not len(rows):return {'status':'missing','observation_age_minutes':None,'last_observed_at':None,'scope':'historical replay' if replay else 'current source snapshot'}
        newest=rows.observed_at_utc.max();age=max(0,(pd.Timestamp(issue)-newest).total_seconds()/60)
        return {'status':'recent' if age<=r.config['recent_evidence_minutes'] else 'stale','observation_age_minutes':age,'last_observed_at':newest.isoformat(),
                'scope':'historical event timestamp replay; delivery latency unverified' if replay else 'last-known transactions; no heartbeat guarantee',
                'does_not_label_full_block':True}

    def estimate(self,face_id,issue,arrival,stay,profile,experimental,replay=False):
        r=self.repo;age=(arrival-issue).total_seconds()/60
        empty=(None,None,{'status':'insufficient_data','reason':'No usable source/history at this issue time; no stale state extension'})
        if not r.load_model_data():return empty
        base=r.design.loc[(r.design.block_face_id==face_id)&(r.design.issued_at_utc<=issue)].copy()
        if not len(base):
            if experimental:
                segment=r.faces.loc[face_id].segment_id
                context=r.context
                row=context.loc[context.segment_id==segment] if len(context) else pd.DataFrame()
                if len(row):
                    rank=float(context.business_300.rank(pct=True).loc[row.index[0]])
                    return None,rank,{'status':'experimental_extrapolation','reason':'Business-density percentile is an unvalidated activity prior, not parking availability'}
            return empty
        # Historical features can be replayed only at their actual 15-minute origins.
        origin=pd.Timestamp(issue).floor('15min')
        if age<=120:
            if not replay:return None,None,{'status':'insufficient_data','reason':'Current snapshot lacks a reconstructed recent feature window; a successful poll alone cannot activate this historical model'}
            selected=base.loc[base.issued_at_utc==origin].copy()
            if not len(selected):return empty
            origin_lead=(pd.Timestamp(arrival)-origin).total_seconds()/60
            horizon=next((h for h in [0,15,30,60,120] if h>=max(0,origin_lead)),120)
        else:
            selected=base.sort_values('issued_at_utc').tail(1).copy();horizon=int(np.ceil(age))
        selected['issued_at_utc']=origin
        selected['arrival_time_utc']=origin+pd.Timedelta(minutes=horizon)
        selected['horizon_minutes']=horizon if horizon<=120 else 0
        cal=calendar_features(pd.Series([pd.Timestamp(arrival)],index=selected.index))
        for c in cal:selected[c]=cal[c].to_numpy()
        try:
            result=request_forecast(face_id,origin,origin+pd.Timedelta(minutes=horizon),stay,profile,False,selected,r.context,r.historical,
                face_inventory=r.faces[['block_face_id','segment_id']],model_loader=r.model)
        except (OSError,ValueError,KeyError) as exc:
            return None,None,{'status':'insufficient_data','reason':f'Model/feature unavailable: {type(exc).__name__}'}
        diagnostics=result.sensor_panel_diagnostics
        if result.support!='experimental_sensor_panel' or not diagnostics:return None,None,{'status':'insufficient_data','reason':result.unavailable_reason}
        panel=PanelEstimate(occupancy_rate=diagnostics.get('time_weighted_panel_occupancy_rate'),expected_vacant_count=diagnostics.get('expected_panel_vacant_count'),
            probability_any_panel_vacant=diagnostics.get('probability_any_panel_vacant_proxy'),panel_sensor_count=diagnostics.get('panel_sensor_count'),
            count_range=diagnostics.get('expected_panel_vacant_count_range'),modeled_horizon_minutes=horizon,
            net_change_15m=diagnostics.get('expected_panel_net_change_15m'),net_change_30m=diagnostics.get('expected_panel_net_change_30m'),net_change_60m=diagnostics.get('expected_panel_net_change_60m'))
        return panel,None,{'status':'model_estimate','reason':result.unavailable_reason,'feature_origin_at':origin.isoformat(),'model_mode':result.forecast_mode,
            'arrival_resolution':'Nearest supported upper lead; requested arrival calendar retained. No numeric interpolation.',
            'model_uncertainty':result.model_uncertainty}
