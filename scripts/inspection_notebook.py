"""Create and execute the reproducible, offline data inspection notebook."""
import os
import sys
import json
from pathlib import Path
import nbformat as nbf
from nbclient import NotebookClient

root=Path.cwd()
nb=nbf.v4.new_notebook()
nb.metadata.kernelspec={'display_name':'Python (project environment)','language':'python','name':'la-parking'}
nb.cells=[
 nbf.v4.new_markdown_cell('# 01 — Los Angeles parking foundation inspection\n\nExecuted against real downloaded data. Unknown supply/occupancy stays unknown. This notebook does not train a citywide model.'),
 nbf.v4.new_code_cell("from pathlib import Path\nimport json\nimport pandas as pd\nimport geopandas as gpd\nimport duckdb\nROOT=Path.cwd()\nassert (ROOT/'data/processed').exists()\ncoverage=json.loads((ROOT/'reports/coverage.json').read_text())\npd.DataFrame([coverage['geography']])"),
 nbf.v4.new_markdown_cell('## Jurisdiction and approximate curb sides\n\nOfficial City boundary clips the street source. Offset faces are approximate. Physical curb footprints do not establish eligible capacity.'),
 nbf.v4.new_code_cell("segments=gpd.read_parquet('data/processed/street_segments.parquet')\nfaces=gpd.read_parquet('data/processed/pilot_block_faces.parquet')\nassert segments.segment_id.is_unique\nassert segments.is_valid.all()\nfaces.groupby(['geometry_method','applicability']).size().to_frame('faces')"),
 nbf.v4.new_code_cell("mapping=pd.read_parquet('data/processed/meter_face_mapping.parquet')\nmapping.join_status.value_counts().to_frame('pilot_meter_joins')"),
 nbf.v4.new_markdown_cell('## Time-specific evidence\n\nCurrent states are last-known transactions. Age is measured at retrieval. Historical event-time states are not continuous verified ground truth. Persistence caps are sensitivity policies, and UNKNOWN remains separate.'),
 nbf.v4.new_code_cell("pd.DataFrame(coverage['history'])"),
 nbf.v4.new_code_cell("current=pd.read_parquet('data/processed/pilot_current_occupancy.parquet')\ncurrent.groupby(['state','stale']).size().to_frame('meters')"),
 nbf.v4.new_code_cell("pd.read_parquet('data/processed/coverage_sensitivity.parquet')"),
 nbf.v4.new_markdown_cell('## Context and source quality\n\nCounts measure the downloaded registry/layer. They are not occupancy labels. Actual observation dates can differ sharply from a file name or metadata update timestamp.'),
 nbf.v4.new_code_cell("registry=json.loads(Path('config/source_registry.json').read_text())\npd.DataFrame(registry['sources'])[['id','status','priority','temporal_coverage']]"),
 nbf.v4.new_code_cell("pd.DataFrame(coverage['context_layers']).T"),
 nbf.v4.new_code_cell("with duckdb.connect('data/processed/parking.duckdb',read_only=True) as con:\n    summary=con.sql('SELECT count(*) AS faces, count(physical_capacity) AS faces_with_capacity FROM curb_inventory').df()\nsummary"),
 nbf.v4.new_code_cell("from IPython.display import IFrame\nIFrame('../reports/coverage_map.html',width='100%',height=600)"),
 nbf.v4.new_markdown_cell('## Modeling gate\n\nThere are **zero verified unmetered occupancy labels**. Use the manual schema/workflow to collect them. Metered temporal experiments can begin after reviewing sensor freshness and historical inventory mapping; duration-specific legal suitability and citywide predictions are not validated. Use forward-time and held-out-face evaluation, with as-of features and prospective surveys.'),
]
Path('notebooks').mkdir(exist_ok=True)
path=Path('notebooks/01_foundation_inspection.ipynb')
nbf.write(nb,path)
# Force the installed project interpreter without writing a global kernelspec.
os.environ['JUPYTER_PLATFORM_DIRS']='1'
os.environ['IPYTHONDIR']=str(root/'.ipython')
os.environ['JUPYTER_PATH']=str(root/'.jupyter')
os.environ['JUPYTER_RUNTIME_DIR']=str(root/'.jupyter/runtime')
kdir=root/'.jupyter/kernels/la-parking'; kdir.mkdir(parents=True,exist_ok=True)
(kdir/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],'display_name':'LA parking project','language':'python'}))
client=NotebookClient(nb,timeout=180,kernel_name='la-parking',resources={'metadata':{'path':str(root)}})
client.execute()
nbf.write(nb,path)
print('Executed',path)
