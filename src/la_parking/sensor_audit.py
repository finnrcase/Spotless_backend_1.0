"""Source-semantic and label-selection audit; no cutoff is optimized on R2."""
import hashlib
import json
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from .http import utcnow
from .labels import interval_panel
from .temporal import intervals
from .evaluation import regression_metrics


def event_patterns(events,start,end,roster_ids):
    e=events[['space_id','observed_at_utc','state']].copy()
    duplicate_rows=int(e.duplicated().sum());e=e.drop_duplicates()
    conflict=e.groupby(['space_id','observed_at_utc']).state.transform('nunique').gt(1)
    conflict_rows=int(conflict.sum());e.loc[conflict,'state']='UNKNOWN'
    e=e.drop_duplicates(['space_id','observed_at_utc']).sort_values(['space_id','observed_at_utc'])
    previous=e.groupby('space_id').state.shift();gap=e.groupby('space_id').observed_at_utc.diff().dt.total_seconds()/60
    comparable=previous.isin(['VACANT','OCCUPIED'])&e.state.isin(['VACANT','OCCUPIED'])
    repeated=comparable&previous.eq(e.state);changed=comparable&previous.ne(e.state)
    local=e.observed_at_utc.dt.tz_convert('America/Los_Angeles')
    activity=pd.DataFrame({'space_id':e.space_id,'day':local.dt.strftime('%Y-%m-%d'),'hour':local.dt.hour,'state':e.state})
    daily=activity.groupby('day').agg(events=('space_id','size'),reporting_sensors=('space_id','nunique')).reset_index()
    dates=pd.date_range(start,end,freq='D',inclusive='left').strftime('%Y-%m-%d')
    days=pd.DataFrame({'day':dates}).merge(daily,on='day',how='left').fillna({'events':0,'reporting_sensors':0})
    roster_events=activity.loc[activity.space_id.isin(roster_ids)]
    reporting_sensor_days=roster_events[['space_id','day']].drop_duplicates().shape[0]
    def quantiles(mask):
        values=gap.loc[mask].dropna()
        return {str(q):float(values.quantile(q)) for q in [.1,.25,.5,.75,.9,.95,.99]} if len(values) else {}
    summary={'events':len(events),'sensors':int(e.space_id.nunique()),'exact_duplicate_rows':duplicate_rows,'conflicting_state_rows':conflict_rows,
        'states':e.state.value_counts().to_dict(),'successive_known_pairs':int(comparable.sum()),'same_state_pairs':int(repeated.sum()),
        'opposite_state_pairs':int(changed.sum()),'same_state_fraction':float(repeated.sum()/comparable.sum()) if comparable.any() else None,
        'all_pair_gap_minutes_quantiles':quantiles(comparable),'same_state_gap_minutes_quantiles':quantiles(repeated),
        'opposite_state_gap_minutes_quantiles':quantiles(changed),'gaps_over_3_hours':int(gap.gt(180).sum()),
        'gaps_over_24_hours':int(gap.gt(1440).sum()),'retrospective_roster_sensor_days_without_events':int(len(roster_ids)*len(dates)-reporting_sensor_days),
        'events_by_local_hour':activity.hour.value_counts().sort_index().to_dict(),
        'event_timestamp_first':e.observed_at_utc.min().isoformat(),'event_timestamp_last':e.observed_at_utc.max().isoformat(),
        'interpretation':'Opposite-state dominance supports change-driven reporting; same-state messages are reaffirmations, not proof of a periodic heartbeat. Silence can be stable occupancy, inactive hours, missing transmission or outage.'}
    return summary,days


