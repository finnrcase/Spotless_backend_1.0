"""Offline modeling pipeline over preserved acquired data; no acquisition/purchases."""
import argparse
import subprocess
import sys
from pathlib import Path
from la_parking.labels import build_labels
from la_parking.model_features import build_design
from la_parking.modeling import train_models
from la_parking.forecasting import build_forecast_artifacts
from la_parking.model_report import report
from la_parking.model_validation import sensitivity,audit_artifacts
from la_parking.survey_design import make_survey_plan

p=argparse.ArgumentParser();p.add_argument('--reuse-labels',action='store_true');p.add_argument('--reuse-models',action='store_true');a=p.parse_args()
if not a.reuse_labels:build_labels();build_design()
if not a.reuse_models:train_models()
build_forecast_artifacts();sensitivity();report();make_survey_plan();print(audit_artifacts())
from la_parking.evaluation import write_readiness
write_readiness()
from datetime import datetime,timezone
import hashlib,json,sklearn
run_path=Path('artifacts/models/run_manifest.json')
if not run_path.exists():
    run_path.write_text(json.dumps({'manifest_created_at_utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,'scikit_learn':sklearn.__version__,
        'uv_lock_sha256':hashlib.sha256(Path('uv.lock').read_bytes()).hexdigest(),'models_saved':len(list(Path('artifacts/models').glob('*.joblib'))),
        'code_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/la_parking').glob('*.py')},'note':'Provenance manifest assembled after completed fitting; artifacts are retrospective sensor-panel experiments'},indent=2))
subprocess.run([sys.executable,'-m','pytest','-q'],check=True)
subprocess.run([sys.executable,'scripts/modeling_notebook.py'],check=True)
