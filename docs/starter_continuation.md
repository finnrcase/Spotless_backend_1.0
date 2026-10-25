# Starter integration and next field steps

The earlier citywide foundation, local FastAPI/map app, phone collector, trained sensor-panel artifacts and evaluation were preserved. The supplied `LA_Parking_Data_Starter.zip` was found in Downloads and imported into `data/reference/parking_data_starter`. Its README, results, sources, field protocol, manifest and actual schemas were inspected. The later flattened spare files had mismatched names; 105 were removed only after their contents matched retained package files by SHA-256. See `reports/starter/duplicate_cleanup.json`.

## What actually ran

* Verified all 96 packaged response hashes, byte lengths, source object-ID sets, 65 curb pages and 19 driveway pages against the combined exports. There are 6,402 curb and 1,803 driveway assets. Twelve curb IDs and five driveway IDs were absent from the larger cached pilot; imported staging/associations retain them without rewriting the existing analytical tables. There are 84 curb and 19 driveway candidates outside the exact requested WGS84 box, retained with explicit masks. Raw query completeness does not prove complete real-world asset coverage.
* Retained the existing 81,315 City street segments and 162,630 faces with unique authoritative source lineage. Westwood's larger 981-segment/1,962-face inventory and 122 trained auxiliary meter artifacts were preserved. Street sides remain approximate unless supported by physical curb geometry. Source segments may need topology review where one real block spans several segments.
* Kept curb/driveway assets as a **2017 inventory based on 2014 imagery**, with no verified current maintenance. Metadata edit dates and retrieval timestamps do not update the physical evidence. Polygons are not stalls; supply and legal capacity remain unknown. Original native asset units are retained in the schema audit; metre calculations use NAD83 / UTM 11N.
* Inspected the included 500×560 JPEG and primary raster 17317, `m_3411861_nw_11_060_20220511`. Its raster `/info` reports **pixelSizeX/Y = 0.6 in EPSG:26911 metres**. Service-wide pixel size is not used as local resolution. Capture is May 11, 2022, **date only**. Midnight does not establish flight time. The original export's aspect ratio expanded the returned extent to latitude 34.06382–34.06718; inferring its registration from a repeat request is labelled as such.
* Acquired only 12 additional pinned 360 m image tiles (600×600 each, about 1 MB in total). They are crops of the same selected raster, not twelve independent capture times; catalog overviews are not independent photos. Prepared 24 face tasks across low/high activity contexts and real residential/commercial/arterial/occluded scenes. `reports/imagery/contact_sheet.png` shows the real images and approximate corridors. [NAIP public-domain terms](https://catalog.data.gov/dataset/national-agriculture-imagery-program-naip-imagery) support this local experiment; no commercial imagery or AI enhancement was used.
* Built `reports/imagery/annotator.html`: explicit visible-curb/occlusion polygons, curbside/traffic-lane/uncertain vehicle boxes, confidence, review/completion flags, local persistence and JSON export/import. Unmarked areas remain unknown. `failure_examples.html` and its JSON contain **unverified assistant visual examples**, excluded from scored reference labels. A single frame cannot prove motion, parking legality or current occupancy.
* Checked actual public sources and preserved request evidence. The LADOT-owned CDS catalog item points to a service returning “No Layers”; the separate public corridor API exposes DTLA geometry and returns zero Westwood records. The legacy permit export reports 155 rows but returns empty attributes/null geometry. An alternative official City layer yielded six district polygons with no verified current rule/eligibility completeness. Legacy permit-page URLs returned 404; current official LADOT FAQ/online-services pages remain readable. See [source findings](../reports/starter/source_findings.md).
* Downloaded the actual 206-page November 2021 Venice report and recovered 48 zone/time-band occupancy cells. Percentages above 100 are retained because its unmarked capacity uses an assumed 20 feet per position. These mixed historic aggregates lack independent block-face timestamps and cannot validate unmetered forecasts. The PDF has no embedded raw attachments. The CSV retains source page, URL and hash; no report aggregates were relabelled as full-face truth.
* Added 187 bounded Census 2020 block geometries and joined 148 to the existing 2023 LODES records. The other 39 remain missing. Availability/publication history must be verified before historical forecasting use. Existing business/event/transit/weather sources were reused; ACS and several effective-date histories remain unresolved. These are predictor candidates; later ablations must measure benefit.

Detailed geometry/schema/provenance evidence: `reports/starter/quality.json`. Every import and new acquisition retains bytes, hashes, retrieval times and failures in `data/manifest.jsonl`. Repeating import does not redownload source pages or append duplicate import records.

## Local use and reproduction

From this project folder in PowerShell:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
uv sync --frozen --extra dev --python 3.13
.\.venv\Scripts\la-parking.exe serve
```

Open **http://127.0.0.1:8765/** for the existing prediction app, **/field-route** for planned visits, **/collector** for observations, **/imagery** for the annotation workflow, and **/docs** for API contracts. All app services remain local. The collector and route HTML also work as self-contained files; keep `reports/collector.html` and `reports/field_route.html` together when transferring them. Actual iPhone/Android file handling and GPS support still require a device trial; see [phone instructions](phone_collection.md).

Reuse the supplied snapshots and cached tiles without network requests:

```powershell
.\.venv\Scripts\la-parking.exe integrate-starter
.\.venv\Scripts\la-parking.exe field-route
.\.venv\Scripts\la-parking.exe collector
.\.venv\Scripts\la-parking.exe imagery-prepare
.\.venv\Scripts\python.exe scripts\imagery_review_assets.py
.\.venv\Scripts\la-parking.exe schemas
.\.venv\Scripts\python.exe scripts\finalize_starter.py
```

`integrate-starter --path <zip-or-folder>` handles the package folder, a parent containing `parking_data_starter`, or the original ZIP. It refuses conflicting existing content and unsafe ZIP paths. There is no reason to rerun the starter download script for these existing data.

For deliberate bounded acquisition/inspection on a fresh checkout, run `scripts/starter_sources.py`, `scripts/starter_expand.py`, then `imagery-prepare --download`. The latter permits at most twelve small missing image tiles and reuses matching cached exports. `scripts/extract_starter_survey.py` reproduces PDF extraction from the cached report. Failed optional URLs are logged and do not invent replacement data. Rebuilding the older source registry merges `config/source_registry_supplement.json`.

## Field route and exact next actions

The [route sheet](../reports/field_route.md) uses Le Conte, Levering, Gayley, Broxton, Weyburn and Landfair, with both sides, source diagrams, stable codes and automatically filled IDs. Confirm actual sides, public access, intersections, parking type and signs during reconnaissance. The first 20-face route reserves up to 100 minutes per window; measure real workload before expanding.

The concrete schedule is October 27 and 29 plus November 1, 2026, with morning 09:00, afternoon 14:00 and evening 18:00 starts: 180 planned observations. Two sides of a short development block add t/15/30/60-minute repeats at noon, 24 more planned visits. Route order rotates/reverses; the design remains purposive rather than citywide representative. Three entire source blocks are reserved for unseen-block evaluation. Repeats do not create independent blocks. Sunday wall times handle the DST change explicitly.

1. Open the route/collector on the phone and **collect the first four faces only**. Record actual times, counts, raw gap lengths/convention, occlusion, posted/temporary rules, stay/profile and confidence. Leave unknown fields blank; do not turn one large gap into one exact stall. Record skipped visits and reasons without creating zero-count observations.
2. Export JSONL, keep a backup, and import the small batch through the app or `la-parking observations <export.jsonl>`. Review location, count reconciliation, capacity basis and whole-stay rules before collecting the remaining schedule. No ID or coordinate transcription is required.
3. After that quality check, complete/revise the remaining planned visits and repeats. Preserve the revision/skips and holdout blocks. Training and calibration need earlier reviewed labels and sufficient independent later tests; the 204-assignment plan is not a power guarantee.

## Evaluation and blockers

The real manual observation store is still empty. Existing reported model results remain **auxiliary meter-panel proxy results**, separately measured in `reports/modeling`; none demonstrate unmetered or citywide accuracy. The unmetered comparison remains unavailable until reviewed direct labels and frozen as-of tables exist. It compares unmetered-only versus compatible mixed training against mean, time-week, face and fresh-state persistence baselines, with separate later known-block and later unseen-block tests, R²/MAE/RMSE and probability calibration. Persistence reports fresh-state coverage and mean fallback; own-block persistence is unavailable on unseen blocks. No fixed R² target applies; earlier rough ranges were speculative.

No overhead-vehicle detector, weights or compatible detector runtime is configured. Therefore **imagery count MAE, precision and recall are unmeasured**, with null fields in `reports/imagery/evaluation.json`. Independent human annotations are also outstanding. This is the explicit annotation-workflow fallback, not a claimed detection run. Once both references and actual predictions exist:

```powershell
.\.venv\Scripts\la-parking.exe imagery-evaluate --annotations path\to\reviewed.json --predictions path\to\detector_predictions.json
```

Predictions are one record per task with `task_id`, exact `image_sha256`, `detector_id`, and `boxes` as `[x,y,width,height]` in image pixels. The evaluator checks bounds/hash identity, reviewed visible masks and one-to-one IoU≥0.5 matches. Box centres determine visible-area inclusion; overlapping occlusion masks take precedence. It reports coverage and excludes unreviewed/unseen areas. This measures historic visible vehicle candidates, not full-curb occupancy, legally eligible vacancies or arrival-time performance.

Current complete restrictions, direct unmetered labels, exact imagery capture times and device field testing remain unresolved. No additional credentials are required to run the local app or use the acquired public data. A Census API key remains optional for the blocked ACS path. Paid imagery/parking vendors, proprietary terms, production services and public deployment are future decisions; nothing was purchased or deployed.
