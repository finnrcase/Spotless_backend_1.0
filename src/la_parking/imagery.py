"""Bounded historic-imagery annotation and evaluation, separate from forecasting."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image
from shapely.geometry import box,Polygon,Point
from shapely.ops import unary_union
from .http import Store
from .spatial import METRIC_CRS,canonical_line

NAIP='https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer'
VEHICLES={'curbside_vehicle_candidate','traffic_lane_vehicle','uncertain_vehicle'}
MASKS={'visible_curb','tree_occluded','shadow_occluded','other_occluded'}


def select_blocks(streets,context,source_extent,n=12):
    f=streets.to_crs(METRIC_CRS).copy();f['length_m']=f.length
    f=f.loc[f.length_m.between(55,240)&~f.street_designation.str.contains('Private|Freeway|Ramp|Walkway|Paper',case=False,na=False)]
    f=f.loc[f.geometry.centroid.map(lambda p:source_extent.covers(p.buffer(190)))]
    f=f.merge(context[['segment_id','business_300']].drop_duplicates('segment_id'),on='segment_id',how='left')
    f['business_300']=f.business_300.fillna(0)
    # These are activity/context strata, not verified land use or parking type.
    f['stratum']=pd.qcut(f.business_300.rank(method='first'),4,labels=['low_activity_prior','lower_mid_activity_prior','upper_mid_activity_prior','high_activity_prior']).astype(str)
    selected=[];points=[]
    included=Point(-118.4485,34.0655)
    anchor=gpd.GeoSeries([included],crs=4326).to_crs(METRIC_CRS).iloc[0]
    anchor_index=f.geometry.centroid.distance(anchor).idxmin();selected.append(anchor_index);points.append(f.loc[anchor_index].geometry.centroid)
    for stratum in sorted(f.stratum.unique()):
        choices=f.loc[f.stratum==stratum]
        desired=n//4
        already=sum(f.loc[i].stratum==stratum for i in selected)
        for _ in range(desired-already):
            available=choices.loc[~choices.index.isin(selected)]
            if available.empty:break
            distances=available.geometry.centroid.map(lambda p:min(p.distance(q) for q in points))
            i=distances.idxmax();selected.append(i);points.append(f.loc[i].geometry.centroid)
    if len(selected)!=n:raise ValueError('Not enough distinct physical blocks for bounded imagery design')
    return f.loc[selected].to_crs(METRIC_CRS)


def source_metadata(checks):
    info=checks['naip_source_raster_info']['data'];scene=checks['naip_current_scene_identity']['data']['attributes']
    if scene['Name']!='m_3411861_nw_11_060_20220511' or scene['Category']!=1:raise ValueError('Pinned raster identity changed; do not substitute a mosaic')
    if info['extent']['spatialReference']['wkid']!=26911 or info['pixelSizeX']!=.6 or info['pixelSizeY']!=.6:raise ValueError('Unexpected local native raster metadata')
    e=info['extent'];extent=box(e['xmin'],e['ymin'],e['xmax'],e['ymax'])
    return info,scene,extent


def prepare(download=False,output='reports/imagery'):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);assets=Path('data/staged/starter/imagery');assets.mkdir(parents=True,exist_ok=True)
    checks=json.loads(Path('reports/starter/source_checks.json').read_text());info,scene,extent=source_metadata(checks)
    streets=gpd.read_parquet('data/processed/pilot_street_segments.parquet')
    context=pd.read_parquet('data/modeling/current_context.parquet')
    blocks=select_blocks(streets,context,extent)
    store=Store(max_mb=2);tasks=[];tiles=[]
    inventory=gpd.read_parquet('data/processed/pilot_block_faces.parquet').set_index('block_face_id')
    for j,seg in enumerate(blocks.itertuples()):
        center=seg.geometry.interpolate(.5,normalized=True);tile_id=f'naip-17317-{hashlib.sha256(seg.segment_id.encode()).hexdigest()[:10]}'
        image_path=assets/(tile_id+'.jpg');metadata_path=assets/(tile_id+'.json')
        params={'f':'json','bbox':','.join(str(x) for x in [center.x-180,center.y-180,center.x+180,center.y+180]),
            'bboxSR':26911,'imageSR':26911,'size':'600,600','format':'jpg',
            'mosaicRule':json.dumps({'mosaicMethod':'esriMosaicLockRaster','lockRasterIds':[17317]})}
        if not metadata_path.exists() or not image_path.exists():
            if not download:raise ValueError('Bounded imagery missing; rerun with explicit download=True (12 small tiles maximum)')
            export,record=store.json(NAIP+'/exportImage',params)
            raw,image_record=store.get(export['href'],max_mb=2)
            with Image.open(raw) as image:
                if image.size!=(600,600):raise ValueError('Unexpected export dimensions')
                image.verify()
            shutil.copyfile(raw,image_path)
            tile={'tile_id':tile_id,'path':str(image_path),'sha256':image_record['sha256'],'width':600,'height':600,'extent':export['extent'],
                'native_pixel_size_m':[info['pixelSizeX'],info['pixelSizeY']],'source_scene_id':17317,'source_scene_name':scene['Name'],
                'capture_date':'2022-05-11','capture_time_utc':None,'capture_time_precision':'date_only','time_specific_occupancy_truth':False,
                'retrieved_at_utc':image_record['retrieved_at_utc'],'export_request_sha256':record['sha256'],
                'rights_source':'https://catalog.data.gov/dataset/national-agriculture-imagery-program-naip-imagery','rights':'Public domain NAIP; no commercial imagery used'}
            metadata_path.write_text(json.dumps(tile,indent=2))
        tile=json.loads(metadata_path.read_text())
        if hashlib.sha256(image_path.read_bytes()).hexdigest()!=tile['sha256']:raise ValueError('Cached tile hash mismatch')
        e=tile['extent'];w=tile['width'];h=tile['height']
        project=lambda x,y:[(x-e['xmin'])/(e['xmax']-e['xmin'])*w,(e['ymax']-y)/(e['ymax']-e['ymin'])*h]
        tile_bounds=box(e['xmin'],e['ymin'],e['xmax'],e['ymax'])
        for side,offset in [('left',8),('right',-8)]:
            fid=seg.segment_id+':'+side
            if fid not in inventory.index:raise ValueError('Task has no stable inventory face')
            line=canonical_line(seg.geometry).offset_curve(offset)
            region=line.buffer(4,cap_style='flat').intersection(tile_bounds)
            polygons=[region] if region.geom_type=='Polygon' else list(region.geoms)
            corridor=[[project(x,y) for x,y in p.exterior.coords] for p in polygons if p.geom_type=='Polygon']
            tasks.append({'task_id':f'pilot-face-{j:02d}-{side}','block_face_id':fid,'block_id':seg.segment_id,'street_name':seg.street_name,
                'side':side,'context_stratum':seg.stratum,'business_count_prior':int(seg.business_300),'parking_type':'unverified',
                'image':tile,'corridor':corridor,'corridor_method':'approximate centerline offset ±8 m, buffered ±4 m; alignment needs review',
                'annotations_status':'awaiting_independent_human_review','legal_eligibility':'unknown','capacity':None})
        tiles.append(tile)
    # Include the provided photograph separately so its inferred registration is visible.
    original=Path('data/reference/parking_data_starter/data/westwood_naip_test.jpg')
    supplied={'tile_id':'included-naip-17317','path':str(original),'sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
        'width':500,'height':560,'extent':checks['included_export_extent_metadata']['data']['extent'],
        'extent_method':'Inferred from repeat export metadata for identical parameters; original JPEG has no world file',
        'capture_date':'2022-05-11','capture_time_precision':'date_only','native_pixel_size_m':[.6,.6]}
    manifest={'version':'imagery-feasibility-v1','tasks':tasks,'tiles':tiles,'included_image':supplied,
        'detector_runtime':{name:bool(importlib.util.find_spec(name)) for name in ['torch','ultralytics','onnxruntime']},
        'detector_configured':False,'reference_annotations_reviewed':0,'count_mae':None,'detection_precision':None,'detection_recall':None,
        'status':'annotation_workflow_ready_detection_blocked','blocker':'No configured overhead-vehicle detector, weights or compatible runtime; no independently reviewed annotations. No detections fabricated.',
        'scope':'24 faces, 12 physical blocks, 12 bounded 360 m tiles; historic visible-vehicle feasibility only, not legal vacancy or time-specific forecasting'}
    (out/'tasks.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    payload=json.loads(json.dumps(manifest))
    for tile in payload['tiles']+[payload['included_image']]:tile['data_uri']='data:image/jpeg;base64,'+base64.b64encode(Path(tile['path']).read_bytes()).decode()
    # Reuse one image per physical block in the embedded payload.
    template=Path('web/imagery');html=(template/'index.html').read_text(encoding='utf8')
    for key,value in {'/*__DATA__*/':json.dumps(payload,separators=(',',':')).replace('<','\\u003c'),
        '/*__STYLE__*/':(template/'style.css').read_text(),
        '/*__MODEL__*/':(template/'model.mjs').read_text().replace('export ',''),
        '/*__APP__*/':(template/'app.js').read_text()}.items():html=html.replace(key,value)
    (out/'annotator.html').write_text(html,encoding='utf8')
    report=['# Historic imagery feasibility','',manifest['scope'],'',f"Status: **{manifest['status']}**.",'',manifest['blocker'],'',
        'Native resolution is confirmed from raster 17317/info: pixelSizeX=0.6, pixelSizeY=0.6, NAD83 / UTM 11N (metres). The service-wide 0.3 value is not used. The source is a four-band primary raster named m_3411861_nw_11_060_20220511. Capture metadata is date-only; midnight is not a flight time.','',
        'The supplied 500×560 JPEG was inspected and retained. Its actual repeat-export extent differs from the requested box because the server adjusted aspect ratio. That registration remains an inference for the original JPEG. New 600×600 exports save the returned projected extent; rendering at 0.6 m does not improve source information.','',
        'Open annotator.html for real images, approximate curb overlays, explicit visible/occluded masks, traffic-lane/curbside/uncertain vehicle boxes, local saving and JSON export/import. No unannotated area is marked visible or empty. Single-image curbside position cannot prove a vehicle is parked or legally eligible.','',
        'Count MAE, precision and recall are unavailable. Run imagery-evaluate after independent human review and actual detector predictions. Evaluation is limited to reviewed visible curb area, excludes occlusion, and never turns these old images into arrival-time or legally suitable-space labels. The included failure-example overlay is explicitly an unverified visual review.']
    (out/'feasibility.md').write_text('\n'.join(report)+'\n',encoding='utf8')
    return manifest


def evaluate_annotations(manifest,annotations,predictions=None):
    tasks={t['task_id']:t for t in manifest['tasks']};rows=[];tp=fp=fn=0;reviewed=eligible=0
    ids=[r.get('task_id') for r in annotations]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate reference task IDs')
    if predictions is not None:
        ids=[r.get('task_id') for r in predictions]
        if len(ids)!=len(set(ids)) or not set(ids).issubset(tasks):raise ValueError('Duplicate or unknown prediction task IDs')
    for record in annotations:
        task=tasks.get(record.get('task_id'))
        if task is None or record.get('image_sha256')!=task['image']['sha256']:raise ValueError('Unknown task or image hash mismatch')
        width,height=task['image']['width'],task['image']['height']
        shapes=record.get('shapes',[])
        for s in shapes:
            if s.get('confidence') is not None and (not np.isfinite(s['confidence']) or not 0<=s['confidence']<=1):raise ValueError('Invalid annotation confidence')
            if s.get('class') not in VEHICLES|MASKS:raise ValueError('Unknown annotation class')
            if s['class'] in VEHICLES:
                x,y,w,h=s['box']
                if not all(np.isfinite([x,y,w,h])) or x<0 or y<0 or w<=0 or h<=0 or x+w>width or y+h>height:raise ValueError('Invalid vehicle box')
            else:
                if len(s['points'])<3 or any(not (0<=x<=width and 0<=y<=height) for x,y in s['points']):raise ValueError('Invalid area mask coordinates')
                if not Polygon(s['points']).is_valid:raise ValueError('Invalid area mask polygon')
        if record.get('reviewed_by_human') is not True or record.get('annotation_complete') is not True or not record.get('annotator','').strip():continue
        reviewed+=1
        visible=unary_union([Polygon(s['points']) for s in shapes if s['class']=='visible_curb'])
        occluded=unary_union([Polygon(s['points']) for s in shapes if s['class'] in MASKS-{'visible_curb'}])
        visible=visible.difference(occluded)
        if visible.is_empty:continue
        eligible+=1
        refs=[s['box'] for s in shapes if s['class']=='curbside_vehicle_candidate' and visible.covers(box(*_corners(s['box'])).centroid)]
        if predictions is None:continue
        matched=[p for p in predictions if p.get('task_id')==record['task_id']]
        if len(matched)!=1:raise ValueError('Exactly one actual prediction record per reviewed task required')
        prediction=matched[0]
        if prediction.get('image_sha256')!=task['image']['sha256'] or not prediction.get('detector_id'):raise ValueError('Prediction provenance missing/mismatched')
        guesses=[]
        for b in prediction['boxes']:
            x,y,w,h=b
            if not all(np.isfinite(b)) or min(x,y)<0 or min(w,h)<=0 or x+w>width or y+h>height:raise ValueError('Invalid prediction box')
            if visible.covers(box(*_corners(b)).centroid):guesses.append(b)
        pairs=[]
        for i,a in enumerate(refs):
            for j,b in enumerate(guesses):
                aa,bb=box(*_corners(a)),box(*_corners(b));iou=aa.intersection(bb).area/aa.union(bb).area
                if iou>=.5:pairs.append((iou,i,j))
        used_r=set();used_p=set()
        for _,i,j in sorted(pairs,reverse=True):
            if i not in used_r and j not in used_p:used_r.add(i);used_p.add(j)
        tp+=len(used_r);fp+=len(guesses)-len(used_p);fn+=len(refs)-len(used_r)
        rows.append({'task_id':record['task_id'],'reference_visible_candidates':len(refs),'predicted_visible_candidates':len(guesses),
            'absolute_count_error':abs(len(refs)-len(guesses)),'visible_fraction_of_image':visible.area/(width*height)})
    return {'status':'evaluated_historic_visible_candidates' if rows else 'unavailable_no_reviewed_reference_prediction_pairs',
        'evaluation_target':'Historical visible curbside vehicle candidates; not legal vacancy, full-curb occupancy or time-specific truth',
        'total_tasks':len(tasks),'human_reviewed_complete_tasks':reviewed,'eligible_visible_reference_faces':eligible,
        'prediction_coverage_among_eligible_reviewed_faces':len(rows)/eligible if eligible else None,
        'paired_faces':len(rows),'count_mae':float(np.mean([r['absolute_count_error'] for r in rows])) if rows else None,
        'true_positives':tp if rows else None,'false_positives':fp if rows else None,'false_negatives':fn if rows else None,
        'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,'iou_threshold':.5,'rows':rows}


def _corners(b):return [b[0],b[1],b[0]+b[2],b[1]+b[3]]


def evaluate_files(annotations_path,predictions_path=None,output='reports/imagery/evaluation.json'):
    manifest=json.loads(Path('reports/imagery/tasks.json').read_text());annotations=json.loads(Path(annotations_path).read_text())
    predictions=json.loads(Path(predictions_path).read_text()) if predictions_path else None
    result=evaluate_annotations(manifest,annotations,predictions);Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text(json.dumps(result,indent=2),encoding='utf8');return result
