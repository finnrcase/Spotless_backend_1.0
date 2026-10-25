"""Randomized block-time assignments, not fabricated field observations."""
import json
from pathlib import Path
import numpy as np
import pandas as pd


def make_survey_plan(start_date='2026-10-26',blocks=24,visits=12,seed=430):
    faces=pd.read_parquet('data/processed/pilot_block_faces.parquet',columns=['block_face_id','segment_id'])
    streets=pd.read_parquet('data/processed/pilot_street_segments.parquet',columns=['segment_id','street_name','street_designation'])
    eligible=faces.merge(streets,on='segment_id')
    eligible=eligible.loc[~eligible.street_designation.str.contains('Private|Outside City',case=False,na=False)]
    rng=np.random.default_rng(seed);names=eligible.segment_id.unique();selected=rng.choice(names,size=min(blocks,len(names)),replace=False)
    days=pd.date_range(start_date,periods=14,freq='D',tz='America/Los_Angeles')
    assignments=[]
    # Probability is for block selection only; repeated visits are conditional on selected block.
    for j,block in enumerate(selected):
        face=eligible.loc[eligible.segment_id==block].iloc[rng.integers(0,len(eligible.loc[eligible.segment_id==block]))]
        dates=rng.choice(len(days),size=visits,replace=len(days)<visits)
        for k,index in enumerate(dates):
            hour=int(rng.choice([8,12,17,20]));minute=int(rng.choice([0,15,30,45]))
            time=days[index]+pd.Timedelta(hours=hour,minutes=minute)
            assignments.append({'assignment_id':f'pilot-{seed}-{j:02}-{k:02}','block_id':block,'block_face_id':face.block_face_id,'street_name':face.street_name,
                'scheduled_local':time.isoformat(),'scheduled_utc':time.tz_convert('UTC').isoformat(),'sampling_method':'randomized',
                'block_inclusion_probability':len(selected)/len(names),'face_given_block_probability':1/len(eligible.loc[eligible.segment_id==block]),
                'evaluation_role':'unseen_block_holdout' if j>=int(len(selected)*.75) else 'development',
                'parking_type':'must_verify_in_field','visit_status':'planned_not_observed'})
    out=Path('reports/modeling');out.mkdir(exist_ok=True)
    pd.DataFrame(assignments).sort_values('scheduled_utc').to_csv(out/'randomized_survey_assignments.csv',index=False)
    details={'seed':seed,'selected_blocks':len(selected),'assignments':len(assignments),'dates':'14 local days','replacement_policy':'record missed visits; do not replace with convenient successes',
             'parking_types':'verify and stratify metered/unmetered after reconnaissance; absence of a meter is not a verified label',
             'initial_precision':'With 24 independent blocks, repeats do not make 288 independent units. Worst-case binomial independent-n planning gives n≈1.96²*0.25/e²: ~97 independent units for ±10 percentage points; inflate for block/day correlation and nonresponse. Estimate ICC/variability first, then expand blocks and times.',
             'aspiration':'No fixed R² target; earlier rough ranges were speculative and are not measured benchmarks'}
    (out/'survey_design.json').write_text(json.dumps(details,indent=2))
    return details
