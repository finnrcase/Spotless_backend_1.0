"""Two-month bounded extension; new holdout outcomes are not requested/read."""
import json
from pathlib import Path
import duckdb
import pandas as pd
from .http import Store
from .connectors import download_month
from .build import normalize_events
from .temporal import parse_time
from .labels import interval_panel
from .temporal_features import history_grid


def acquire():
    cfg=json.loads(Path('config/temporal_v2.json').read_text());meta=json.loads(Path('data/staged/temporal_v2/history_metadata.json').read_text())
    out=Path('data/modeling/temporal_v2');out.mkdir(parents=True,exist_ok=True)
    report_path=Path('reports/modeling/temporal_v2_acquisition.json')
    report={'maximum_new_archives':cfg['maximum_new_archives'],'per_archive_mb_limit':cfg['maximum_archive_megabytes_each'],
        'holdout_reserved':cfg['new_archive_holdout'],'new_holdout_outcomes_opened':False,'months':{},'roster_comparisons':[]}
    if len(cfg['additional_archive_months'])>cfg['maximum_new_archives']:raise ValueError('Archive budget exceeded')
    store=Store();pilot=pd.read_parquet('data/processed/pilot_meters.parquet',columns=['spaceid'])
    mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet');connection=duckdb.connect();connection.register('pilot',pilot)
    for month in cfg['additional_archive_months']:
        # No later test-period data are downloaded as a side effect.
        if month>='2026_09':raise ValueError('Reserved later holdout must not enter development acquisition')
        path=out/f'events_{month}.parquet'
        try:
            raw,record=download_month(store,meta,month,cfg['maximum_archive_megabytes_each'])
            pointer=Path('data/staged/temporal_v2')/f'history_{month}.json'
            pointer.write_text(json.dumps({'path':str(raw),'record':record,'month':month},indent=2))
            if not path.exists():
                frame=connection.execute('SELECT * FROM read_csv_auto(?) WHERE SpaceID IN (SELECT spaceid FROM pilot)',[str(raw)]).fetchdf()
                local=parse_time(frame.EventTime_Local.astype(str),'America/Los_Angeles');utc=pd.to_datetime(frame.EventTime_UTC,utc=True)
                disagreement=(local-utc).dt.total_seconds().abs();bad=int((disagreement>1).sum())
                if bad:raise ValueError(f'{bad} local/UTC timestamp mismatches; audit before normalization')
                events,rejected,duplicates=normalize_events(frame,'ladot_archive_'+month,record['retrieved_at_utc'])
                if len(rejected):rejected.astype(str).to_parquet(out/f'event_rejects_{month}.parquet',index=False)
                events.to_parquet(path,index=False)
            else:
                events=pd.read_parquet(path);bad=0;duplicates=None;rejected=[]
            year,number=map(int,month.split('_'));start=pd.Timestamp(year=year,month=number,day=1,tz='America/Los_Angeles');end=start+pd.DateOffset(months=1);discovery=start+pd.DateOffset(days=7)
            panel,quality=interval_panel(events,mapping,discovery,end,15,15,discovery)
            panel['source_month']=month;panel['block_id']=panel.block_face_id.str.rsplit(':',n=1).str[0]
            panel.to_parquet(out/f'panel_{month}.parquet',index=False)
            history=history_grid(events,mapping,start,end,discovery);history['source_month']=month;history.to_parquet(out/f'history_{month}.parquet',index=False)
            report['months'][month]={'status':'acquired','bytes':record['bytes'],'sha256':record['sha256'],'retrieved_at_utc':record['retrieved_at_utc'],
                'pilot_events':len(events),'normalization_rejects':len(rejected),'duplicate_events':duplicates,'local_UTC_timestamp_mismatches':bad,'quality':quality,
                'historical_mapping':'Current October 2026 inventory only; historical location/relocation consistency unverified'}
            print('Acquired',month,record['bytes'],'bytes',len(events),'pilot events',quality['mapped_roster_sensors'],'roster sensors',flush=True)
        except Exception as exc:
            report['months'][month]={'status':'unavailable','reason':str(exc)};print(month,'unavailable',str(exc)[:250],flush=True)
        report_path.write_text(json.dumps(report,indent=2),encoding='utf8')
    connection.close()
    roster={}
    for month in ['2025_09','2026_06','2026_07','2026_08']:
        path=out/f'events_{month}.parquet'
        if not path.exists():path=Path(f'data/processed/pilot_history_{month}.parquet')
        if path.exists():roster[month]=set(pd.read_parquet(path,columns=['space_id']).space_id)
    ordered=sorted(roster)
    for a,b in zip(ordered,ordered[1:]):
        report['roster_comparisons'].append({'from_month':a,'to_month':b,'observed_ids_before':len(roster[a]),'observed_ids_after':len(roster[b]),
            'common_ids':len(roster[a]&roster[b]),'new_ids':sorted(roster[b]-roster[a]),'no_longer_reporting_ids':sorted(roster[a]-roster[b]),
            'interpretation':'Observed ID churn is not proof of relocation, decommissioning or sensor reliability. Counts describe reports, not curb supply.'})
    report_path.write_text(json.dumps(report,indent=2),encoding='utf8');return report
