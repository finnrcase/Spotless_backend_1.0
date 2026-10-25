"""Offline post-build validation, source registry and executed notebook."""
import json
from pathlib import Path
import subprocess
import sys
import hashlib
import geopandas as gpd
import pandas as pd

root=Path.cwd(); out=root/'data/processed'
raw_records=[json.loads(line) for line in Path('data/manifest.jsonl').read_text(encoding='utf8').splitlines()]
hashes={r['path']:r['sha256'] for r in raw_records if r.get('success')}
for path,digest in hashes.items():
    assert hashlib.sha256((root/'data'/path).read_bytes()).hexdigest()==digest, f'Raw hash mismatch: {path}'
faces=gpd.read_parquet(out/'pilot_block_faces.parquet')
mapping=pd.read_parquet(out/'meter_face_mapping.parquet')
current=pd.read_parquet(out/'pilot_current_occupancy.parquet')
from la_parking.build import create_map,write_coverage_markdown
create_map(gpd.read_parquet(out/'pilot_street_segments.parquet'),gpd.read_parquet(out/'pilot_meters.parquet'),gpd.read_parquet(out/'pilot_curbs.parquet'),current)
write_coverage_markdown(json.loads(Path('reports/coverage.json').read_text(encoding='utf8')))
counts=mapping[mapping.join_status=='matched'].merge(current,left_on='space_id',right_on='space_id',how='left',validate='one_to_one')
counts['fresh_known']=counts.state.isin(['OCCUPIED','VACANT'])&counts.stale.eq(False)
counts['has_sensor_observation']=counts.observed_at_utc.notna()
agg=counts.groupby('block_face_id').agg(linked_meters=('space_id','count'),sensor_observations=('has_sensor_observation','sum'),fresh_known_states=('fresh_known','sum'))
coverage=faces[['block_face_id']].merge(agg,on='block_face_id',how='left',validate='one_to_one')
for c in ['linked_meters','sensor_observations','fresh_known_states']: coverage[c]=coverage[c].fillna(0).astype(int)
coverage['observation_support']=coverage.fresh_known_states.map(lambda n:'partial_metered_evidence' if n else 'NO_OBSERVATION')
coverage['available_spaces']=pd.Series([pd.NA]*len(coverage),dtype='Int64')
coverage.to_parquet(out/'pilot_face_coverage.parquet',index=False)
assert not coverage.available_spaces.notna().any()
subprocess.run([sys.executable,'scripts/registry.py'],check=True)
# Add view for the post-build support summary.
import duckdb
with duckdb.connect(str(out/'parking.duckdb')) as con:
    quoted=str((out/'pilot_face_coverage.parquet').resolve()).replace("'","''")
    con.execute(f"CREATE OR REPLACE VIEW pilot_face_coverage AS SELECT * FROM read_parquet('{quoted}')")
subprocess.run([sys.executable,'-m','pytest','-q'],check=True)
subprocess.run([sys.executable,'scripts/inspection_notebook.py'],check=True)
checks={'raw_hashes_verified':len(hashes),'pilot_faces':len(faces),'faces_with_fresh_partial_metered_evidence':int(coverage.fresh_known_states.gt(0).sum()),'faces_with_no_fresh_observation':int(coverage.fresh_known_states.eq(0).sum()),'verified_unmetered_labels':0}
Path('reports/final_validation.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
print(json.dumps(checks,indent=2))
