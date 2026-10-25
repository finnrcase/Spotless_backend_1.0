"""Bounded supplemental source checks; cached successes, explicit failures."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from la_parking.http import Store,utcnow

OUT=Path('reports/starter');OUT.mkdir(parents=True,exist_ok=True)
store=Store(max_mb=4)
# Avoid long retry loops on optional program/document pages.
store.session.mount('https://',__import__('requests').adapters.HTTPAdapter(max_retries=0))


def document(url,budget=4_000_000):
    key=hashlib.sha256(('source_document:'+url).encode()).hexdigest();pointer=Path('data/cache')/(key+'.json')
    if pointer.exists():
        r=json.loads(pointer.read_text());p=Path('data')/r['path']
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']:return p,r
    rec={'url':url,'retrieved_at_utc':utcnow(),'purpose':'source_document_audit'}
    try:
        with store.session.get(url,stream=True,timeout=(12,35)) as response:
            rec.update(status=response.status_code,final_url=response.url,content_type=response.headers.get('Content-Type'))
            response.raise_for_status();chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>budget:raise ValueError('Document exceeds bounded request budget')
                chunks.append(chunk)
        body=b''.join(chunks);sha=hashlib.sha256(body).hexdigest();path=Path('data/raw')/sha
        if not path.exists():path.write_bytes(body)
        rec.update(success=True,path=str(path.relative_to('data')),sha256=sha,bytes=len(body))
        pointer.write_text(json.dumps(rec,indent=2));return path,rec
    except Exception as exc:rec.update(success=False,error=str(exc));raise
    finally:
        with Path('data/manifest.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(rec)+'\n')


checks=json.loads((OUT/'source_checks.json').read_text()) if (OUT/'source_checks.json').exists() else {}
def check(name,callback):
    try:
        value=callback();checks[name]={'status':'retrieved','checked_at_utc':utcnow(),**value};print(name,'retrieved',flush=True)
    except Exception as exc:checks[name]={'status':'unavailable','checked_at_utc':utcnow(),'error':str(exc)[:600]};print(name,'unavailable',str(exc)[:100],flush=True)
    (OUT/'source_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf8')


def api(url,params=None):
    o,r=store.json(url,params)
    return {'url':url,'request':r,'data':o}


def page(url):
    p,r=document(url);text=p.read_text(encoding='utf8',errors='replace')
    links=[urljoin(url,x) for x in re.findall(r'href=["\']([^"\']+)',text,re.I)]
    return {'url':url,'request':r,'candidate_links':[x for x in links if re.search(r'arcgis|curbiq|api|download|dataset|\.csv|\.json',x,re.I)],
        'plain_text_excerpt':re.sub('<[^>]+>',' ',text)[-22000:]}


if __name__=='__main__':
    base='https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer'
    check('naip_source_raster_info',lambda:api(base+'/17317/info',{'f':'json'}))
    check('naip_current_scene_identity',lambda:api(base+'/17317',{'f':'json'}))
    selection=json.loads(Path('data/reference/parking_data_starter/data/imagery_selection.json').read_text())
    check('included_export_extent_metadata',lambda:api(base+'/exportImage',{**selection['export_parameters'],'f':'json'}))
    check('code_the_curb_program',lambda:page('https://ladot.lacity.gov/codethecurb'))
    check('code_the_curb_arcgis_discovery',lambda:api('https://www.arcgis.com/sharing/rest/search',{'f':'json','q':'"Code the Curb"','num':20}))
    check('code_the_curb_socrata_discovery',lambda:api('https://api.us.socrata.com/api/catalog/v1',{'q':'Code the Curb','search_context':'data.lacity.org','limit':20}))
    check('parking_survey_socrata_discovery',lambda:api('https://api.us.socrata.com/api/catalog/v1',{'q':'parking survey','search_context':'data.lacity.org','limit':20}))
    check('permit_district_metadata',lambda:api('https://data.lacity.org/api/views/2ckn-xmjp.json'))
    check('street_sweeping_metadata',lambda:api('https://data.lacity.org/api/views/krk7-ayq2.json'))
    check('permit_policy',lambda:page('https://ladotparking.org/permits/ppd-permits/'))
    check('naip_rights',lambda:page('https://catalog.data.gov/dataset/national-agriculture-imagery-program-naip-imagery'))
    def survey():
        url='https://planning.lacity.gov/odocument/23ddbbd5-632b-4b58-a3d0-29846fcc3c84/Fehr_%26_Peers_Parking_Utilization_and_Transpor.pdf'
        p,r=document(url,budget=20_000_000)
        return {'url':url,'request':r,'pdf_header_verified':p.read_bytes().startswith(b'%PDF')}
    check('venice_parking_survey',survey)
    check('census2020_block_service',lambda:api('https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/tigerWMS_Census2020/MapServer',{'f':'json'}))
