"""A bounded 16-face development design, never a replacement for frozen holds."""
import hashlib,html,json
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
from .field_route import local_slot,cross_streets
from .spatial import METRIC_CRS


def plan(output='reports/collection',seed=452):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);streets=gpd.read_parquet('data/processed/pilot_street_segments.parquet').to_crs(METRIC_CRS)
    faces=gpd.read_parquet('data/processed/pilot_block_faces.parquet');mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet');held=set()
    for file in ['config/field_holdouts.json','config/coverage_v4_field_holdouts.json']:
        cfg=json.loads(Path(file).read_text());held.update(cfg['unseen_physical_blocks']);held.update(cfg.get('known_future_physical_blocks',[]))
    f=streets.loc[~streets.segment_id.isin(held)&streets.length.between(55,190)&~streets.street_designation.str.contains('Private|Freeway|Ramp|Walkway|Paper|Outside',case=False,na=False)].copy()
    counts=mapping.loc[mapping.join_status.eq('matched')].groupby('segment_id').size();f['meter_linked']=f.segment_id.map(counts).fillna(0).gt(0)
    confidence=faces.groupby('segment_id').confidence.mean();f['evidence_gap_priority']=1.5-f.segment_id.map(confidence).fillna(0)
    rng=np.random.default_rng(seed);chosen=[];selections=[]
    for linked in [False,True]:
        pool=f.loc[f.meter_linked.eq(linked)].sort_values('segment_id').copy();original=len(pool)
        if original<4:raise ValueError('Need at least four development blocks per meter-link stratum')
        for draw in range(4):
            probability=.75/len(pool)+.25*pool.evidence_gap_priority/pool.evidence_gap_priority.sum();index=int(rng.choice(len(pool),p=probability.to_numpy()));r=pool.iloc[index]
            chosen.append(r.segment_id);selections.append({'block_id':r.segment_id,'meter_linked_prior':bool(linked),'draw':draw+1,'stratum_candidates':original,'remaining_candidates':len(pool),
                'conditional_draw_probability':float(probability.iloc[index]),'marginal_inclusion_probability':None,'evidence_gap_priority':float(r.evidence_gap_priority)})
            pool=pool.drop(pool.index[index])
    slots=[(day,hour) for day in ['2026-11-01','2026-11-02','2026-11-03'] for hour in [8,12,17]][:8];assignments=[];route=[]
    for index,(bid,(day,hour)) in enumerate(zip(chosen,slots)):
        seg=streets.loc[streets.segment_id.eq(bid)].iloc[0];selected=faces.loc[faces.segment_id.eq(bid)].to_crs(4326)
        for face in selected.itertuples():
            p=face.geometry.representative_point();entry={'block_face_id':face.block_face_id,'block_id':bid,'street_name':seg.street_name,'side':face.side,'longitude':p.x,'latitude':p.y,
                'location_is_reference_pin_not_capture_geotag':True,'cross_streets':cross_streets(seg.geometry,seg.street_name,streets),'parking_type':'metered_or_mixed_candidate' if selections[index]['meter_linked_prior'] else 'unmetered_candidate_verify',
                'selection':selections[index],'evaluation_role':'development_only'};route.append(entry)
            for delta in [0,15,30,60]:
                minute=delta+(0 if face.side=='left' else 4);time=local_slot(day,hour)+pd.Timedelta(minutes=minute);session=f'collection-v1-{index:02d}-{day}'
                assignments.append({**entry,'assignment_id':f'{session}-{face.side}-{delta}','survey_session_id':session,'repeat_offset_minutes':delta,'planned_local':time.isoformat(),'planned_utc':time.tz_convert('UTC').isoformat(),'visit_status':'planned_not_observed'})
    result={'version':'collection-development-v1','seed':seed,'physical_blocks':8,'faces':16,'planned_snapshots':64,'observed_snapshots':0,'protected_blocks_excluded':sorted(held),
        'sampling':'Within two inventory meter-link strata: 75% uniform plus 25% evidence-gap weighted sequential draws without replacement; logged probabilities are conditional draws, not marginal inclusion weights.',
        'uncertainty_target':'Historic geometry confidence only; no held-out outcomes or forecast errors used. Missing rules and absent meters do not establish legal supply/type.',
        'workload':'One physical block per approximately 65-minute session, both faces four minutes apart; travel/review time must be logged. Choose this bounded plan rather than assuming all earlier routes can also be completed.',
        'representativeness':'Probability selection within a constrained short-block Westwood frame; purposive dates. Not a representative LA sample.', 'faces_detail':route,'assignments':assignments}
    (out/'development_plan.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');pd.DataFrame(assignments).to_csv(out/'development_assignments.csv',index=False)
    rows=[]
    from urllib.parse import urlencode
    for a in sorted(assignments,key=lambda r:r['planned_utc']):
        link='../collector.html#'+urlencode({'face':a['block_face_id'],'session':a['survey_session_id'],'assignment':a['assignment_id'],'planned':a['planned_local'],'repeat':a['repeat_offset_minutes']})
        rows.append(f'<li><a href="{html.escape(link,quote=True)}">{html.escape(a["planned_local"])} · {html.escape(a["street_name"])} · {a["side"]} · {a["repeat_offset_minutes"]} min</a></li>')
    page='<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Westwood development collection</title><style>body{font:16px/1.5 system-ui;max-width:850px;margin:auto;padding:16px}li{margin:14px 0}</style><h1>Westwood development collection</h1><p>16 faces, 64 planned snapshots, zero collected. Verify parking type, access and signs. Preserved blocks/sessions are excluded. Conditional sampling probabilities are in the JSON/CSV.</p><p>'+html.escape(result['workload'])+'</p><ol>'+''.join(rows)+'</ol>'
    (out/'development_plan.html').write_text(page,encoding='utf8');return {k:v for k,v in result.items() if k not in ['faces_detail','assignments']}
