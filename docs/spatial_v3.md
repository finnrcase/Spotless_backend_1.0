# Geographic validation, delivery records and field holdouts

The [spatial experiment table](../reports/modeling/SPATIAL_V3.md) compares 60-minute forecasts on exactly the existing targets and legacy rows. Known-block gains remain in [temporal v2](../reports/modeling/TEMPORAL_V2.md). The 15-minute expiry was not changed. Numeric results concern metered sensor panels in Westwood; full-curb suitability, unmetered accuracy and citywide accuracy remain unvalidated.

## What ran

Three geographic clusters of development blocks, with both curb sides held out together, crossed with August 9/13 chronological origins. Training has a three-hour embargo; held-out blocks cannot supply neighbor observations. No own-block history or block/face identity enters the transfer models. Ridge, boosted trees and Extra Trees are compared on validation squared error; count heads have their own squared-error selection and binary vacancy heads use Brier. Calibration uses later development-area observations; independently unseen-block calibration is unavailable.

Eight feature variants quantify housing, employment, neighbor and geometry contributions on identical validation rows. Geographic validation selected the calendar model. Added families did not improve this sample's validation score. Transfer occupancy R² recovered from v2's regression but did not beat v1 on the forward-time/new-block legacy test. Forward-time/new-block count MAE improved, but only 39 labels on two blocks are available and R² remains negative. Calibration is weak in that tiny transferred sample. All results, unfavorable cases, coverage, reliability bins and whole-block bootstrap intervals are retained. No model was automatically activated.

A 6.2 MB public 2022 employment file fills the September 2025 vintage gap. Its November 19, 2024 public release, file modification and creation dates were verified; 2023 values remain gated until their December 2025 release. Retail, education, healthcare, arts and food-sector employment are predictors, not occupancy truth. Unmatched Census blocks remain missing, not zero. Current active-business counts are stored for prospective use only. Actual activity/hours, historical event joins and sign-complete legal supply remain unavailable. Geometry uses the later October street map and is an exploratory retrospective tier.

Cached consecutive June–August history is reused without another monthly download. Sensor-roster churn and historical mapping uncertainty remain in the earlier acquisition audit. A fresh metadata probe still finds the public Code the Curb service unavailable; the sensor-map schema is verified but supplies no verified historical installation/change timeline. Program pages do not establish a working rules API.

## Reproduce and verify

From the project root using the existing locked environment:

```powershell
.\.venv\Scripts\python.exe scripts\spatial_experiment.py acquire
.\.venv\Scripts\python.exe scripts\spatial_experiment.py run
.\.venv\Scripts\python.exe scripts\spatial_experiment.py check
.\.venv\Scripts\la-parking.exe collector
.\.venv\Scripts\la-parking.exe field-route
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/collector_model.test.mjs tests/imagery_model.test.mjs
```

Completed runs refuse silent re-selection. `check` verifies unchanged legacy inputs, identical targets/rows, common feature-family validation populations, prediction bounds and saved-bundle inference. It freezes model hashes in `reports/modeling/spatial_v3_locked_models.json`. Models and datasets remain local and ignored by Git. The local map's `/api/model-evidence` endpoint and coverage notice expose the evidence limits without enabling experimental forecasts.

## Independent sensor checks and actual delivery

The official dictionary describes occupancy transaction time and last-known state. The pilot overwhelmingly alternates states; this supports change-driven reporting, but does not establish heartbeat cadence or whether silence is stable occupancy or outage. Repeated client polls are not sensor heartbeats. Current hardware descriptions do not certify the semantics or reliability of older archived records.

`scripts/capture_sensors.py` stores immutable raw snapshots, provider transaction times, actual first-seen/last-seen delivery times and poll failures separately. Repeated polls do not renew event age. UNKNOWN/conflicting states stay unknown. A failed poll does not prove an individual sensor outage.

The new October 25–31 archive period and November 15–21 manual period were reserved before tuning, alongside earlier reservations. The app refuses normal source polling during protected periods. Capture a blind snapshot explicitly:

```powershell
.\.venv\Scripts\python.exe scripts\capture_sensors.py poll --quarantine
.\.venv\Scripts\python.exe scripts\capture_sensors.py status
```

One real bounded poll succeeded: 3,866 source records are quarantined, with **zero parsed provider transactions** entering features. No reserved state values were inspected. After the reserved period ends, an explicit `release --poll-id <ID>` verifies the frozen model hashes and copies data to a separate locked-evaluation database. It refuses early release and never modifies the live feature database. Use the returned evaluation directory for independent comparisons; do not use evaluation outcomes for further model selection.

The phone collector now lists actual mapped bay IDs/positions. An optional state selection records its own timestamp and a separate identity check. It never fills the full-face counters or legal capacity. Unknown identity/visibility stays unknown. Imports require the bay to be uniquely mapped to the selected face and its timestamp inside the real survey. Bay observations require separate review. `capture_sensors.py compare --observations <parquet> --reviews <csv> --directory <evaluation directory>` expects review columns `observation_id,space_id,reviewed`; only reviewed, identity-confirmed human states are scored. It compares 5/15/60/180-minute policies on common observations and reports selection/coverage effects. No expiry is selected by R². Current independent reviewed bay n is zero, so accuracy remains null.

## Exact next collection steps

1. Start the local app with `.\.venv\Scripts\la-parking.exe serve`, open `/field-route`, and tap **Start smallest batch: 8 counts over 1 hour**. On October 27, inspect both sides of **S Levering Ave between W Roebling Ave and W Le Conte Ave** at noon/+15/+30/+60 minutes; second-side slots are four minutes later. Verify actual unmetered status, boundaries, public access, intended-stay rules and capacity basis. Record actual times, gaps and missing views. This tests collection quality; it is not enough to validate accuracy.
2. Export JSONL, then import with `.\.venv\Scripts\la-parking.exe observations <export.jsonl>` and review before training. IDs, pins, session and assignment are prefilled; do not transcribe coordinates. If collecting optional October 28 metered-bay checks, retain them for independent review after the October holdout ends.
3. Keep the November 17/21 morning/afternoon/evening sessions reserved. The route contains 60 planned evaluation visits across three new physical blocks and two previously observed blocks, with both sides retained. `config/field_holdouts.json` records the reservations, and unmetered training rejects reserved blocks/sessions in train, validation or calibration. Planned visits are not observations. These few Westwood blocks cannot validate citywide accuracy.

No paid service, external credential or public deployment is required. Optional Census/Socrata keys can help quotas. Remaining evidence needs are direct reviewed unmetered counts, independent meter checks, versioned full-stay rules/legal supply, verified historical sensor mappings/delivery, and pre-issue business/event versions.
