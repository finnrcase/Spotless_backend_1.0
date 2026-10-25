from datetime import datetime,timezone
from typing import Literal,Any
from pydantic import BaseModel,ConfigDict,Field,AwareDatetime,model_validator


class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Location(Contract):
    latitude: float=Field(ge=-90,le=90)
    longitude: float=Field(ge=-180,le=180)
    label: str | None=Field(default=None,max_length=160)


class EligibilityProfile(Contract):
    permit_class: str | None=Field(default=None,max_length=100)
    vehicle_class: Literal['standard_passenger','accessible','commercial','motorcycle','other']='standard_passenger'


class PredictionRequest(Contract):
    destination: Location
    arrival_time: AwareDatetime
    intended_stay_minutes: int=Field(default=60,ge=1,le=1440)
    maximum_walking_distance_m: int=Field(default=400,ge=25,le=2000)
    eligibility: EligibilityProfile=Field(default_factory=EligibilityProfile)
    maximum_price_per_hour: float | None=Field(default=None,ge=0,le=100)
    prefer_lower_price: bool=False
    include_experimental: bool=False
    mode: Literal['live','historical_replay']='live'
    replay_issue_time: AwareDatetime | None=None

    @model_validator(mode='after')
    def mode_consistency(self):
        if self.mode=='live' and self.replay_issue_time is not None:raise ValueError('Replay time only applies to historical replay')
        if self.mode=='historical_replay' and self.replay_issue_time is None:raise ValueError('Historical replay requires an explicit issue time')
        if self.replay_issue_time and self.arrival_time<self.replay_issue_time:raise ValueError('Arrival precedes replay issue time')
        self.arrival_time=self.arrival_time.astimezone(timezone.utc)
        if self.replay_issue_time:self.replay_issue_time=self.replay_issue_time.astimezone(timezone.utc)
        return self


class RestrictionRecord(Contract):
    restriction_id: str
    block_face_id: str
    rule_type: Literal['no_parking','permit','vehicle_only','max_duration','allow']
    effective_from: AwareDatetime
    effective_to: AwareDatetime
    available_at: AwareDatetime
    source_kind: Literal['official','posted_sign_review']
    source_url: str | None=None
    raw_text: str
    verification: Literal['verified','needs_review']='needs_review'
    verified_at: AwareDatetime | None=None
    expires_at: AwareDatetime | None=None
    allowed_permits: list[str]=Field(default_factory=list)
    allowed_vehicles: list[str]=Field(default_factory=list)
    maximum_stay_minutes: int | None=Field(default=None,ge=1)
    weekdays: list[int] | None=None
    local_start: str | None=None
    local_end: str | None=None

    @model_validator(mode='after')
    def valid_rule(self):
        if self.effective_to<=self.effective_from:raise ValueError('Rule effective interval is reversed')
        if self.verification=='verified' and self.verified_at is None:raise ValueError('Verified rule requires a verification timestamp')
        if self.weekdays is not None and any(d not in range(7) for d in self.weekdays):raise ValueError('Weekday must be 0–6')
        if (self.local_start is None)!=(self.local_end is None):raise ValueError('Recurring rule requires both local boundaries')
        if self.local_start:
            for value in [self.local_start,self.local_end]:
                try:datetime.strptime(value,'%H:%M')
                except ValueError:raise ValueError('Local schedule times must use HH:MM')
        return self


class RuleCoverage(Contract):
    block_face_id: str
    effective_from: AwareDatetime
    effective_to: AwareDatetime
    available_at: AwareDatetime
    source_kind: Literal['official','posted_sign_review']
    complete: bool=False
    verified_at: AwareDatetime
    expires_at: AwareDatetime
    notes: str=''

    @model_validator(mode='after')
    def valid_coverage(self):
        if self.effective_to<=self.effective_from:raise ValueError('Coverage effective interval is reversed')
        if self.expires_at<=self.verified_at:raise ValueError('Coverage expiry must follow verification')
        return self


class EligibilityResult(Contract):
    status: Literal['unknown','allowed','prohibited','conflict']
    reason: str
    checked_from: AwareDatetime
    checked_to: AwareDatetime
    official_coverage_complete: bool=False
    posted_sign_coverage_complete: bool=False
    restrictions: list[dict]=Field(default_factory=list)
    upcoming: list[dict]=Field(default_factory=list)


class PanelEstimate(Contract):
    occupancy_rate: float | None=Field(default=None,ge=0,le=1)
    expected_vacant_count: float | None=Field(default=None,ge=0)
    probability_any_panel_vacant: float | None=Field(default=None,ge=0,le=1)
    panel_sensor_count: int | None=Field(default=None,ge=1)
    count_range: list[float] | None=None
    net_change_15m: float | None=None
    net_change_30m: float | None=None
    net_change_60m: float | None=None
    modeled_horizon_minutes: int | None=None
    interpretation: str='Experimental metered sensor-panel proxy; not full-curb eligible parking'

    @model_validator(mode='after')
    def bounds(self):
        if self.expected_vacant_count is not None and (self.panel_sensor_count is None or self.expected_vacant_count>self.panel_sensor_count):raise ValueError('Panel count exceeds its known panel size')
        if self.count_range is not None:
            if len(self.count_range)!=2 or not 0<=self.count_range[0]<=self.count_range[1] or self.panel_sensor_count is None or self.count_range[1]>self.panel_sensor_count:raise ValueError('Invalid panel count interval')
        return self


class BlockForecast(Contract):
    block_face_id: str
    street_name: str
    geometry: dict
    geometry_method: str
    straight_line_distance_m: float=Field(ge=0)
    walking_distance_m: float | None=Field(default=None,ge=0)
    walking_distance_method: str='centerline_network_estimate; pedestrian crossings/accessibility unverified'
    rank: int | None=None
    rank_reason: str
    visual_status: Literal['observed_recent','model_estimate','experimental_extrapolation','insufficient_data','known_restriction']
    eligibility: EligibilityResult
    expected_available_eligible_spaces: float | None=Field(default=None,ge=0)
    probability_at_least_one_suitable: float | None=Field(default=None,ge=0,le=1)
    availability_changes: dict[str,float | None]=Field(default_factory=lambda:{'15m':None,'30m':None,'60m':None})
    panel_estimate: PanelEstimate | None=None
    experimental_activity_rank: float | None=Field(default=None,ge=0,le=1)
    evidence: dict
    uncertainty: dict
    price: dict
    unavailable_reason: str | None=None


class PredictionResponse(Contract):
    request: PredictionRequest
    forecast_issued_at: AwareDatetime
    computed_at: AwareDatetime
    response_at: AwareDatetime
    arrival_time: AwareDatetime
    intended_stay_end: AwareDatetime
    model_version: str
    cache_hit: bool
    cache_key: str
    data_revision: str
    mode_label: str
    blocks: list[BlockForecast]
    coverage: dict
    refresh: dict
    limitations: list[str]


class ObservationBatch(Contract):
    records: list[dict]=Field(min_length=1,max_length=500)


class RefreshResponse(Contract):
    checked_at: AwareDatetime
    changed: bool
    data_revision: str
    cache_entries_cleared: int
    source_poll_performed: bool=False
    message: str
