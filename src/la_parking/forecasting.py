"""Forecast requests separate modeled sensor panels from legally suitable parking."""
import json
from pathlib import Path
from typing import Literal
import joblib
import numpy as np
import pandas as pd
import geopandas as gpd
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,model_validator
from .modeling import prep_scenario,predict_head
from .model_features import calendar_features


class ForecastArtifact(BaseModel):
    model_config=ConfigDict(extra='forbid')
    block_face_id: str
    issued_at: AwareDatetime
    arrival_time: AwareDatetime
    horizon_minutes: int=Field(ge=0)
    intended_stay_minutes: int=Field(gt=0)
    eligibility_profile: dict
    forecast_mode: Literal['nowcast','forecast','typical_pattern','experimental_transfer','insufficient_data']
    physical_capacity: int | None=None
    eligible_capacity_estimate: float | None=None
    eligible_capacity_range: list[float] | None=None
    expected_available_spaces: float | None=None
    expected_available_spaces_range: list[float] | None=None
    probability_at_least_one: float | None=Field(default=None,ge=0,le=1)
    expected_net_change_15m: float | None=None
    expected_net_change_30m: float | None=None
    expected_net_change_60m: float | None=None
    restriction_status: Literal['unknown','verified_allowed','verified_prohibited']='unknown'
    evidence_class: str
    observation_age_minutes: float | None=None
    rule_uncertainty: str='unresolved full-duration restrictions and eligibility'
    capacity_uncertainty: str='physical/eligible capacity unverified'
    model_uncertainty: dict
    support: Literal['experimental_sensor_panel','experimental_unmetered_prior','insufficient_data']
    model_version: str='sensor-panel-v1'
    unavailable_reason: str | None=None
    sensor_panel_diagnostics: dict | None=None

    @model_validator(mode='after')
    def honest_support(self):
        if self.arrival_time<self.issued_at: raise ValueError('Arrival before issue')
        if abs((self.arrival_time-self.issued_at).total_seconds()/60-self.horizon_minutes)>1e-6: raise ValueError('Horizon does not match request times')
        if self.restriction_status=='unknown' and any(v is not None for v in [self.eligible_capacity_estimate,self.probability_at_least_one,self.expected_available_spaces]): raise ValueError('Unknown rules cannot support numerical suitable-space predictions')
        if self.support=='insufficient_data' and self.sensor_panel_diagnostics: raise ValueError('Insufficient-data output must not hide a numeric panel forecast')
        return self


def whole_stay_rules(arrival,stay_minutes,profile,rules,physical_capacity=None,complete=False):
    """Small explicit effective-interval rule connector, not a sign-text interpreter.

    Unknown schedule/coverage yields unknown. Confirmed face-wide prohibitions
    intersecting any part of the stay make that entire stay unsuitable.
    """
    a=pd.Timestamp(arrival);end=a+pd.Timedelta(minutes=stay_minutes)
    if a.tzinfo is None or stay_minutes<=0: raise ValueError('Aware arrival and positive stay required')
    for rule in rules:
        start=pd.Timestamp(rule['start_utc']);stop=pd.Timestamp(rule['end_utc'])
        if start.tzinfo is None or stop.tzinfo is None or stop<=start: raise ValueError('Invalid effective rule interval')
        if start<end and stop>a:
            if rule.get('status')!='verified': return {'status':'unknown','eligible_capacity':None}
            if rule['type']=='no_parking': return {'status':'verified_prohibited','eligible_capacity':0}
            if rule['type']=='permit' and profile.get('permit_class') not in rule.get('allowed_permits',[]): return {'status':'verified_prohibited','eligible_capacity':0}
            if rule['type'] not in ['allow','permit']: return {'status':'unknown','eligible_capacity':None}
    if not complete or physical_capacity is None: return {'status':'unknown','eligible_capacity':None}
    return {'status':'verified_allowed','eligible_capacity':physical_capacity}


