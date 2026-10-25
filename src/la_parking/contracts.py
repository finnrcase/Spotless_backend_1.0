"""Version 1 record contracts. Export JSON Schema using `la-parking schemas`."""
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, model_validator


class Provenance(str, Enum):
    observed='observed'
    derived='derived'
    assumed='assumed'
    imputed='imputed'
    unavailable='unavailable'


class Record(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version: Literal['1.0']='1.0'
    source_id: str
    source_record_id: str
    source_version: str
    retrieved_at_utc: AwareDatetime
    field_provenance: dict[str,Provenance]
    confidence: float=Field(ge=0,le=1)

    @model_validator(mode='after')
    def normalize_utc(self):
        for name in type(self).model_fields:
            value=getattr(self,name)
            if isinstance(value,datetime):
                setattr(self,name,value.astimezone(timezone.utc))
        return self


class EffectiveRecord(Record):
    valid_from_utc: AwareDatetime
    valid_to_utc: AwareDatetime | None=None
    @model_validator(mode='after')
    def effective_order(self):
        if self.valid_to_utc and self.valid_to_utc<=self.valid_from_utc: raise ValueError('Effective end must follow start')
        return self


class StreetSegment(Record):
    segment_id: str
    geometry_wkt: str
    crs: Literal['EPSG:4326']='EPSG:4326'
    jurisdiction: Literal['City of Los Angeles']='City of Los Angeles'
    applicability: Literal['candidate','excluded','needs_review']
    exclusion_reason: str | None=None


class BlockFace(Record):
    block_face_id: str
    segment_id: str
    side: Literal['left','right']
    geometry_wkt: str
    geometry_method: Literal['authoritative_curb','approximate_centerline_offset']
    orientation: Literal['canonical_endpoint_order']='canonical_endpoint_order'
    curb_source_ids: list[str]=[]


class CurbInventory(EffectiveRecord):
    block_face_id: str
    physical_capacity: int | None=Field(default=None,ge=0)
    eligible_capacity: int | None=Field(default=None,ge=0)
    capacity_lower: int | None=Field(default=None,ge=0)
    capacity_upper: int | None=Field(default=None,ge=0)
    capacity_method: Literal['field_survey','marked_spaces','exclusion_adjusted_estimate','unavailable']
    exclusions_complete: bool
    restriction_ids: list[str]=[]
    @model_validator(mode='after')
    def capacities(self):
        if self.physical_capacity is not None and self.eligible_capacity is not None and self.eligible_capacity>self.physical_capacity: raise ValueError('Eligible exceeds physical capacity')
        if self.capacity_lower is not None and self.capacity_upper is not None and self.capacity_lower>self.capacity_upper: raise ValueError('Reversed capacity interval')
        if self.capacity_method=='unavailable' and any(v is not None for v in [self.physical_capacity,self.eligible_capacity,self.capacity_lower,self.capacity_upper]): raise ValueError('Unavailable capacity must be null')
        return self


class Restriction(EffectiveRecord):
    restriction_id: str
    block_face_id: str
    rule_type: Literal['no_parking','sweeping','permit','loading','time_limit','meter_hours','closure','other']
    raw_rule_text: str
    local_timezone: Literal['America/Los_Angeles']='America/Los_Angeles'
    schedule: dict
    permit_eligibility: list[str]=[]
    interpretation_status: Literal['verified','needs_review','unparsed']


class OccupancyObservation(Record):
    observation_id: str
    space_id: str | None=None
    block_face_id: str | None=None
    observed_at_utc: AwareDatetime
    state: Literal['OCCUPIED','VACANT','UNKNOWN','NO_OBSERVATION']
    evidence_type: Literal['sensor','manual','survey','partner']
    available_spaces: int | None=Field(default=None,ge=0)
    stale: bool
    @model_validator(mode='after')
    def missing_is_not_zero(self):
        if self.state in ['UNKNOWN','NO_OBSERVATION'] and self.available_spaces is not None: raise ValueError('Unknown is not a space count')
        if self.observed_at_utc>self.retrieved_at_utc: raise ValueError('Observation cannot be in the future')
        return self


class Coverage(EffectiveRecord):
    entity_id: str
    expected_seconds: float=Field(gt=0)
    observed_seconds: float=Field(ge=0)
    unknown_seconds: float=Field(ge=0)
    max_gap_seconds: float=Field(ge=0)
    @model_validator(mode='after')
    def bounded(self):
        if self.observed_seconds+self.unknown_seconds>self.expected_seconds: raise ValueError('Coverage exceeds requested window')
        return self


class Feature(EffectiveRecord):
    entity_id: str
    feature_name: str
    feature_kind: Literal['static','dynamic']
    value: float | str | None
    available_at_utc: AwareDatetime
    @model_validator(mode='after')
    def missingness(self):
        if self.value is None and self.field_provenance.get('value')!=Provenance.unavailable: raise ValueError('Null feature must be marked unavailable')
        return self


class Event(EffectiveRecord):
    event_id: str
    venue_id: str
    event_type: str
    announced_at_utc: AwareDatetime
    latitude: float=Field(ge=-90,le=90)
    longitude: float=Field(ge=-180,le=180)
    attendance_estimate: int | None=Field(default=None,ge=0)
    status: Literal['scheduled','cancelled','postponed','completed','unknown']


class ManualObservation(Record):
    observation_id: str
    block_face_id: str
    observer_pseudonym: str
    survey_session_id: str | None=Field(default=None,max_length=120)
    assignment_id: str | None=Field(default=None,max_length=120)
    survey_start_utc: AwareDatetime
    survey_end_utc: AwareDatetime
    occupied: int | None=Field(default=None,ge=0)
    vacant_legal: int | None=Field(default=None,ge=0)
    unsuitable: int | None=Field(default=None,ge=0)
    surveyed_capacity: int | None=Field(default=None,ge=0)
    complete_face: bool
    permit_class: str | None=None
    location_method: Literal['gps','confirmed_map_pin']='gps'
    gps_accuracy_m: float | None=Field(default=None,ge=0)
    parking_type: Literal['metered','unmetered','mixed','unknown']='unknown'
    rules_checked: bool=False
    intended_duration_minutes: int | None=Field(default=None,gt=0)
    vehicle_class: str='standard_passenger'
    capacity_basis: Literal['marked_spaces','estimated_positions','unknown']='unknown'
    sampling_stratum: str | None=None
    sampling_method: Literal['randomized','repeat_visit','convenience','unspecified']='unspecified'
    sampling_probability: float | None=Field(default=None,gt=0,le=1)
    observer_confidence: float | None=Field(default=None,ge=0,le=1)
    restrictions_text: str=''
    curb_usable_length_m: float | None=Field(default=None,ge=0)
    measurement_method: str | None=None
    gap_lengths_m: list[float] | None=None
    obstructed_curb_length_m: float | None=Field(default=None,ge=0,allow_inf_nan=False)
    counting_convention: str | None=Field(default=None,max_length=500)
    exclusions_text: str=Field(default='',max_length=2000)
    latitude: float=Field(ge=-90,le=90)
    longitude: float=Field(ge=-180,le=180)
    notes: str=''
    @model_validator(mode='after')
    def survey(self):
        import math
        if self.gap_lengths_m is not None and any(not math.isfinite(v) or v<=0 for v in self.gap_lengths_m):raise ValueError('Gap lengths must be positive finite metres; [] means checked and none, null means unmeasured')
        if self.location_method=='gps' and self.gps_accuracy_m is None: raise ValueError('GPS accuracy required for a GPS fix')
        if self.location_method=='confirmed_map_pin' and self.gps_accuracy_m is not None: raise ValueError('A map pin has no measured GPS accuracy')
        if self.survey_end_utc<self.survey_start_utc: raise ValueError('Survey end precedes start')
        if self.survey_end_utc>self.retrieved_at_utc: raise ValueError('Survey cannot be in future')
        if self.complete_face:
            vals=[self.occupied,self.vacant_legal,self.unsuitable,self.surveyed_capacity]
            if any(v is None for v in vals) or sum(vals[:3])!=vals[3]: raise ValueError('Complete-face counts must reconcile')
        return self


class Forecast(Record):
    forecast_id: str
    block_face_id: str
    issued_at_utc: AwareDatetime
    arrival_at_utc: AwareDatetime
    duration_minutes: int=Field(gt=0)
    permit_class: str | None=None
    probability_suitable_space: float | None=Field(default=None,ge=0,le=1)
    expected_available: float | None=Field(default=None,ge=0)
    lower: float | None=Field(default=None,ge=0)
    upper: float | None=Field(default=None,ge=0)
    model_version: str
    support: Literal['validated','experimental','unsupported']
    @model_validator(mode='after')
    def support_check(self):
        if self.arrival_at_utc<self.issued_at_utc: raise ValueError('Arrival precedes forecast issue')
        if self.lower is not None and self.upper is not None and self.lower>self.upper: raise ValueError('Reversed forecast bounds')
        if self.support=='unsupported' and any(x is not None for x in [self.probability_suitable_space,self.expected_available,self.lower,self.upper]): raise ValueError('Unsupported forecast must abstain')
        return self


MODELS=[StreetSegment,BlockFace,CurbInventory,Restriction,OccupancyObservation,Coverage,Feature,Event,ManualObservation,Forecast]
