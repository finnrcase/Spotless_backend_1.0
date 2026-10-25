import json
import os
import sys
from pathlib import Path
import nbformat as nbf
from nbclient import NotebookClient

root=Path.cwd();os.environ['IPYTHONDIR']=str(root/'.ipython');os.environ['JUPYTER_PATH']=str(root/'.jupyter');os.environ['JUPYTER_RUNTIME_DIR']=str(root/'.jupyter/runtime');os.environ['MPLCONFIGDIR']=str(root/'.matplotlib')
kdir=root/'.jupyter/kernels/la-parking';kdir.mkdir(parents=True,exist_ok=True)
(kdir/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],'display_name':'LA parking','language':'python'}))
nb=nbf.v4.new_notebook();nb.metadata.kernelspec={'display_name':'LA parking','language':'python','name':'la-parking'}
cells=[('markdown','# 02 — Time-specific parking models\n\nExecuted on actual September 2025 and August 2026 events. Targets are reconstructed metered sensor panels, not full-curb eligible capacity. No verified unmetered labels or suitable-space probabilities are claimed.'),
('code',"from pathlib import Path\nimport json\nimport pandas as pd\nfrom IPython.display import Image,display\nR=Path('reports/modeling')\nmanifest=json.loads((R/'label_manifest.json').read_text())\npd.DataFrame(manifest['quality'])"),
('markdown','## Fixed target and split protocol\n\n15-minute sensor-time bins; 5/15/60-minute cap sensitivity; panels fixed after a seven-day discovery period. Unknown intervals stay unknown. Geometry uses a later snapshot, so even calendar/history experiments remain retrospective.'),
('code',"protocol=json.loads((R/'experiment_protocol.json').read_text())\nprotocol['config']"),
('code',"metrics=pd.read_csv(R/'metrics.csv')\nmetrics.query(\"axis == 'future_time' and target == 'occupancy_rate'\")[[\"horizon\",\"model\",\"n\",\"r2\",\"mae\",\"label_coverage_fraction\"]]"),
('code',"display(Image(filename=str(R/'test_r2.png')))"),
('markdown','## Geographic transfer is a separate result\n\nThe north area and buffer are withheld. Own-face histories are removed, and neighboring features use training-area sensors only. The pure spatial test overlaps historical time periods; the combined future/unseen-area test is separately named.'),
('code',"metrics.query(\"axis != 'future_time' and target == 'occupancy_rate' and model == 'boosted'\")[[\"axis\",\"horizon\",\"n\",\"r2\",\"mae\"]]"),
('code',"display(Image(filename=str(R/'coverage.png')))\njson.loads((R/'geographic_support.json').read_text())"),
('markdown','## Counts, binary panel outcomes and uncertainty\n\nCounts require a complete sensor panel at the point time. A directly fitted binary panel-vacancy outcome avoids space-independence assumptions. It is not a verified legal-suitability label. Calibration and residual ranges use a separate earlier period, with empirical held-out coverage reported.'),
('code',"metrics.query(\"axis == 'future_time' and model == 'boosted' and target != 'occupancy_rate'\")[[\"target\",\"horizon\",\"n\",\"mae\",\"r2\",\"brier_score\",\"log_loss\",\"interval_coverage\",\"interval_mean_width\"]]"),
('code',"display(Image(filename=str(R/'calibration.png')))"),
('code',"pd.read_json(R/'ablations.json')[[\"axis\",\"horizon\",\"family_variant\",\"r2\",\"mae\"]]"),
('code',"pd.read_json(R/'persistence_sensitivity.json')"),
('markdown','## Forecast contracts and unsupported fields\n\nAll eligible-capacity, suitable-space probability and eligible net-change fields remain null. Sensor diagnostics and experimental activity ranks are isolated and labelled. Typical-pattern requests use no recent-state information.'),
('code',"examples=[json.loads(s) for s in (R/'forecast_examples.jsonl').read_text().splitlines()]\nassert all(r['probability_at_least_one'] is None and r['expected_available_spaces'] is None for r in examples)\npd.DataFrame(examples)[['forecast_mode','support','horizon_minutes','unavailable_reason']].value_counts()"),
('code',"json.loads((R/'validation.json').read_text())"),
('markdown','## Decision\n\nThis run supports reproducible experimental diagnostics on metered sensor panels. It does not establish unmetered, legal-duration or citywide accuracy. Independent randomized/repeated surveys, historical source alignment, and verified capacity/rules are needed before exposing numerical user predictions. The aspirational 0.50 unmetered test R² is not evaluated here.')]
nb.cells=[nbf.v4.new_markdown_cell(c) if kind=='markdown' else nbf.v4.new_code_cell(c) for kind,c in cells]
path=Path('notebooks/02_time_specific_models.ipynb');nbf.write(nb,path)
NotebookClient(nb,timeout=180,kernel_name='la-parking',resources={'metadata':{'path':str(root)}}).execute();nbf.write(nb,path)
print('Executed',path)