def request_forecast(face_id,issued_at,arrival_time,intended_stay=60,profile=None,experimental_transfer=False,design=None,context=None,event_history=None,face_inventory=None,model_loader=None,modeling_config=None):
    issued=pd.Timestamp(issued_at);arrival=pd.Timestamp(arrival_time)
    if issued.tzinfo is None or arrival.tzinfo is None or arrival<issued: raise ValueError('Aware issue/arrival times in order required')
    horizon=(arrival-issued).total_seconds()/60
    if not float(horizon).is_integer(): raise ValueError('Whole-minute forecast horizon required')
    horizon=int(horizon)
    f=ForecastArtifact(block_face_id=face_id,issued_at=issued.to_pydatetime(),arrival_time=arrival.to_pydatetime(),horizon_minutes=horizon,intended_stay_minutes=intended_stay,
        eligibility_profile=profile or {'vehicle_class':'standard_passenger','permit_class':None},forecast_mode='insufficient_data',evidence_class='no_verified_occupancy',
        model_uncertainty={'status':'unavailable'},support='insufficient_data',unavailable_reason='No usable history at this issue time; capacity and full-duration rules unverified')
    faces=face_inventory if face_inventory is not None else pd.read_parquet('data/processed/block_faces.parquet',columns=['block_face_id','segment_id'])
    load=model_loader or joblib.load
    known=faces.loc[faces.block_face_id==face_id]
    if not len(known): f.unavailable_reason='Unknown or out-of-scope block face';return f
    if design is None: design=pd.read_parquet('data/modeling/design.parquet')
    past=design.loc[(design.block_face_id==face_id)&(design.issued_at_utc<=issued)]
    sensor_face=len(past)>0
    if not sensor_face:
        if experimental_transfer:
            context=pd.read_parquet('data/modeling/current_context.parquet') if context is None else context
            row=context.loc[context.segment_id==known.segment_id.iloc[0]]
            if len(row):
                rank=float(context.business_300.rank(pct=True).loc[row.index[0]])
                f.forecast_mode='experimental_transfer';f.support='experimental_unmetered_prior';f.evidence_class='unvalidated_business_density_prior'
                f.sensor_panel_diagnostics={'relative_activity_rank':rank,'meaning':'current registered-business density percentile, not an occupancy probability','unmetered_validated':False}
                f.model_uncertainty={'status':'unvalidated transfer prior; uncertainty uncalibrated'}
        f.unavailable_reason='No verified unmetered or full-curb labels; numerical suitable-space forecast unavailable'
        return f
    cfg=modeling_config or json.loads(Path('config/modeling.json').read_text())
    calibrated_until=pd.Timestamp(cfg['calibration_end_local'],tz='America/Los_Angeles').tz_convert('UTC')
    if issued<calibrated_until:
        f.unavailable_reason='Issue time precedes the fitted model calibration cutoff';return f
    exact=past.loc[(past.issued_at_utc==issued)&(past.horizon_minutes==(horizon if horizon<=120 else 0))]
    if horizon>120 and not len(exact):
        exact=past.loc[past.horizon_minutes==0].sort_values('issued_at_utc').tail(1).copy()
        exact['issued_at_utc']=issued
    if not len(exact):
        f.unavailable_reason='No historical/recent feature row at this issue time; stale history is not carried forward'
        return f
    row=prep_scenario(exact.iloc[:1].copy(),'future_time')
    if event_history is None:
        event_history=pd.concat([pd.read_parquet(p) for p in Path('data/processed').glob('pilot_history_20*.parquet')],ignore_index=True)
        mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet').query("join_status=='matched'")
        event_history=event_history.merge(mapping[['space_id','block_face_id']],on='space_id',how='inner')
    past_events=event_history.loc[(event_history.block_face_id==face_id)&(event_history.observed_at_utc<=issued)]
    age=float((issued-past_events.observed_at_utc.max()).total_seconds()/60) if len(past_events) else None
    f.observation_age_minutes=age
    if horizon<=120 and (age is None or age>15 or pd.isna(row.lag_rate_15.iloc[0]) or row.lag_coverage.iloc[0]<.25):
        f.unavailable_reason='Latest mapped transaction or recent sensor-time features exceed the freshness policy';return f
    if horizon>120:
        row['arrival_time_utc']=arrival
        cal=calendar_features(row.arrival_time_utc)
        for c in cal: row[c]=cal[c].to_numpy()
        bundle=load('artifacts/models/future_time_typical_pattern.joblib')
        pred=float(predict_head(bundle,row)[0]);radius=bundle.get('conformal_radius')
        diagnostics={'time_weighted_panel_occupancy_rate':pred,'interval':None if radius is None else [max(0,pred-radius),min(1,pred+radius)],'mode':'typical pattern; no live occupancy prediction'}
        f.forecast_mode='typical_pattern'
    elif horizon not in [0,15,30,60,120]:
        f.unavailable_reason='Supported operational horizons are 0/15/30/60/120 minutes; other horizons are unavailable';return f
    else:
        # Fixed operational choice: boosted selected/tuned using rolling origins; not chosen by final-test score.
        bundles={target:load(f'artifacts/models/future_time_h{horizon}_{target}_boosted.joblib') for target in ['occupancy_rate','available_count','any_panel_vacant']}
        rate=float(predict_head(bundles['occupancy_rate'],row)[0]);count=float(predict_head(bundles['available_count'],row)[0]);prob=float(predict_head(bundles['any_panel_vacant'],row)[0])
        diagnostics={'time_weighted_panel_occupancy_rate':rate,'expected_panel_vacant_count':count,'probability_any_panel_vacant_proxy':prob,
            'panel_sensor_count':int(row.panel_sensor_count.iloc[0]),'full_curb_prediction':False,'legality_verified':False}
        for target,value,name,maximum in [('occupancy_rate',rate,'panel_occupancy_rate_range',1),('available_count',count,'expected_panel_vacant_count_range',int(row.panel_sensor_count.iloc[0]))]:
            radius=bundles[target].get('conformal_radius')
            diagnostics[name]=None if radius is None else [max(0,value-radius),min(maximum,value+radius)]
        for future in [15,30,60]:
            if horizon+future<=120 and horizon+future in [0,15,30,60,120]:
                next_bundle=load(f'artifacts/models/future_time_h{horizon+future}_available_count_boosted.joblib')
                next_row=row.copy();next_row['arrival_time_utc']=arrival+pd.Timedelta(minutes=future)
                cal=calendar_features(next_row.arrival_time_utc)
                for c in cal: next_row[c]=cal[c].to_numpy()
                diagnostics[f'expected_panel_net_change_{future}m']=float(predict_head(next_bundle,next_row)[0])-count
        f.forecast_mode='nowcast' if horizon==0 else 'forecast'
    f.evidence_class='retrospective_sensor_panel_proxy';f.support='experimental_sensor_panel';f.sensor_panel_diagnostics=diagnostics
    f.model_uncertainty={'status':'calibration-period residual ranges; temporal dependence limits coverage guarantee','nominal_regression_coverage':.9,'scope':'sensor panel only'}
    f.unavailable_reason='Sensor diagnostics only: unknown total capacity, incomplete curb coverage, unverified historical geometry and full-duration rules'
    return ForecastArtifact.model_validate(f.model_dump())


