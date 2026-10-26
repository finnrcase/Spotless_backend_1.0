import json
import os
from pathlib import Path
import pandas as pd
from .sources import SODA


def verify_ids(expected, features, oid):
    got = [f['properties'][oid] for f in features]
    if len(got) != len(set(got)) or set(got) != set(expected):
        raise ValueError(f'Incomplete/duplicate ArcGIS IDs: expected {len(expected)}, got {len(got)}')


def arcgis(store, layer, *, bbox=None, where='1=1', max_features=100000, batch=500,out_fields='*',query_by_ids=False):
    meta, _ = store.json(layer, {'f':'json'})
    oid = meta.get('objectIdField') or next(f['name'] for f in meta['fields'] if f['type']=='esriFieldTypeOID')
    query = {'f':'json', 'where':where}
    if bbox:
        query.update(geometry=','.join(map(str,bbox)), geometryType='esriGeometryEnvelope', inSR=4326, spatialRel='esriSpatialRelIntersects')
    ids, _ = store.json(layer+'/query', {**query, 'returnIdsOnly':'true'})
    expected = sorted(ids.get('objectIds') or [])
    if len(expected) > max_features:
        raise ValueError(f'{len(expected)} features exceeds budget {max_features}')
    print(f'ArcGIS {meta.get("name")}: estimated {len(expected)} features; {batch}/batch', flush=True)
    features=[]
    for start in range(0, len(expected), min(batch, meta.get('maxRecordCount',batch))):
        chunk=expected[start:start+min(batch,meta.get('maxRecordCount',batch))]
        # Short range predicates avoid IIS URL-length 404s from long objectIds lists.
        # Retain spatial filter for sparse pilot IDs and reconcile the exact set.
        selector={'objectIds':','.join(map(str,chunk))} if query_by_ids else {'where':f'({where}) AND {oid} >= {chunk[0]} AND {oid} <= {chunk[-1]}'}
        obj,_=store.json(layer+'/query', {**query, 'f':'geojson', **selector, 'outFields':out_fields, 'outSR':4326, 'returnGeometry':'true', 'resultRecordCount':len(chunk)})
        if obj.get('exceededTransferLimit'):
            raise ValueError('ArcGIS transfer limit; reduce batch size')
        verify_ids(chunk,obj['features'],oid)
        features.extend(obj['features'])
    verify_ids(expected,features,oid)
    return {'type':'FeatureCollection','features':features}, meta, oid


def socrata(store, ident, *, where=None, max_rows=60000, page_size=5000,anonymous=True):
    headers = {'X-App-Token':os.environ['SOCRATA_APP_TOKEN']} if not anonymous and os.getenv('SOCRATA_APP_TOKEN') else {}
    base = f'{SODA}/resource/{ident}.json'
    filt = {'$where':where} if where else {}
    count,_=store.json(base,{**filt,'$select':'count(*)'},headers=headers)
    n=int(count[0]['count'])
    print(f'Socrata {ident}: {n} rows expected',flush=True)
    if n>max_rows: raise ValueError(f'{n} rows exceeds budget {max_rows}; narrow filter')
    rows=[]
    for offset in range(0,n,page_size):
        page,_=store.json(base,{**filt,'$order':':id','$limit':page_size,'$offset':offset},headers=headers)
        if len(page)!=min(page_size,n-offset): raise ValueError('Socrata pagination count changed; refresh a consistent snapshot')
        rows.extend(page)
    after,_=store.json(base,{**filt,'$select':'count(*)'},headers=headers)
    if int(after[0]['count'])!=n: raise ValueError('Source changed during paging')
    # Live mutable feeds cannot guarantee transaction isolation; report this limitation.
    return pd.DataFrame(rows)


def history_attachments(meta):
    return sorted(meta.get('metadata',{}).get('attachments',[]), key=lambda a:a['filename'])


def download_month(store, meta, month, max_mb=450):
    candidates=[a for a in history_attachments(meta) if month in a['filename']]
    if len(candidates)!=1: raise ValueError('Month absent or ambiguous in verified attachment metadata')
    a=candidates[0]
    url=f"{SODA}/api/views/cj8s-ivry/files/{a['assetId']}"
    # HEAD is only an estimate. Streaming byte ceiling also enforced by Store.
    h=store.session.head(url,params={'download':'true'},allow_redirects=True,timeout=30)
    print(f"History {month}: advertised {h.headers.get('Content-Length','unknown')} bytes; hard budget {max_mb} MB",flush=True)
    return store.get(url,{'download':'true','filename':a['filename']},max_mb=max_mb)


def parcel_on_demand(store, layer, bbox, max_features=2000):
    """No citywide parcel export: cached, caller-bounded spatial request."""
    if not bbox or len(bbox)!=4: raise ValueError('Explicit small parcel bounding box required')
    if (bbox[2]-bbox[0])*(bbox[3]-bbox[1]) > .0025: raise ValueError('Parcel request area too large')
    return arcgis(store,layer,bbox=bbox,max_features=max_features)


def census_acs(store, year=2024):
    from .environment import load_local_env
    load_local_env()
    params={'get':'NAME,B01003_001E,B25001_001E,B08201_002E,B08301_001E,B11001_001E', 'for':'tract:*','in':'state:06 county:037'}
    # Cache/manifests include only public parameters; raw bodies still preserved.
    secret={'key':os.environ['CENSUS_API_KEY']} if os.getenv('CENSUS_API_KEY') else None
    obj,_=store.json(f'https://api.census.gov/data/{year}/acs/acs5',params,secret_params=secret)
    return pd.DataFrame(obj[1:],columns=obj[0])