def audit(output='reports/modeling/temporal_v2_audit'):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(Path('config/temporal_v2.json').read_text());mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet')
    mapping=mapping.loc[mapping.join_status.eq('matched')]
    legacy_files=['data/modeling/design.parquet','data/modeling/panel_intervals.parquet','artifacts/models/catalog.json','reports/modeling/results.json']
    protocol={'registered_at_utc':utcnow(),'config':cfg,'config_sha256':hashlib.sha256(Path('config/temporal_v2.json').read_bytes()).hexdigest(),
        'legacy_fingerprints':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in legacy_files},
        'fresh_holdout_evaluated':False,'new_holdout_outcomes_opened':False}
    pp=Path('reports/modeling/temporal_v2_protocol.json')
    if pp.exists():
        frozen=json.loads(pp.read_text())
        if frozen['config_sha256']!=protocol['config_sha256']:raise ValueError('Registered experiment configuration changed; create a separately named run')
    else:pp.write_text(json.dumps(protocol,indent=2),encoding='utf8')
    meta=json.loads(Path('data/staged/temporal_v2/history_metadata.json').read_text())
    current=json.loads(Path('data/staged/temporal_v2/occupancy_metadata.json').read_text())
    all_summary={};policy_rows=[];daily=[];conn=duckdb.connect()
    for month in ['2025_09','2026_08']:
        events=pd.read_parquet(f'data/processed/pilot_history_{month}.parquet')
        year,number=map(int,month.split('_'));start=pd.Timestamp(year=year,month=number,day=1,tz='America/Los_Angeles');end=start+pd.DateOffset(months=1);discovery=start+pd.DateOffset(days=7)
        roster_ids=set(events.loc[events.observed_at_utc<discovery,'space_id'])&set(mapping.space_id)
        summary,days=event_patterns(events,start,end,roster_ids);days['source_month']=month;daily.append(days)
        raw_info=json.loads(Path(f'data/staged/history_{month}.json').read_text());raw=raw_info['path']
        raw_counts=conn.execute('SELECT OccupancyState, count(*) n, count(distinct SpaceID) sensors FROM read_csv_auto(?) GROUP BY 1 ORDER BY 1',[raw]).fetchdf()
        summary['citywide_raw_states']=raw_counts.to_dict('records');summary['raw_archive_sha256']=raw_info['record']['sha256']
        frames={}
        for cap in cfg['audit_persistence_minutes']+[44640]:
            f,quality=interval_panel(events,mapping,discovery,end,15,cap,discovery)
            frames[cap]=f.set_index(['block_face_id','interval_start_utc'])
            iv=intervals(events.loc[events.space_id.isin(roster_ids)],cap,window_end=end)
            a=iv.observed_at_utc.clip(lower=start);b=iv.valid_to_utc.clip(upper=end)
            full_seconds=float(((b-a).dt.total_seconds().clip(lower=0)*iv.known).sum())
            policy='next_event_state_change_hypothesis' if cap==44640 else f'ttl_{cap}m'
            policy_rows.append({'month':month,'policy':policy,'cap_minutes':None if cap==44640 else cap,
                'post_discovery_sensor_time_fraction':quality['known_sensor_time_fraction'],
                'full_month_retrospective_roster_fraction':full_seconds/(len(roster_ids)*(end-start).total_seconds()),
                'rate_eligible_bins':int(f.coverage_fraction.ge(.25).sum()),'candidate_face_bins':len(f),
                'rate_eligible_fraction':float(f.coverage_fraction.ge(.25).mean()),'complete_panel_points':quality['complete_panel_points'],
                'conditional_rate_mean':float(f.loc[f.coverage_fraction.ge(.25),'occupancy_rate'].mean()),
                'independent_validity_established':False,'training_target_policy':cap==15,
                'uncertainty':'Long gaps remain unresolved; expanded state persistence is a hypothesis, not independently validated labels'})
        primary=frames[15];common=set(primary.index[primary.coverage_fraction.ge(.25)])
        for f in frames.values():common&=set(f.index[f.coverage_fraction.ge(.25)])
        common=sorted(common)
        for row in [r for r in policy_rows if r['month']==month]:
            cap=row['cap_minutes'] or 44640;f=frames[cap];selected=primary.coverage_fraction.ge(.25)&f.coverage_fraction.ge(.25)
            row.update(common_all_policy_bin_count=len(common),
                common_bin_label_MAE_vs_15m=float((f.loc[common,'occupancy_rate']-primary.loc[common,'occupancy_rate']).abs().mean()),
                primary_target_mean_on_selected_bins=float(primary.loc[selected,'occupancy_rate'].mean()),
                primary_target_mean_on_all_primary_supported_bins=float(primary.loc[primary.coverage_fraction.ge(.25),'occupancy_rate'].mean()))
        all_summary[month]=summary
    conn.close()
    report={'source_history_description':meta.get('description'),'source_current_description':current.get('description'),
        'timestamp_dictionary':{c['fieldName']:c.get('description') for c in current['columns'] if c.get('fieldName') in ['eventtime','occupancystate']},
        'official_heartbeat_interval_documented':False,'official_silence_equals_unoccupied':False,'official_delivery_latency_guarantee_documented':False,
        'available_archive_months':[a['filename'] for a in meta.get('metadata',{}).get('attachments',[])],
        'monthly_pilot_patterns':all_summary,'policies':policy_rows,'independent_field_observations':0,
        'findings':['The field is an occupancy transaction timestamp, not a documented reporting heartbeat.',
            'Every UNKNOWN or same-timestamp conflict terminates a known interval; no forward/back-fill through it.',
            'Long unchanged periods cannot be certified from sparse events alone. State-change semantics are plausible, but no policy is independently validated.',
            'Coverage depends on denominator: full-month retrospective roster and causal post-discovery roster are reported separately.',
            'Changing the cap changes the target and missingness population. Label disagreement and primary-target selection effects are reported; R2 is not used to choose a cap.',
            'All subsequent model-version comparisons retain identical v1 15-minute targets and frozen test identities.'],
        'sources':['https://data.lacity.org/api/views/cj8s-ivry.json','https://data.lacity.org/api/views/e7h6-4a3e.json','https://laexpresspark-wp.azurewebsites.net/technology/']}
    (out/'audit.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf8')
    pd.DataFrame(policy_rows).to_csv(out/'policy_coverage.csv',index=False);pd.concat(daily).to_csv(out/'reporting_by_day.csv',index=False)
    lines=['# Sensor label validity audit','','No persistence cutoff is selected by prediction scores. No independent observations currently certify the reconstructed intervals.','', '| Month | Policy | Post-discovery sensor-time | Full-month retrospective roster | Supported rate bins | Common-bin label MAE versus 15m |','|---|---|---:|---:|---:|---:|']
    for r in policy_rows:lines.append(f"| {r['month']} | {r['policy']} | {r['post_discovery_sensor_time_fraction']:.3%} | {r['full_month_retrospective_roster_fraction']:.3%} | {r['rate_eligible_bins']} | {r['common_bin_label_MAE_vs_15m']:.4f} |")
    lines+=['']+report['findings']+['','The unbounded next-event row is a diagnostic state-change hypothesis. It is not promoted to ground truth. Silent sensor-days are reporting gaps, not proof of outages or vacancy. Current mapping is later-vintage and event delivery time remains unverified.']
    (out/'audit.md').write_text('\n\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'patterns':{k:{a:v for a,v in s.items() if a in ['same_state_fraction','same_state_pairs','opposite_state_pairs','states','gaps_over_24_hours']} for k,s in all_summary.items()},'coverage':[{k:r[k] for k in ['month','policy','post_discovery_sensor_time_fraction','full_month_retrospective_roster_fraction']} for r in policy_rows]},indent=2))
    return report