def build_forecast_artifacts():
    design=pd.read_parquet('data/modeling/design.parquet');ctx=pd.read_parquet('data/modeling/current_context.parquet')
    issued=pd.Timestamp('2026-08-25 17:00:00Z')
    events=pd.concat([pd.read_parquet(p) for p in Path('data/processed').glob('pilot_history_20*.parquet')],ignore_index=True)
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet').query("join_status=='matched'")
    events=events.merge(mapping[['space_id','block_face_id']],on='space_id',how='inner')
    sampled=design.loc[(design.issued_at_utc==issued)&(design.horizon_minutes==0)].sort_values('block_face_id').head(12)
    records=[]
    for face in sampled.block_face_id:
        for horizon in [0,15,30,60,120,7*24*60]:
            record=request_forecast(face,issued,issued+pd.Timedelta(minutes=horizon),design=design,context=ctx,event_history=events)
            records.append(record.model_dump(mode='json'))
    # Demonstrate unsupported and experimental modes without inferring unmetered status from missing meters.
    allfaces=pd.read_parquet('data/processed/pilot_block_faces.parquet',columns=['block_face_id'])
    unsupported=allfaces.loc[~allfaces.block_face_id.isin(set(design.block_face_id))].iloc[0,0]
    for mode in [False,True]: records.append(request_forecast(unsupported,issued,issued+pd.Timedelta(minutes=30),experimental_transfer=mode,design=design,context=ctx).model_dump(mode='json'))
    path=Path('reports/modeling/forecast_examples.jsonl');path.write_text(''.join(json.dumps(r)+'\n' for r in records),encoding='utf8')
    Path('schemas/ForecastArtifact.schema.json').write_text(json.dumps(ForecastArtifact.model_json_schema(),indent=2))
    return records
