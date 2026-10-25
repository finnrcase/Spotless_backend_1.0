"""Conservative state intervals; a sensitivity policy, not a validated sensor SLA."""
import pandas as pd


def parse_time(values, basis):
    if basis=='UTC': return pd.to_datetime(values,format='mixed',errors='coerce',utc=True)
    if basis!='America/Los_Angeles': raise ValueError('Explicit timestamp basis required')
    # Ambiguous autumn and nonexistent spring wall times are quarantined, never guessed.
    return pd.to_datetime(values,format='mixed',errors='coerce').dt.tz_localize(basis,ambiguous='NaT',nonexistent='NaT').dt.tz_convert('UTC')


def intervals(events, horizon_minutes=15, window_end=None):
    if horizon_minutes<=0: raise ValueError('Positive freshness horizon required')
    frame=events[['space_id','observed_at_utc','state']].drop_duplicates().copy()
    # Conflicting states at one timestamp provide no reliable label.
    conflicts=frame.groupby(['space_id','observed_at_utc'])['state'].transform('nunique')>1
    frame.loc[conflicts,'state']='UNKNOWN'
    frame=frame.drop_duplicates().sort_values(['space_id','observed_at_utc'])
    next_time=frame.groupby('space_id')['observed_at_utc'].shift(-1)
    cap=frame['observed_at_utc']+pd.Timedelta(minutes=horizon_minutes)
    frame['valid_to_utc']=pd.concat([next_time,cap],axis=1).min(axis=1)
    if window_end is not None:
        end=pd.Timestamp(window_end)
        if end.tzinfo is None: raise ValueError('Window end must be timezone-aware')
        frame['valid_to_utc']=frame.valid_to_utc.clip(upper=end)
    frame['known']=frame.state.isin(['OCCUPIED','VACANT'])
    frame['seconds']=(frame.valid_to_utc-frame.observed_at_utc).dt.total_seconds()
    return frame
