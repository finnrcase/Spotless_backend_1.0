# Los Angeles parking data foundation

The [temporal improvement experiment](docs/temporal_v2.md) audits sensor semantics, adds causal block patterns and consecutive history, and compares models on fixed legacy targets using chronological validation RMSE. The [experiment table](reports/modeling/TEMPORAL_V2.md) separates known/unseen blocks and keeps unmetered accuracy unsupported. New September and prospective manual holdouts are reserved unopened.

Project repository: [finnrcase/Spotless_backend_1.0](https://github.com/finnrcase/Spotless_backend_1.0). This folder is the Git root. See [repository layout and local-data exclusions](docs/repository.md).

Local data foundation for arrival-time and duration-specific street-parking prediction within the **City of Los Angeles**. Westwood/UCLA is the first inspection pilot; street coverage is citywide. This is separate from the read-only ECON 430 [Spotless reference](https://github.com/finnrcase/Spotless/tree/4fc449ac2d8302fc7d8856345867bc0483e35ca8).

**No verified contemporary full-face unmetered occupancy labels have been acquired.** Capacity and legally eligible space counts remain null where unverified. The project does not claim citywide prediction accuracy or a completed legal-rule engine.

**Unmetered parking is a core prediction target.** The [unmetered comparison workflow](docs/unmetered_modeling.md) combines direct reviewed observations with demand, curb supply and time-dependent restriction predictors. It compares unmetered-only and mixed metered/unmetered training against four unmetered baselines on identical held-out unmetered observations, with separate time/block tests. Run `.\.venv\Scripts\la-parking.exe compare-unmetered` for the [current unavailable-results report](reports/unmetered/comparison.md). Whether metered training helps remains unmeasured until actual labels are collected; the existing meter models are auxiliary experiments.

The starter package is now integrated without rerunning its downloads. See [the continuation guide](docs/starter_continuation.md), [geometry quality audit](reports/starter/quality.md), [source findings](reports/starter/source_findings.md) and [imagery feasibility report](reports/imagery/feasibility.md). The local app links to a concrete 20-face field route and a 24-face historic-image annotation workflow. Vehicle detection metrics remain unmeasured because no detector/runtime or independent reference annotations are configured.

## Reproduce on Windows / PowerShell

Install Python 3.13 and [uv](https://docs.astral.sh/uv/) if unavailable. From this folder:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
uv sync --frozen --extra dev --python 3.13
.\.venv\Scripts\la-parking.exe schemas
.\.venv\Scripts\python.exe scripts\reproduce.py
```

The complete command acquires bounded public data, builds tables/map/DuckDB views, runs tests, and executes the inspection notebook. Successful requests are cached: rerunning resumes completed pages/files. Network access is needed on first acquisition; failed optional sources are documented without inventing replacements. Current sensor feeds can change during pagination. Two monthly history files total about 457 MB; the initial raw snapshot set is about 653 MB, plus staged/processed data and the Python environment. The 450 MB ceiling applies per history file, not to the whole run. No paid services, deployment, or upstream repository writes occur.

For individual steps:

```powershell
.\.venv\Scripts\la-parking.exe acquire --months 2025_09 2026_08
.\.venv\Scripts\python.exe scripts\supplement.py
.\.venv\Scripts\python.exe scripts\activity.py
.\.venv\Scripts\python.exe scripts\registry.py
.\.venv\Scripts\la-parking.exe build
.\.venv\Scripts\python.exe scripts\finalize.py
```

Use `acquire --refresh` deliberately for new snapshots. It retains old raw content; staging/processed files are rebuildable projections of the selected latest requests. History asset URLs come from current attachment metadata; an unavailable month fails explicitly. Change the pilot bounding box in `src/la_parking/sources.py` before a controlled expansion; every source is queried with that scope where feasible. Never expand parcels by default: `parcel_on_demand` requires a small explicit bounding box and feature budget.

`finalize.py` verifies raw hashes, builds per-face evidence support, runs tests and executes the notebook. Run tests alone with `.\.venv\Scripts\python.exe -m pytest -q`.

If a Census key becomes available, set `$env:CENSUS_API_KEY` before acquisition. Optional `$env:SOCRATA_APP_TOKEN` improves SODA quotas. `.env.example` documents names; `.env` is **not automatically loaded**. Credentials are excluded from cache keys and manifests. No credentials are required for the sources successfully acquired in this run.

## Inspect results

* `notebooks/01_foundation_inspection.ipynb`: executed inspection with real counts, timestamps, join/coverage checks and modeling limitations.
* `reports/coverage_map.html`: interactive pilot street, physical-curb and meter-inventory map. It is a coverage map, not an availability forecast. Leaflet assets load from public CDNs; no external basemap is required.
* `reports/coverage.json`, `reports/coverage.md`: measured source/geometry/occupancy quality and freshness.
* `config/source_registry.json`, `docs/source_registry.md`: verified URLs, field schemas, owners, terms, access, cadence, dates, statuses, priorities and unresolved candidates.
* `data/manifest.jsonl`: immutable raw snapshot hashes and request evidence; local datasets are ignored by Git.
* `data/processed/parking.duckdb`: views over local Parquet/GeoParquet. Paths point to this workspace; rerun the build after moving the folder.

Python reusable logic lives in `src/la_parking`. Numbered notebooks explain and inspect outputs; acquisition does not depend on hidden notebook state. `uv.lock` pins the environment. Raw responses remain unmodified, with projected XY geometry and cleaned timestamps stored separately.

## Continue the project

The working local API and minimal map are now available. Run `.\.venv\Scripts\la-parking.exe serve` and open **http://127.0.0.1:8765/**. It includes destination/street search, estimated walking routes, full-stay eligibility checks, explicit archive replay, evidence layers, an arrival slider, observation submission/import and refresh monitoring. See [local service instructions](docs/local_service.md) and [refresh/expansion plan](docs/service_refresh.md). OpenAPI is served at `/openapi.json`; no external service or deployment is required.

The time-specific modeling pipeline has been implemented and run. See [training commands](docs/training.md), [measured results](reports/modeling/results_report.md), [model card](docs/model_card.md) and `notebooks/02_time_specific_models.ipynb`. These are metered sensor-panel experiments, with explicit partial coverage and retrospective geometry; user-facing legally suitable parking fields remain unsupported/null.

The first phone-friendly collector is available locally: run `.\.venv\Scripts\la-parking.exe collector`, then open or transfer `reports/collector.html`. It supports street-side selection, short count snapshots, explicit metered/unmetered status, GPS or reviewed map pins, device-local saving, backup export and validated import. See [phone instructions](docs/phone_collection.md). No deployment is needed for the standalone file.

Confirmed modeling commitments are in [the evaluation protocol](docs/evaluation_protocol.md): held-out R² and MAE with training-only baselines, probability calibration, separate future-time/unseen-block tests and separate metered/unmetered results. There is no fixed R² target; earlier rough ranges were speculative. Experimental metered sensor-panel results are now measured; no unmetered or citywide accuracy is claimed.

Read `docs/progress.md`, `docs/spotless_audit.md`, `docs/architecture.md`, `docs/observation_workflow.md` and `docs/modeling_readiness.md`. Exported contracts are in `schemas/`. Start field collection with:

```powershell
.\.venv\Scripts\la-parking.exe observations path\to\surveys.jsonl
```

Before predictive application use, verify historical meter locations, sensor reliability, side assignments, full sign/rule content and exclusion completeness; collect independent unmetered observations. Evaluate forward in time and across held-out block faces/areas. Current business/meter snapshots and realized weather cannot be treated as historical information known at a forecast issue time.
