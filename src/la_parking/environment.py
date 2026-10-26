"""Load explicitly allowed local credentials without executing shell syntax."""
import os
from pathlib import Path


def load_local_env(path='.env',keys=('CENSUS_API_KEY',)):
    allowed=set(keys);found={};p=Path(path)
    if p.exists():
        for line in p.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if line.startswith('export '):line=line[7:].lstrip()
            name,sep,value=line.partition('=');name=name.strip()
            if not sep or name not in allowed:continue
            value=value.strip()
            if value.startswith(('"',"'")):
                quote=value[0];end=value.find(quote,1)
                if end<0:raise ValueError('Unclosed quoted credential in local environment file')
                value=value[1:end]
            else:value=value.split(' #',1)[0].strip()
            if value:found[name]=value
    result={}
    for name in allowed:
        if os.environ.get(name):result[name]={'loaded':True,'source':'process_environment'}
        elif found.get(name):os.environ[name]=found[name];result[name]={'loaded':True,'source':'local_env'}
        else:result[name]={'loaded':False,'source':'missing'}
    return result
