"""Safe credential verification: no response body or credential in reports."""
import json
import os
from pathlib import Path
from .environment import load_local_env
from .http import Store, utcnow


def verify(store=None,env_path='.env',output='reports/modeling/census_v4_auth.json'):
    status=load_local_env(env_path)['CENSUS_API_KEY']
    report={'checked_at_utc':utcnow(),'credential':status,'request_attempted':False,'authenticated_request_succeeded':False}
    store=store or Store(refresh=True,max_mb=1)
    if status['loaded']:
        report['request_attempted']=True
        try:
            obj,rec=store.json('https://api.census.gov/data/2023/acs/acs5',
                {'get':'NAME,B25001_001E,B25001_001M,B08201_001E,B08201_001M,B08201_002E,B08201_002M','for':'tract:261200','in':'state:06 county:037'},
                secret_params={'key':os.environ['CENSUS_API_KEY']})
            if not isinstance(obj,list) or len(obj)!=2 or not isinstance(obj[0],list) or len(obj[1])!=len(obj[0]):raise ValueError('Unexpected Census response shape')
            report.update(authenticated_request_succeeded=True,status='verified',http_status=rec['status'],data_rows=1,year=2023,response_sha256=rec['sha256'])
        except Exception:
            rec=store.last_record or {};url=rec.get('final_url','')
            report.update(status='authentication_failed' if rec.get('status') in [400,401,403] or 'invalid_key' in url or 'missing_key' in url else 'request_failed',
                http_status=rec.get('status'),reason='Census did not return the expected authenticated JSON data; credential value withheld.')
    else:report['status']='credential_not_loaded'
    if output:Path(output).write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    return report
