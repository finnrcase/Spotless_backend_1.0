from pathlib import Path
import pandas as pd
import geopandas as gpd

p=Path('data/processed')
mapping=pd.read_parquet(p/'meter_face_mapping.parquet')
print('mapping',mapping.head().to_dict('records'))
for name in ['pilot_history_2025_09','pilot_history_2026_08']:
 f=pd.read_parquet(p/f'{name}.parquet'); matched=f.merge(mapping.query("join_status=='matched'"),on='space_id',how='inner')
 print(name,'events',len(f),'matched',len(matched),'faces',matched.block_face_id.nunique(),'blocks',matched.segment_id.nunique())
 print('sensor count/face',matched.groupby('block_face_id').space_id.nunique().describe().to_dict())
 print('local dates',f.observed_at_utc.dt.tz_convert('America/Los_Angeles').dt.date.value_counts().sort_index().to_dict())
 print('ids',list(f.space_id.unique())[:5])
for name in ['pilot_street_segments','pilot_meters','static_features','events']:
 f=pd.read_parquet(p/f'{name}.parquet'); print(name,'columns',f.columns.tolist(),'head',f.head(1).to_dict('records'))
f=pd.read_parquet('data/staged/business.parquet');print('business columns',f.columns.tolist())
