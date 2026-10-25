# Fixed-target temporal improvement experiment

This continues the project and preserves the original design, labels, reports and service models. See [sensor audit](../reports/modeling/temporal_v2_audit/audit.md), [experiment table](../reports/modeling/TEMPORAL_V2.md), and versioned JSON/CSV reports in `reports/modeling/temporal_v2_*`. Measurements concern metered sensor-panel proxies, not verified full-curb or unmetered occupancy.

## Reproduce locally

Use the existing locked Python environment, from the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\temporal_experiment.py audit
.\.venv\Scripts\python.exe scripts\temporal_experiment.py features
.\.venv\Scripts\python.exe scripts\temporal_experiment.py acquire
.\.venv\Scripts\python.exe scripts\temporal_experiment.py predictors
.\.venv\Scripts\python.exe scripts\temporal_experiment.py run
.\.venv\Scripts\python.exe scripts\temporal_experiment.py check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\la-parking.exe field-route
```

The audit registers the protocol before fitting. Successful downloads are content-addressed and reused. Acquisition permits June and July 2026 only, at most two 450 MB archives; it does not request reserved September outcomes. ACS uses two free table exports (about 83 MB combined); Census geometry is bounded to the pilot plus a buffer, with complete-ID paging. No key, payment or public deployment is required.

New caches go to `data/modeling/temporal_v2` and models to `artifacts/models/temporal_v2`, both excluded from Git. The app's v1 artifacts remain intact. A completed run refuses automatic re-selection: register a separately versioned experiment for new choices. Do not delete reports to obtain a favorable score. The bulky candidate report stays local; concise selections, results, row hashes and CSV are tracked.

The implementation supports bounded execution partitions with `run --horizons ... --report-directory ...` and explicit `--resume`. Completed validation choices/models are reused. This run used a memory-bounded continuation and two local calculation processes with disjoint output reports; the final manifest records their partitions. `collate` merges disjoint horizons and checks duplicates without re-fitting or re-selecting. The default command above runs all horizons sequentially. Execution partitions do not change any test population, split, candidate grid or score objective.

## Comparison and validation

The primary target remains the exact v1 15-minute TTL sensor-time occupancy rate, requiring at least 25% known sensor-time. Counts/binary vacancy retain the v1 complete-panel point-label rule. No easier target, street aggregation or error-based row removal is used. Test identity/target hashes accompany every variant. Predictions are bounded; missing predictors use training-only imputation and indicators, never deletion of difficult test rows.

Temporal validation has two chronological origins, August 9 and 13, three-day windows and a three-hour training embargo. Regression choices minimize pooled validation squared error, aligning with R²; MAE is also reported. Probability heads use Brier separately and logistic calibration on the disjoint August 18–23 interval. History patterns fit fold training data only; each training row's encoding also uses only labels available by issue time. Local-clock day/week lookup leaves DST ambiguity missing.

Changes are isolated as original features with RMSE selection; a pooled face/hour/day baseline; causal patterns/trends/age/quality; consecutive historical training; broader Ridge/boosted settings; vintage-gated Census/LODES context; and housing/employment ablations. Time-of-week and persistence baselines retain all rows with pooled fallback. Direct persistence coverage is reported; unseen blocks have no own-history support.

Family variants receive the same declared candidate budget and tune independently on validation. Their differences include permitted re-tuning; they are not causal feature-importance estimates. The complete candidate ledger remains local, and the concise family comparison reports validation RMSE/MAE. Whole-block bootstrap intervals retain all days of each sampled block; the original block/day intervals are also kept. Both are conditional on the sparse sensor labels and cannot certify their validity.

Known-block forecasting uses earlier own-block observations. Geographic transfer masks own history and face patterns in training and prediction; neighbors come only from the southern training geography. The original northern holdout/buffer are preserved. Geographic models tune chronologically within training geography: that is not independent unseen-block validation. Pure geographic transfer and combined future/unseen tests are separate. October 2026 geometry/meter mapping remain retrospective; historical relocations are unverified.

The pure unseen-block test overlaps training dates and is retrospective geographic transfer; it does not establish future-time forecasting. The future/unseen test is the joint forward-time/geographic check. Probability calibration for the retrospective geographic comparison is also retrospective. Later-period results carry the time-generalization interpretation.

August 25–31 was already inspected: every result there is a legacy diagnostic. September 21–30 is reserved unopened, but the checked official catalog ends in August. Freeze choices before its first evaluation when published. November 7–14 prospective manual sessions and whole new blocks are reserved before collection. These are plans, not acquired labels. No fresh later-period evaluation result exists yet.

Paired block/day bootstrap intervals describe variability conditional on the proxy labels; they do not establish sensor truth or citywide accuracy. All versions must share identical test identities and targets.

Historical sensor features and pattern-label availability are an **event-time replay assuming immediate delivery**, not a certified historical ingestion timeline. Monthly archives are published with a two-month lag. Added June/July history represents what a continuous live-feed recorder could have accumulated; the files alone do not prove it was available for August forecasts. Actual delivery timestamps/latency were not supplied, so an archive-publication-only deployable backtest is unavailable. Demand context uses verified publication gates; this cannot resolve sensor delivery uncertainty. Fresh prospective ingestion logs and observations are required to validate an operational forecast.

## Sensor uncertainty

Official metadata calls the timestamp an occupancy transaction; no heartbeat cadence or delivery SLA is verified. Almost all successive known pilot states alternate. This supports a change-event interpretation, but silence alone cannot distinguish stable occupancy from outage. UNKNOWN/conflicting simultaneous states terminate known intervals. Reaffirmations are not automatically heartbeats.

Coverage uses both full-month retrospective and post-discovery causal denominators. The quoted 16.4% was not exactly reproduced: August is 16.87% full-month or 16.93% post-discovery in the retained snapshot. Comparisons of 5/15/60/180-minute caps and an unbounded state-change hypothesis are diagnostic. Common-bin label disagreement and selection effects are reported; prediction R² never selects the cap. Long unresolved intervals remain uncertain. Independent sensor truth is not yet available.

For independent checks, add a paired visit on a verified metered face: timestamp individual bay states (including unreadable/occluded), physical meter IDs, actual observation availability time, and a second observer count. Check historical positions before linking archived states. A sensor reconstruction cannot independently confirm itself. Four repeated snapshots can reveal a gross mismatch, but cannot validate a persistence policy or outage rate.

## Smallest useful unmetered batch

Open `reports/field_route.html` (app link `/field-route`) and tap **Start smallest batch: 8 counts over 1 hour**. It selects both sides of one short development block on October 27 at noon, +15, +30 and +60 minutes; the second side is about four minutes later. Links fill face/session/assignment IDs and map pins. Confirm public access, side and actual unmetered status in person. Reschedule explicitly if necessary; record actual times instead of copying planned times.

Record occupied counts, independently checked capacity, suitable/unsuitable vacancies, raw gap lengths, confidence, occlusion and posted rules for the whole intended stay. Blank means unknown; checked zero means zero. If both faces cannot be completed within each round, collect one face four times and log the other visits skipped. Export JSONL and import with `la-parking observations <file>`. Review labels before modeling; import is not approval. Eight counts test collection/change calculations only. Continue diverse block/day sessions and preserve whole held-out blocks before comparing unmetered-only against mixed training. Additional datasets never substitute for occupancy labels.

## Expansion gaps

No external credentials are required for successful acquisitions. Optional Census/Socrata keys help quotas. Needed evidence: historical sensor location/roster versions, documented latency/reporting semantics, independent meter checks, direct unmetered labels, historically versioned sign-complete supply/eligibility, and archived pre-issue business/event feeds. Current snapshots, historic curb polygons, vendor forecasts and date-only imagery cannot supply missing time-specific truth.
