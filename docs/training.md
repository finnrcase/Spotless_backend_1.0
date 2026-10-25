# Run the time-specific modeling pipeline

For new performance work, use the [versioned temporal-v2 experiment](temporal_v2.md) and its [fixed-target comparison table](../reports/modeling/TEMPORAL_V2.md). The commands below reproduce v1, including its legacy MAE-based tuner, and overwrite its generated artifacts. V2 keeps those artifacts intact, selects occupancy/count models on chronological squared error, and reserves later outcomes before selection.

The commands below reproduce the auxiliary **metered sensor-panel** experiment. For the core unmetered target, use the [review, predictor preparation and held-out comparison workflow](unmetered_modeling.md). Meter-panel scores are not unmetered scores.

Run from this project folder. The preserved acquired data are the inputs; no API access, paid services or deployment is needed for training.

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
uv sync --frozen --extra dev --python 3.13
.\.venv\Scripts\python.exe scripts\train_pipeline.py
```

This reconstructs bounded sensor-state labels, builds features, fits/tunes models, evaluates all horizons and both generalization axes, writes forecasts/maps/reports, creates randomized collection assignments, runs tests and executes Notebook 02. On this workspace it produced 122 local model files and 200 model/target/horizon evaluation rows. Output sizes and runtime depend on interval and source scope; the current design has 975,840 candidate rows, of which 251,539 have supported rate labels across the five leads. Repeated horizons do not represent independent observations.

Configuration: `config/modeling.json`. Retain its source fingerprint and freeze new final test periods before model development. The current August 25–31 final test has now been inspected; further research should obtain a new prospective holdout rather than treating this period as newly untouched.

To inspect or re-render an existing run without changing fitted models:

```powershell
.\.venv\Scripts\python.exe scripts\train_pipeline.py --reuse-labels --reuse-models
```

Reusing labels/models is appropriate only when their input, feature and split fingerprints match; the validation checks compare the stored design fingerprint. Use the full command after acquisition, configuration or feature changes. `initial_rate_results.json` preserves the preliminary rate inspection before a count-head correction; the validation verifies unchanged rate results. If intentionally changing rate specifications later, preserve this experiment in a separately named run rather than overwriting its comparison audit.

Individual reusable steps:

```powershell
.\.venv\Scripts\la-parking.exe prepare-models
.\.venv\Scripts\la-parking.exe train
.\.venv\Scripts\la-parking.exe survey-plan
.\.venv\Scripts\la-parking.exe collector
.\.venv\Scripts\la-parking.exe schemas
```

Forecast requests can be replayed at a supported historical issue time:

```powershell
.\.venv\Scripts\la-parking.exe forecast --face "<block_face_id from pilot_block_faces.parquet>" --issued "2026-08-25T17:00:00Z" --arrival "2026-08-25T18:00:00Z" --stay 60 --output reports\request.json
```

Default current-time requests with no usable recent data return insufficient data; stale historical states are never silently carried into today. Requests above 120 minutes can use a separately labelled typical-pattern sensor model on historically observed faces. `--experimental-transfer` enables a current business-density rank on supported pilot context, never a validated unmetered occupancy probability. Full-stay eligible capacity/count/probability and net-change fields remain null while rules/capacity are unknown. Supported panel count differences are isolated under diagnostics and do not guarantee available suitable spaces.

Read [results_report.md](../reports/modeling/results_report.md), [model_card.md](model_card.md), `reports/modeling/validation.json` and `notebooks/02_time_specific_models.ipynb`. Static PNG/SVG figures include R², probability reliability and city/pilot coverage. Detailed stratification/reliability tables are in results.json; all model baselines are in metrics.csv. Local Parquet artifacts live in ignored `data/modeling`, and trusted fitted estimators in ignored `artifacts/models`.

Before showing numerical predictions to users: collect independent metered/unmetered counts, verify physical/eligible capacity and complete interval rules, align historical/current geometry, confirm event delivery and sensor persistence, expand observed areas and repeat prospective tests. No unmetered test R² is available from these data.
