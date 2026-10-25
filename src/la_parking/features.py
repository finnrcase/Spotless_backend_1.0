"""Inspection features, never occupancy labels; availability/vintage explicit."""
import json
from pathlib import Path
import pandas as pd
import geopandas as gpd
from .spatial import METRIC_CRS, read_features
from .http import utcnow
from .temporal import parse_time


def build_context():
    stage=Path('data/staged'); out=Path('data/processed'); now=utcnow()
    segs=gpd.read_parquet(out/'pilot_street_segments.parquet').to_crs(METRIC_CRS)
    buffers=segs[['segment_id','geometry']].copy(); buffers.geometry=buffers.buffer(100)
    records=[]; quality={}
    for name in ['driveways','hydrants','buildings','regulatory_signs']:
        path=out/f'pilot_{name}.parquet'
        if not path.exists(): continue
        layer=gpd.read_parquet(path).to_crs(METRIC_CRS)
        valid=layer.geometry.notna()&~layer.is_empty&layer.is_valid
        matched=gpd.sjoin(buffers,layer.loc[valid,['geometry']],how='left',predicate='intersects')
        count=matched.groupby('segment_id').index_right.count()
        for entity,n in count.items(): records.append({'entity_id':entity,'feature_name':f'{name}_within_100m','value':float(n),'field_provenance':'derived','feature_kind':'static','source_id':name,'available_at_utc':pd.Timestamp(now),'valid_from_utc':pd.Timestamp(now),'valid_to_utc':pd.NaT,'historical_validity':'unverified','confidence':.4})
        quality[name]={'rows':len(layer),'valid_rows':int(valid.sum()),'unique_matched_source_rows':int(matched.index_right.nunique()),'unmatched_segment_buffers':int((count==0).sum())}
    if records: pd.DataFrame(records).to_parquet(out/'static_features.parquet',index=False)

    path=stage/'weather_forecast.json'
    if path.exists():
        obj=json.loads(path.read_text()); props=obj['properties']; frame=pd.DataFrame(props['periods'])
        f=pd.DataFrame({'entity_id':'nws:ucla-grid','feature_name':'forecast_temperature','value':frame.temperature,
                        'units':frame.temperatureUnit,'valid_from_utc':pd.to_datetime(frame.startTime,utc=True),
                        'valid_to_utc':pd.to_datetime(frame.endTime,utc=True),'issued_at_utc':pd.Timestamp(props['generatedAt']),
                        'available_at_utc':pd.Timestamp(now),'source_id':'nws_forecast','field_provenance':'observed','feature_kind':'dynamic'})
        f.to_parquet(out/'dynamic_features.parquet',index=False)
    path=stage/'ucla_2026_27.ics'
    events=[]; unparsed=[]
    if path.exists():
        # Verified input uses all-day DTSTART, DURATION:P1D. Quarantine other forms.
        text=path.read_text(encoding='utf8').replace('\n ','').replace('\n\t','')
        for block in text.split('BEGIN:VEVENT')[1:]:
            fields={line.split(':',1)[0]:line.split(':',1)[1] for line in block.split('END:VEVENT')[0].splitlines() if ':' in line}
            try:
                if 'DTSTART;VALUE=DATE' not in fields or fields.get('DURATION')!='P1D' or 'RRULE' in fields: raise ValueError('Unsupported recurrence/time format')
                start=pd.Timestamp(fields['DTSTART;VALUE=DATE']).tz_localize('America/Los_Angeles')
                end=start+pd.DateOffset(days=1)  # A local day may be 23 or 25 hours.
                events.append({'event_id':fields['UID'],'venue_id':'ucla_campus','event_type':'academic_calendar','summary':fields.get('SUMMARY'),
                               'valid_from_utc':start.tz_convert('UTC'),'valid_to_utc':end.tz_convert('UTC'),
                               'announced_at_utc':pd.to_datetime(fields.get('DTSTAMP'),utc=True),'available_at_utc':pd.Timestamp(now),
                               'source_id':'ucla_calendar','source_version':fields.get('SEQUENCE'),'field_provenance':'observed',
                               'attendance_estimate':pd.NA,'confidence':.8})
            except Exception as exc: unparsed.append({'uid':fields.get('UID'),'error':str(exc)})
        pd.DataFrame(events).to_parquet(out/'events.parquet',index=False)
    quality['ucla_calendar']={'normalized':len(events),'unparsed':unparsed}
    # LODES remains at observed source geography, not distributed over streets by fiat.
    for name in ['lodes_la_wac_2023','lax_weather_2025','metro_rail_stops','metro_rail_calendar']:
        p=stage/f'{name}.parquet'
        if p.exists(): pd.read_parquet(p).to_parquet(out/f'{name}.parquet',index=False)
    Path('reports/feature_quality.json').write_text(json.dumps(quality,indent=2),encoding='utf8')
    return quality
