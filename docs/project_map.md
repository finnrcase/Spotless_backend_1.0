# Project map

Start with [current status](current_status.md) for supported behavior and evidence. This is **Spotless_backend_1.0**, the app at this Git root. `Spotless/` is a separate reference checkout: leave it untouched. Inspect the task-relevant paths below rather than loading every report or rerunning pipelines.

## Application path

`pyproject.toml` registers `la-parking` → `src/la_parking/cli.py`. `la-parking serve` starts loopback-only FastAPI at `http://127.0.0.1:8765/`.

1. `web/map/{index.html,app.js,style.css}` collects destination, arrival/stay, walk limit, eligibility and price preferences; calls `/api/predictions`.
2. `service/api.py` validates `service/schemas.py`, refreshes snapshots and checks `service/refresh.py`'s bounded cache.
3. `service/repository.py` queries City geometry and approximate centerline walking distances. `service/eligibility.py` evaluates the entire stay independently of model confidence.
4. `service/inference.py` gathers evidence and adapts `forecasting.request_forecast()`. That function consumes frozen **v1** artifacts through `modeling.predict_head()`; it never trains. See status for exact paths and abstention conditions.
5. The response returns face geometry, ranking, timestamps, unknowns and isolated experimental panel diagnostics. The map renders evidence layers, details and the arrival slider. `/api/model-evidence` is a summary of v2/v3 evidence, not the model loader or the latest v4 report.

All Python paths in the preceding steps are relative to `src/la_parking/`. [Local service](local_service.md) covers API examples/OpenAPI; [refresh plan](service_refresh.md) distinguishes polling, evidence age, features, issuance and client refresh. `reports/service/` contains tracked contracts and small real-data examples.

## Data and collection

| Work | Code / entry points | Authority and boundaries |
|---|---|---|
| Cached public ingestion | `http.py`, `connectors.py`, `acquire.py`; `la-parking acquire` | `config/source_registry*.json`, [source registry](source_registry.md); `data/manifest.jsonl` records local raw provenance |
| City/pilot geometry | `build.py`, `spatial.py`; `la-parking build` | [Architecture](architecture.md), [quality report](../reports/starter/quality.md); source IDs, approximate offsets and unknown capacity retained |
| Existing starter/NAIP | `starter.py`, `imagery.py`; `integrate-starter`, `imagery-prepare/evaluate` | [Starter guide](starter_continuation.md), [imagery evidence](../reports/imagery/feasibility.md); 2022 date-only imagery is not current truth |
| Prospective context | `signals.py`, `westwood_context.py`; `acquire-signals`, `acquire-westwood-context`, `signal-features` | [Access research](data_access_research.md), [source freshness/coverage](../reports/westwood_context/coverage.md); issue-time receipt gates, no automatic historical backfill or model promotion |
| Manual counts | `contracts.py`, `observations.py`, `collector.py`; `collector`, `observations <jsonl>` | `web/collector/` → ignored standalone `reports/collector.html`; [phone guide](phone_collection.md), [field workflow](observation_workflow.md) |
| Repeated development route/media review | `collection_design.py`, `capture_collection.py`; `collection plan/import/review/effort/audit` | [Collection guide](capture_collection.md), [16-face plan](../reports/collection/development_plan.json); local SQLite/JSONL, deduplication, blinded review, no automatic CV labels |

`features.py` builds inspection features. `labels.py` constructs v1 sensor-panel labels; `temporal.py` owns uncertain event intervals. `model_features.py` builds causal design/calendar/history features; `modeling.py` fits original baselines and tabular models. Training commands live in [training.md](training.md), not the serving startup. Additional context is never an occupancy label.

## Experiments and frozen versions

