# Census, regional labels and collection continuation

The [measured experiment table](../reports/modeling/COVERAGE_V4.md) and [all variants](../reports/modeling/coverage_v4_experiments.csv) record the positive and negative results. No production model or label policy was replaced. The service still distinguishes unsupported geography, experimental estimates and unknown whole-stay eligibility.

The local key is now loaded safely, but the real one-tract authenticated request returned Census's invalid-key HTML page despite HTTP 200. Authentication **failed**. No value was printed or committed. Replace/activate the key locally if necessary and rerun the small check; development does not depend on another key. Census API values could not be compared to the cached tables because no authenticated data response succeeded. The comparison instead verifies official static 2023 ACS estimates and MOEs against the previously extracted data, with zero differences.

```powershell
.\.venv\Scripts\python.exe scripts/verify_census.py
.\.venv\Scripts\python.exe scripts/coverage_v4.py census
.\.venv\Scripts\python.exe scripts/coverage_v4.py occupancy
.\.venv\Scripts\python.exe scripts/coverage_v4.py locations
# Evaluate once per registered experiment. A completed run refuses further tuning.
.\.venv\Scripts\python.exe scripts/coverage_v4.py evaluate
.\.venv\Scripts\python.exe scripts/coverage_v4.py check
.\.venv\Scripts\la-parking.exe field-route
.\.venv\Scripts\la-parking.exe collector
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/collector_model.test.mjs tests/imagery_model.test.mjs
.\.venv\Scripts\python.exe scripts/check_starter_browser.py
.\.venv\Scripts\python.exe scripts/check_service_browser.py
```

`occupancy` requires the existing cached archives pointed to by `data/staged/history_{2025_09,2026_08}.json` and `data/staged/temporal_v2/history_{2026_06,2026_07}.json`; it fails rather than redownloading missing files or opening a new period. It scans only the already-used months, filters the fixed bounded sensor mapping, and preserves hashes. `locations` repeats only location checks and cached event-pattern summaries; no archive rescan is necessary. Location-only ArcGIS exports have a 4,500-feature maximum per regional bbox, exact ID reconciliation and explicit failure rather than truncation. Current status values are excluded to protect the prospective period.

The archived city events retain source event timestamps and archive retrieval dates. Their actual delivery latency is unknown; all historical models still assume immediate availability, and mapping is retrospective to the October inventory. Sensor presence in the Sep2025/June2026 discovery week selected candidates; that conditions this sample on reporting coverage. Later coverage selection is visible in the reports, not used to replace difficult blocks. Entire selected physical blocks, both faces and missing label intervals stay in the inventories. Mapping ambiguities never become guessed labels. Reporting-ID changes are not proof of installation or sensor replacement. Audit inventory sensor-days without events is a retrospective inventory diagnostic, not proof of outage or the monthly discovery roster.

County ACS values live under `data/modeling/coverage_v4/`: original estimates and 90% MOEs, GEOIDs, 2020 tract geometry, derived ratios and point-to-tract joins. Public release is December 12, 2024; the conservative feature availability timestamp is December 13 UTC, before these 2025/2026 replay origins. Raw retrieval timestamps and content hashes remain distinct. Derived ratio MOEs are unavailable without covariance. Zero household denominators and Census sentinel estimates remain unknown; no missing ratio becomes zero. The existing no-vehicle fraction and housing density are reused once. New predictors are one-person households and a censored lower bound on vehicles per household. Countywide predictor coverage is not citywide occupancy coverage.

Training uses pooled/weekhour baselines and fixed ExtraTrees settings from `config/coverage_v4.json`, two rolling origins and full neighborhood holdouts. Regression selects on squared error; the binary objective and chronological Platt calibration are separate. The final old Westwood benchmark is verified against v1/v2 target digests. A row-identity check initially caught June/July rows being added to the pure geographic diagnostic; the reporting mask was corrected to original legacy rows without changing model candidates, validation or targets. Results remain legacy diagnostics. All prospective Sep21–30, Oct25–31, Nov7–14 and Nov15–21 reservations remain protected; no new archive/current-status outcomes were requested. The completed run and model hashes are frozen in `coverage_v4_lock.json`; `check` validates inputs, equal variant rows, timestamps and rate/probability/count bounds without fitting.

The smallest useful collection action remains the **eight-count Westwood batch**: both sides of S Levering Avenue between W Roebling Avenue and W Le Conte Avenue, October 27 at 12:00/12:15/12:30/13:00 (second side four minutes later). Open `reports/field_route.html`, tap the small-batch button, and use its prefilled collector links. Verify unmetered/public access, signs, capacity and parked/usable counts. Log missing visits, use actual timestamps, export JSONL, then import with `la-parking observations path\to\surveys.jsonl`. Review labels before fitting; eight snapshots test the workflow, not accuracy.

Optional expansion sessions are November 2 (Downtown) and November 3 (Hollywood), each eight snapshots over an hour. Different complete blocks are reserved for November 18 and 19, also eight snapshots each. Stable IDs, street names, cross streets and approximate side maps are already generated from the actual inventory; no coordinate transcription is needed. A no-meter-within-30m filter only chooses reconnaissance candidates. It never asserts unmetered or unrestricted status. `config/coverage_v4_field_holdouts.json` prevents reserved blocks/sessions/assignments from entering unmetered training, validation or calibration, in addition to existing reservations.

No external service or credential is required to use the local collector/API or evaluate cached data. Census authentication remains the one failed credential check; no Socrata key is requested. Official ACS/TIGER and City endpoints are free/public for acquisition. Further material gaps are reviewed direct unmetered counts on independent blocks and sessions, human bay checks for sensor validity/identity, verified time-dependent curb rules/capacity, and historically available workplace/business/event features for the new regions. No purchase, outreach, deployment or citywide accuracy claim occurred.
