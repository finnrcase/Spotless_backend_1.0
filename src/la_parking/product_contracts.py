"""Direct suitability and product outcomes; sensor panels cannot supply these labels."""
from datetime import datetime,timedelta,timezone
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,StrictBool,model_validator


class ProductRecord(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    @model_validator(mode='after')
    def normalize_utc(self):
        for name in type(self).model_fields:
            value=getattr(self,name)
            if isinstance(value,datetime):setattr(self,name,value.astimezone(timezone.utc))
        return self


class SuitabilityReview(ProductRecord):
    observation_id: str=Field(min_length=1)
    reviewed_by: str=Field(min_length=1)
    reviewed_at_utc: AwareDatetime
    counts_verified: StrictBool=False
    complete_face_visibility_verified: StrictBool=False
    location_verified: StrictBool=False
    full_stay_rules_verified: StrictBool=False
    posted_sign_coverage_verified: StrictBool=False
    official_rule_coverage_verified: StrictBool=False
    capacity_verified: StrictBool=False
    vehicle_class: str='standard_passenger'
    permit_class: str | None=None
    intended_duration_minutes: int=Field(gt=0,le=1440)
    rules_valid_from_utc: AwareDatetime
    rules_valid_to_utc: AwareDatetime
    eligibility_status: Literal['allowed','prohibited','unknown','conflict']='unknown'
    @model_validator(mode='after')
    def times(self):
        if self.rules_valid_to_utc<=self.rules_valid_from_utc:raise ValueError('Reversed rule verification window')
        return self


class ProductForecast(ProductRecord):
    prediction_id: str=Field(min_length=1)
    observation_id: str=Field(min_length=1)
    block_face_id: str=Field(min_length=1)
    issued_at_utc: AwareDatetime
    arrival_at_utc: AwareDatetime
    feature_available_at_utc: AwareDatetime
    training_cutoff_utc: AwareDatetime
    evidence_at_utc: AwareDatetime | None=None
    vehicle_class: str='standard_passenger'
    permit_class: str | None=None
    intended_duration_minutes: int=Field(gt=0,le=1440)
    model_version: str=Field(min_length=1)
    evidence_scope: Literal['direct_suitable_model','meter_panel_proxy','unsupported']='unsupported'
    probability_suitable: float | None=Field(default=None,ge=0,le=1)
    predicted_occupancy_rate: float | None=Field(default=None,ge=0,le=1)
    predicted_suitable_count: float | None=Field(default=None,ge=0)
    @model_validator(mode='after')
    def causality(self):
        if self.arrival_at_utc<self.issued_at_utc or self.feature_available_at_utc>self.issued_at_utc or self.training_cutoff_utc>self.issued_at_utc:raise ValueError('Forecast timestamp leakage')
        if self.evidence_at_utc and self.evidence_at_utc>self.issued_at_utc:raise ValueError('Future evidence')
        if self.evidence_scope!='direct_suitable_model' and (self.probability_suitable is not None or self.predicted_suitable_count is not None):raise ValueError('Meter-panel vacancy and unsupported forecasts cannot become suitable-space predictions')
        if self.evidence_scope=='unsupported' and self.predicted_occupancy_rate is not None:raise ValueError('Unsupported occupancy forecast must abstain')
        return self


class RankingCandidate(ProductRecord):
    block_face_id: str
    observation_id: str | None=None
    prediction_id: str | None=None
    walking_distance_m: float=Field(ge=0)
    price_per_hour: float | None=Field(default=None,ge=0)
    parking_type: Literal['metered','unmetered','unknown']='unknown'
    eligibility_status: Literal['allowed','prohibited','unknown','conflict']='unknown'
    eligibility_checked_at_utc: AwareDatetime | None=None
    rules_valid_from_utc: AwareDatetime | None=None
    rules_valid_to_utc: AwareDatetime | None=None
    official_rule_coverage_verified: StrictBool=False
    posted_sign_coverage_verified: StrictBool=False


class RankingDecision(ProductRecord):
    decision_id: str
    issued_at_utc: AwareDatetime
    arrival_at_utc: AwareDatetime
    intended_duration_minutes: int=Field(gt=0,le=1440)
    vehicle_class: str='standard_passenger'
    permit_class: str | None=None
    maximum_walking_distance_m: float=Field(gt=0)
    prefer_lower_price: bool=False
    maximum_price_per_hour: float | None=Field(default=None,ge=0)
    candidate_set_complete: StrictBool=False
    candidates: list[RankingCandidate]=Field(max_length=100)
    @model_validator(mode='after')
    def candidates_valid(self):
        if self.arrival_at_utc<self.issued_at_utc:raise ValueError('Ranking arrival precedes issue')
        if len({c.block_face_id for c in self.candidates})!=len(self.candidates):raise ValueError('Duplicate ranking faces')
        return self


class EvaluationManifest(ProductRecord):
    version: Literal['product-evaluation-v1']='product-evaluation-v1'
    data_kind: Literal['observed','synthetic_demo']='observed'
    phase: Literal['development','locked_test']='development'
    axis: Literal['future_time','unseen_block']
    train_ids: list[str]
    evaluation_ids: list[str]
    evaluation_start_utc: AwareDatetime
    evaluation_end_utc: AwareDatetime
    freeze_file: str | None=None
    @model_validator(mode='after')
    def disjoint(self):
        if self.evaluation_end_utc<=self.evaluation_start_utc:raise ValueError('Reversed evaluation period')
        if len(set(self.train_ids))!=len(self.train_ids) or len(set(self.evaluation_ids))!=len(self.evaluation_ids) or set(self.train_ids)&set(self.evaluation_ids):raise ValueError('Duplicate/overlapping evaluation IDs')
        if self.phase=='locked_test' and not self.freeze_file:raise ValueError('Locked tests require a prospective freeze file')
        return self


class PilotTrial(ProductRecord):
    trial_id: str=Field(min_length=1)
    data_kind: Literal['observed','synthetic_demo']='observed'
    assigned_arm: Literal['app','nearest_eligible']
    vehicle_class: str='standard_passenger'
    permit_class: str | None=None
    intended_duration_minutes: int=Field(default=60,gt=0,le=1440)
    received_recommendation_at_utc: AwareDatetime
    search_started_at_utc: AwareDatetime
    search_ended_at_utc: AwareDatetime | None=None
    parked_at_utc: AwareDatetime | None=None
    walk_started_at_utc: AwareDatetime | None=None
    destination_reached_at_utc: AwareDatetime | None=None
    arrival_success: StrictBool | None=None
    followed_assignment: StrictBool | None=None
    recommended_face_id: str | None=None
    reached_recommended_face_at_utc: AwareDatetime | None=None
    suitable_outcome_observation_id: str | None=None
    predicted_probability_suitable: float | None=Field(default=None,ge=0,le=1)
    probability_issued_at_utc: AwareDatetime | None=None
    probability_model_version: str | None=None
    probability_scope: Literal['direct_suitable_model','unsupported']='unsupported'
    abandoned: StrictBool=False
    verified: StrictBool=False
    reviewed_by: str | None=None
    reviewed_at_utc: AwareDatetime | None=None
    notes: str=Field(default='',max_length=2000)
    @model_validator(mode='after')
    def timeline(self):
        start=self.search_started_at_utc;end=self.search_ended_at_utc
        if start<self.received_recommendation_at_utc:raise ValueError('Search precedes assigned recommendation')
        if end and end<start:raise ValueError('Reversed search clock')
        if self.parked_at_utc and (not end or not start<=self.parked_at_utc<=end):raise ValueError('Parked time must be inside a finished search window')
        if self.abandoned and self.parked_at_utc:raise ValueError('Abandoned search cannot also be parked')
        if (self.walk_started_at_utc is None)!=(self.destination_reached_at_utc is None):raise ValueError('Walking duration needs both actual timestamps')
        if self.walk_started_at_utc and (not self.parked_at_utc or self.walk_started_at_utc<self.parked_at_utc or self.destination_reached_at_utc<self.walk_started_at_utc):raise ValueError('Invalid walking chronology')
        if self.reached_recommended_face_at_utc and self.reached_recommended_face_at_utc<start:raise ValueError('Recommended-face arrival precedes search')
        if self.arrival_success is not None and not self.reached_recommended_face_at_utc:raise ValueError('Arrival success needs actual recommended-face arrival time')
        if self.arrival_success is True and (not self.recommended_face_id or not self.parked_at_utc or self.parked_at_utc<self.reached_recommended_face_at_utc):raise ValueError('First-arrival success needs parking on the recorded recommended face after arrival')
        if self.predicted_probability_suitable is not None and (self.probability_scope!='direct_suitable_model' or not self.probability_model_version or not self.probability_issued_at_utc or self.probability_issued_at_utc>start):raise ValueError('Suitable probability requires a supported pre-search forecast')
        if self.verified and (not self.reviewed_by or not self.reviewed_at_utc or not end or self.reviewed_at_utc<end):raise ValueError('Reviewed trials need a reviewer and post-search review time')
        return self


PRODUCT_MODELS=[SuitabilityReview,ProductForecast,RankingCandidate,RankingDecision,EvaluationManifest,PilotTrial]