| Version / workflow | Implementation and config | Results / protocol |
|---|---|---|
| Frozen v1 sensor panels (serving artifacts) | `labels.py`, `model_features.py`, `modeling.py`; `config/modeling.json` | [Model card](model_card.md), [original report](../reports/modeling/results_report.md) |
| Frozen temporal-v2 | `temporal_{acquisition,features,predictors,experiment}.py`, `sensor_audit.py`; `config/temporal_v2.json`; `scripts/temporal_experiment.py` | [Guide](temporal_v2.md), [fixed-row experiment table](../reports/modeling/TEMPORAL_V2.md) |
| Frozen spatial-v3 | `transfer_context.py`, `spatial_experiment.py`, `sensor_capture.py`; `config/spatial_v3.json`; `scripts/spatial_experiment.py` | [Guide](spatial_v3.md), [spatial results](../reports/modeling/SPATIAL_V3.md) |
| Frozen Census/regional-v4 | `census_coverage.py`, `regional_coverage.py`, `coverage_experiment.py`, `coverage_report.py`; `config/coverage_v4.json`; `scripts/coverage_v4.py` | [Guide](coverage_v4.md), [latest contextual comparison](../reports/modeling/COVERAGE_V4.md), [selection limitation](model_discipline_review.md) |
| Unmetered-only vs mixed training | `unmetered.py`; `config/unmetered_experiment.json` | [Guide](unmetered_modeling.md), [unavailable measured comparison](../reports/unmetered/comparison.md) |
| Direct suitability/ranking/product pilot | `product_{contracts,evaluation,pilot}.py`; `config/product_pilot.json`; `web/product_pilot.html` | [Guide](product_evaluation.md), [readiness](../reports/product/readiness.md); prospective trial ledger, no measured product gain |
| Controlled A/B/C/D direct observations | `controlled_observations.py`; `config/controlled_observations_v1.json` | [Protocol/commands](controlled_observations.md), [readiness table](../reports/controlled_observations/readiness.md); frozen fit/evaluate stages, no real cohort yet |
| Offline drone feasibility | `drone_feasibility.py`; `config/drone_feasibility.json`, isolated `requirements-drone.txt` | [Guide and execution blocker](drone_feasibility.md), [explicit simulation](../reports/drone_feasibility/simulation.md); no aircraft transport |

`evaluation.py` supplies shared metrics; `survey_design.py`, `field_route.py` and `regional_field.py` preserve earlier sampling plans. Experimental does not mean dead code. Frozen experiments, input hashes, holdout reservations, reports and ignored fitted bundles remain distinct. Do not merge versions, rerun training or open reserved outcomes for navigation/cleanup. [Evaluation protocol](evaluation_protocol.md) and root instructions govern new work.

## Commands and checks

From this Git root in PowerShell; replace `la-parking` below with `.\.venv\Scripts\la-parking.exe` and `python` with `.\.venv\Scripts\python.exe`.

| Need | Command |
|---|---|
| Restore locked environment | `uv sync --frozen --extra dev --python 3.13` |
| Run app / export contracts | `la-parking serve` / `la-parking schemas` |
| Prepare local collection files | `la-parking collector`; `la-parking field-route`; `la-parking collection plan` |
| Inspect direct experiment readiness without outcomes | `la-parking product-readiness`; `la-parking controlled-experiment readiness` |
| Python suite | `python -m pytest -q` (data integration checks need existing local datasets) |
| Collector/imagery JavaScript | `node --test tests/collector_model.test.mjs tests/imagery_model.test.mjs` |
| API/map browser flow | `python scripts/check_service_browser.py` (owns/stops local server) |
| Phone/review browser flows | `python scripts/check_starter_browser.py`; `python scripts/check_product_browser.py`; `python scripts/check_capture_review_browser.py` |
| Frozen-result integrity, no fitting | `python scripts/temporal_experiment.py check`; `python scripts/spatial_experiment.py check`; `python scripts/coverage_v4.py check` |

Use the matching `tests/test_<area>.py` for targeted changes. Browser scripts require local Chrome and generated files, keep fixtures isolated, and write ignored QA artifacts. Integrity checks may regenerate concise evidence reports, so inspect the diff afterward. `scripts/reproduce.py` performs acquisition/build, and `scripts/train_pipeline.py` trains; neither is a routine navigation check.

[Repository layout](repository.md) explains ignored data/artifacts and clone limitations. [Historical progress](progress.md) and the read-only [reference audit](spotless_audit.md) are archival context, not current-status entry points.
