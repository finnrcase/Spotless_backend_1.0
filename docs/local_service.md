# Local prediction service and map

The app runs a FastAPI API and a small vanilla JavaScript/SVG street map on your computer. The complete destination → street discovery → full-stay rules → inference → response → map flow uses the actual local City of Los Angeles street inventory, sensor archives and trained model artifacts. No paid service, external map SDK, remote database or public deployment is needed.

## Run

From this folder:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
uv sync --frozen --extra dev --python 3.13
.\.venv\Scripts\la-parking.exe serve
```

Open **http://127.0.0.1:8765/**. API documentation: **http://127.0.0.1:8765/docs**; machine contract: **http://127.0.0.1:8765/openapi.json**. Use `serve --port 8766` if the port is busy. The default binds only to loopback. Stop with Ctrl+C. The map is a local street diagram with zoom and destination clicks, so it works without online map tiles. Local street-name search returns an approximate segment center, not full postal-address geocoding.

The first request builds a local walking graph and loads the compact inference data; it takes several seconds. Repeated identical requests reuse a bounded cache. Source ingestion, offline training, inference and frontend code remain separate (`acquire.py`, modeling modules, `service/`, `web/map/`). Training is never triggered by serving, refresh or observation submission.

## Use the demo

1. Choose a street, enter coordinates, or click the map. Select arrival, intended stay, maximum walking distance, permit/vehicle profile and optional price preference.
2. In **Live request**, the preserved sensor snapshot will usually be old. A fresh API computation must still show that old evidence, and short-horizon numeric panel estimates remain unavailable until a genuine recent feature window exists. A successful current-state poll does not reconstruct transitions/history or authorize numerical predictions.
3. In **Historical replay**, the explicit origin is August 25, 2026, 10:00 a.m. Los Angeles time. The slider adds 0–120 minutes to arrival and reissues the request. These are real archived events/models, not synthetic data or live parking. Replay assumes immediate event delivery and uses later-vintage geometry, as documented in the model card.
4. Select lines or ranked results for timestamps, evidence age, rules/verification sources, capacity/model uncertainty and upcoming restrictions. Current official coverage and posted-sign review are displayed separately; neither is inferred from model confidence.

Colors: green = recent observation evidence at the selected issue time; blue = experimental fitted sensor-panel estimate; purple = explicitly enabled unvalidated activity prior; gray = insufficient data; red = verified restriction that excludes the requested stay/profile. A red line does not claim zero physical spaces. Conflicts remain unknown and explained in details. Actual default rule data are empty; no synthetic restrictions were inserted to make the red layer appear.

Eligible-space counts, suitable-space probabilities and eligible net changes remain **null** where capacity/rules/labels are unsupported. Optional panel probabilities/counts and 15/30/60-minute count differences are isolated and labelled as partial metered-panel proxies. Missing supplemental horizons show unavailable rather than interpolation or invented precision. Above 120 minutes, historically observed faces can show a separately labelled typical calendar pattern, with no assertion of fresh occupancy.

Ranking first respects verified eligibility/prohibitions and would use supported suitable-space probability if available. Since none is validated now, it falls back to estimated walking distance and optional indicative published prices. It never ranks a business-density prior or panel probability as suitable-space probability and never invents expected search time. Published price ranges do not establish future tariffs or that unmetered parking is free.

Walking distance follows the available centerline network, including approximate connections from the destination and curb side. Private/freeway/ramp segments are excluded. Crosswalks, pedestrian access, sidewalk barriers and accessible routes are unverified, so this is explicitly an **estimate**, not validated pedestrian navigation. Returned faces satisfy the requested maximum under that estimate. Disconnected/no-near-network locations return no reachable faces; the API never silently substitutes straight-line distance as walking distance. Candidate limits and outside-City destinations are explicit.

## Rules and eligibility

The read-only local rule snapshot defaults to `data/service/restrictions.json` (path configurable in `config/service.json`). Start from `config/restrictions.empty.json`. The exported OpenAPI contract defines `RestrictionRecord` and `RuleCoverage`.

Each record must preserve source kind (`official` or `posted_sign_review`), raw text/source URL, effective dates, availability time, review status and verification date. Complete coverage needs its own validity window and expiry. Recurring schedules use America/Los_Angeles; offset-aware absolute times use UTC on the wire. Entire stays are evaluated on elapsed time, including midnight and DST. A restriction that begins during the stay can exclude it. Permits/vehicle/time limits are evaluated for the requested profile. Missing or expired coverage is **unknown**; explicit contradictory verified permissions/prohibitions are **conflict**, with no invented precedence. Ambiguous DST schedule boundaries require review.

Newly collected sign notes are observations, not automatically current official rules. Add only actually reviewed records to the rule snapshot; `/api/refresh` validates/reloads them. Malformed snapshots are rejected and coverage becomes unknown. Complete coverage is a substantive claim about all relevant rules, not just the absence of rows.

## Observation submission/import

Use the full `/collector` form for timed sweeps, GPS/map pins, sampling method, confidence, capacity measurements and sign notes. Export JSONL, then import it through the map’s file input or:

```powershell
.\.venv\Scripts\la-parking.exe observations path\to\observations.jsonl
```

The map detail card also offers a minimal real in-person snapshot submission. Replay mode blocks that form to avoid mistaking a demonstration for a visit. The API accepts batches of at most 500 records / 2 MB via `POST /api/observations`, returns per-line rejections, and stores accepted records locally. Current imports clear caches and appear as recent reviewable evidence. They do not train the model, validate a suitable-space probability, verify posted rules, or remove location/label review flags. All automated fixture observations are isolated in temporary directories; no synthetic examples enter the real observation store.

## API and verification

Main routes: `GET /api/config`, `/api/destinations`, `/api/streets`, `/api/health`, `/api/time/resolve`; `POST /api/predictions`, `/api/observations`, `/api/refresh`. ISO timestamps must be aware. The local-time resolver rejects spring DST holes and requires an explicit first/second occurrence for a repeated autumn hour. Response timestamps distinguish issue, computation and response/cache time; block rule checks use the same requested arrival/stay endpoints.

`reports/service/openapi.json`, `example_replay.json`, `example_live.json` and `health.json` are reproducible real-data examples generated by `python scripts/service_smoke.py`. Browser verification: `python scripts/check_service_browser.py`; API/edge tests: `python -m pytest tests/test_service.py -q`. The browser check owns/stops a temporary loopback server and uses an isolated Chrome profile. Read `docs/service_refresh.md` for scheduling and expansion dependencies.
