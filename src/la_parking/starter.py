"""Audit/import the supplied bounded pilot; never execute its download script."""
import hashlib
import json
from pathlib import Path
import zipfile
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from .http import utcnow
from .spatial import read_features,METRIC_CRS

BBOX=(-118.456,34.050,-118.435,34.075)
REQUIRED=['README.md','PILOT_RESULTS.md','SOURCES.md','FIELD_COLLECTION.md','manifest.json']


def resolve_package(path):
    path=Path(path)
    if path.suffix.lower()=='.zip':
        destination=Path('data/reference').resolve()
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                target=(destination/member.filename).resolve()
                if not target.is_relative_to(destination) or member.file_size>30_000_000:raise ValueError('Unsafe/oversized starter archive member')
                if member.is_dir():continue
                content=archive.read(member)
                if target.exists():
                    if target.read_bytes()!=content:raise ValueError(f'Refusing to overwrite different existing starter file: {target}')
                else:
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
        path=destination/'parking_data_starter'
    if not (path/'manifest.json').exists() and (path/'parking_data_starter/manifest.json').exists():path=path/'parking_data_starter'
    if any(not (path/name).exists() for name in REQUIRED):raise ValueError('Starter README/results/sources/collection/manifest files not found')
    return path


def verify_layer(package,name):
    data=package/'data';meta=json.loads((data/f'{name}_metadata.json').read_text())
    oid=meta.get('objectIdField') or next(f['name'] for f in meta['fields'] if f['type']=='esriFieldTypeOID')
    expected=json.loads((data/f'{name}_ids.json').read_text())['objectIds']
    count=json.loads((data/f'{name}_count.json').read_text())['count']
    complete=read_features(data/f'{name}_pilot_complete.geojson')
    pages=[];page_sizes=[]
    for path in sorted(data.glob(f'{name}_page_*.geojson')):
        page=json.loads(path.read_text())
        if page.get('exceededTransferLimit'):raise ValueError(f'{name}: truncated source page')
        page_sizes.append(len(page['features']));pages.extend(page['features'])
    page_ids=[f['properties'][oid] for f in pages]
    if len(expected)!=len(set(expected)) or count!=len(expected):raise ValueError(f'{name}: independent count/ID list mismatch')
    for label,ids in [('combined',complete[oid].tolist()),('pages',page_ids)]:
        if len(ids)!=len(set(ids)) or set(ids)!=set(expected):raise ValueError(f'{name}: incomplete/duplicate {label} IDs')
    objects={f['properties'][oid]:f for f in json.loads((data/f'{name}_pilot_complete.geojson').read_text())['features']}
    if any(f!=objects[f['properties'][oid]] for f in pages):raise ValueError(f'{name}: combined extraction differs from pages')
    bounds=complete.total_bounds
    if not (-119<bounds[0]<=bounds[2]<-117 and 33<bounds[1]<=bounds[3]<35):raise ValueError(f'{name}: implausible coordinates/CRS')
    if complete.geometry.isna().any() or complete.geometry.is_empty.any():raise ValueError(f'{name}: null/empty geometry')
    exact=complete.intersects(box(*BBOX))
    metric_bbox=gpd.GeoSeries([box(*BBOX)],crs=4326).to_crs(METRIC_CRS).iloc[0]
    max_distance=float(complete.loc[~exact].to_crs(METRIC_CRS).distance(metric_bbox).max()) if (~exact).any() else 0.
    if max_distance>500:raise ValueError(f'{name}: substantial query-extent mismatch')
    details={'features':len(complete),'unique_object_ids':int(complete[oid].nunique()),'source_count':count,
        'page_count':len(page_sizes),'page_sizes':page_sizes,'all_ids_reconciled':True,'coordinates_plausible':True,
        'invalid_geometries_quarantined':int((~complete.is_valid).sum()),'bounds_wgs84':bounds.tolist(),
        'outside_exact_requested_bbox':int((~exact).sum()),'max_outside_distance_m':max_distance,
        'bbox_note':'Provider returned some near-boundary candidates outside the exact WGS84 box; retained with an explicit mask. A projected query envelope is a possible cause, not verified.',
        'schema_fields':meta['fields'],'source_units':meta.get('geometryProperties',{}).get('units'),
        'source_crs':meta.get('extent',{}).get('spatialReference'),'export_crs':'EPSG:4326',
        'source_imagery_year':2014,'inventory_created_year':2017,'current_maintenance_verified':False,
        'interpretation':'Historic physical asset prior; never a parking-stall count or current restriction inventory'}
    complete['geometry_valid']=complete.is_valid
    complete['intersects_exact_requested_bbox']=exact
    complete['source_imagery_year']=2014;complete['inventory_created_year']=2017
    complete['parking_capacity']=None;complete['current_legal_status']='unknown'
    complete['evidence_class']='historic_supply_prior'
    return complete,details


