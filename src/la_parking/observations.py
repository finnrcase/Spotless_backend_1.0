"""Offline manual field-survey intake. No photos, plates, or personal identity needed."""
import json
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from .contracts import ManualObservation
from .spatial import METRIC_CRS


def ingest(path, inventory_path='data/processed/pilot_block_faces.parquet', output='data/observations'):
    faces=gpd.read_parquet(inventory_path).to_crs(METRIC_CRS).set_index('block_face_id')
    target=Path(output); target.mkdir(parents=True,exist_ok=True)
    accepted=[]; rejected=[]
    previous=target/'manual_observations.parquet'
    old=pd.read_parquet(previous) if previous.exists() else pd.DataFrame()
    seen=set(old.observation_id) if len(old) else set()
    for number,line in enumerate(Path(path).read_text(encoding='utf8').splitlines(),1):
        try:
            r=ManualObservation.model_validate_json(line)
            if r.observation_id in seen: raise ValueError('Duplicate observation ID')
            if r.block_face_id not in faces.index: raise ValueError('Unknown block-face ID')
            if r.gps_accuracy_m is not None and r.gps_accuracy_m>30: raise ValueError('GPS accuracy exceeds 30 m; review required')
            pt=gpd.GeoSeries([Point(r.longitude,r.latitude)],crs=4326).to_crs(METRIC_CRS).iloc[0]
            if pt.distance(faces.loc[r.block_face_id].geometry)>max(40,2*(r.gps_accuracy_m or 0)): raise ValueError('Observation is far from declared face')
            if (r.survey_end_utc-r.survey_start_utc).total_seconds()>900: raise ValueError('Survey exceeds 15-minute snapshot window')
            record=r.model_dump(mode='json'); record['field_provenance']=json.dumps(record['field_provenance'])
            record['location_review_required']=r.location_method=='confirmed_map_pin'
            record['label_review_required']=not (r.rules_checked and r.complete_face and r.capacity_basis=='marked_spaces')
            accepted.append(record); seen.add(r.observation_id)
        except Exception as exc: rejected.append({'line':number,'reason':str(exc)})
    if accepted:
        pd.concat([old,pd.DataFrame(accepted)],ignore_index=True).to_parquet(previous,index=False)
    (target/'last_intake_report.json').write_text(json.dumps({'accepted':len(accepted),'rejected':rejected},indent=2),encoding='utf8')
    return {'accepted':len(accepted),'rejected':rejected}