def integrate(path='data/reference/parking_data_starter',output='reports/starter'):
    package=resolve_package(path);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    original=json.loads((package/'manifest.json').read_text());verified=[];records=[]
    root=Path('data').resolve();manifest=root/'manifest.jsonl'
    old=[json.loads(line) for line in manifest.read_text().splitlines()] if manifest.exists() else []
    seen={(r.get('source_file'),r.get('sha256')) for r in old if r.get('acquisition_method')=='starter_package_import'}
    for entry in original:
        if not entry.get('success'):raise ValueError(f'Failed packaged request requires inspection: {entry.get("file")}')
        source=(package/'data'/entry['file']).resolve()
        if not source.is_relative_to((package/'data').resolve()):raise ValueError('Unsafe package manifest path')
        content=source.read_bytes();sha=hashlib.sha256(content).hexdigest()
        if sha!=entry['sha256'] or len(content)!=entry['bytes']:raise ValueError(f'Package hash/length mismatch: {entry["file"]}')
        verified.append(entry['file'])
        if (str(source),sha) not in seen:
            try:relative=str(source.relative_to(root))
            except ValueError:
                target=root/'raw'/sha
                if target.exists() and target.read_bytes()!=content:raise ValueError('Corrupt existing immutable snapshot')
                if not target.exists():target.write_bytes(content)
                relative=str(target.relative_to(root))
            records.append({**entry,'path':relative,'source_file':str(source),'acquisition_method':'starter_package_import','imported_at_utc':utcnow()})
    # Verify every source before appending any acquisition records or staging data.
    layers={name:verify_layer(package,name) for name in ['curbs','driveways']}
    with manifest.open('a',encoding='utf8') as stream:
        for record in records:stream.write(json.dumps(record)+'\n')
    staging=Path('data/staged/starter');staging.mkdir(parents=True,exist_ok=True)
    summary={'package_path':str(package.resolve()),'package_manifest_sha256':hashlib.sha256((package/'manifest.json').read_bytes()).hexdigest(),
        'files_hash_verified':len(verified),'new_acquisition_manifest_records':len(records),'downloads_rerun':0,'layers':{},
        'metered_and_unmetered_core_targets':True,'new_occupancy_labels':0,'processed_existing_tables_overwritten':False}
    times={entry['file']:entry['retrieved_at_utc'] for entry in original}
    links=[]
    faces_path=Path('data/processed/pilot_block_faces.parquet')
    faces=gpd.read_parquet(faces_path).to_crs(METRIC_CRS) if faces_path.exists() else None
    for name,(frame,details) in layers.items():
        # Combined files are derived; retain original page retrieval range.
        dates=[v for k,v in times.items() if k.startswith(name+'_page_')]
        frame['retrieved_at_utc']=max(dates);details['retrieval_range_utc']=[min(dates),max(dates)]
        frame.to_parquet(staging/f'{name}.parquet',index=False)
        existing=Path(f'data/processed/pilot_{name}.parquet')
        if existing.exists():
            ids=set(pd.read_parquet(existing,columns=['OBJECTID']).OBJECTID)
            details['object_ids_already_in_existing_pilot']=int(frame.OBJECTID.isin(ids).sum())
            details['new_object_ids_vs_existing_pilot']=int((~frame.OBJECTID.isin(ids)).sum())
        if faces is not None:
            valid=frame.loc[frame.geometry_valid,['OBJECTID','geometry']].to_crs(METRIC_CRS)
            joined=gpd.sjoin_nearest(valid,faces[['block_face_id','geometry']],max_distance=20,distance_col='distance_m')
            if len(joined):
                joined['asset_kind']=name;joined['relation']='historic_asset_near_face_not_legal_capacity'
                joined['ambiguous_multiple_faces']=joined.groupby('OBJECTID').OBJECTID.transform('size')>1
                links.append(pd.DataFrame(joined.drop(columns=['geometry','index_right'])))
        summary['layers'][name]=details
    if links:pd.concat(links,ignore_index=True).to_parquet(staging/'asset_face_links.parquet',index=False)
    for name in ['street_segments','block_faces']:
        fpath=Path('data/processed')/(name+'.parquet')
        if fpath.exists():
            key='segment_id' if name=='street_segments' else 'block_face_id';f=pd.read_parquet(fpath,columns=[key])
            if f[key].isna().any() or f[key].duplicated().any():raise ValueError('Existing citywide ID foundation failed validation')
            summary[name]={'rows':len(f),'unique_ids':int(f[key].nunique()),'source':'Preserved existing City inventory'}
    (out/'quality.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf8')
    lines=['# Starter integration audit','',f"Verified {len(verified)} packaged response hashes; no source downloads rerun.",'', '| Asset layer | Complete features | Pages | Already in larger pilot | Invalid geometries | Outside exact box |','|---|---:|---:|---:|---:|---:|']
    for name,d in summary['layers'].items():lines.append(f"| {name} | {d['features']} | {d['page_count']} | {d.get('object_ids_already_in_existing_pilot','unknown')} | {d['invalid_geometries_quarantined']} | {d['outside_exact_requested_bbox']} |")
    lines+=['','Independent source ID lists, counts, page contents and combined exports reconcile. Capped sample files are not used as complete data. Near-boundary assets outside the exact requested box are retained with a mask; a projected-envelope query is a possible cause, not established.','', 'Curb and driveway polygons are historic physical assets: 2017 inventory based on 2014 imagery. Metadata edits and retrieval dates do not refresh geometry. Invalid geometry is retained and excluded from spatial links. Parking capacity and current legal status remain unknown.','', 'Existing citywide streets, block faces, model artifacts and larger pilot tables were preserved. Asset-to-face links are uncertain physical associations, not eligibility labels. Full schemas, coordinate bounds and provenance are in quality.json.']
    (out/'quality.md').write_text('\n'.join(lines)+'\n',encoding='utf8');return summary
