# Unmetered is a core prediction target

Unmetered street parking requires its own occupancy labels and held-out evaluation. Demand, curb supply, restrictions and prior observations can explain occupancy; business activity, payments, citations, signs and curb geometry cannot replace occupancy labels. `config/project_decisions.json` records this requirement; `config/unmetered_experiment.json` defines the initial comparison.

The actual manual observation store currently contains **zero records**. Consequently [the current comparison](../reports/unmetered/comparison.md) reports unavailable unmetered R², MAE and calibration. Whether metered training helps is **not evaluated**. The preserved [metered sensor-panel results](../reports/modeling/results_report.md) remain a separate auxiliary experiment, with no claimed unmetered accuracy. Its partial sensor panels are incompatible with full-face count/suitability labels and are rejected by this comparison.

## Ground truth and predictor preparation

Use the existing [phone collector](phone_collection.md) and randomized/repeat visit plan. Collect complete reconciled face counts, metered/unmetered identification, capacity basis, intended stay, vehicle/permit profile and the applicable restrictions. Preserve partial or uncertain observations for review; do not promote them automatically to training labels. Unmarked spaces require an explicit capacity estimate and review; record these as `estimated_positions`, separately from `marked_spaces`. A physical curb-length conversion is an estimate, not a verified capacity or occupancy label.

Import observations through the existing intake, then supply an independent review CSV with these columns:

```text
observation_id,counts_verified,location_verified,capacity_verified,rules_verified,reviewed_by,reviewed_at_utc
```

Each verified field is an explicit boolean. Review checks location/side, capacity denominator, count reconciliation and rules for the **entire recorded stay/profile**. A missing database sign is not a checked unrestricted curb. The reviewer timestamp must be aware and follow the survey. Intake acceptance and observer confidence alone are insufficient. `reviewed_labels()` derives occupancy rate (`occupied / surveyed_capacity`), available count (`vacant_legal`) and the binary event (`vacant_legal > 0`) only after those gates. It records `label_available_at_utc` as the latest survey, receipt or review time. These describe snapshot availability for the recorded stay/profile, not the probability a space stays empty throughout the stay.

Prepare a separate CSV/Parquet predictor table keyed by `observation_id`, including `prediction_issued_at_utc` and `feature_available_at_utc`. The latter is the **maximum actual availability time of every used feature**. Issue time must precede the target survey; feature availability must precede issue time. Retain per-source timestamps and source hashes for audit. Do not copy the target survey's capacity/counts into predictors or backdate a later context snapshot.

Predictor families include:

| Family | Candidate predictors | Required handling |
|---|---|---|
| Demand | Business density, effective openings, jobs/residential context, issued events/weather | Verify spatial joins, vintage and availability; current snapshots cannot explain old forecasts as if known then. |
| Curb supply | Independently established physical/eligible capacity, usable length, exclusions | Keep unknown values missing; separate measured supply from estimates. |
| Time-dependent restrictions | Minutes restricted during the stay, permit requirements, temporary closures | Evaluate the whole stay in Los Angeles time; distinguish unknown coverage from zero restrictions. |
| Observation history | Previous reviewed occupancy, observation age and coverage | Use only earlier available observations; exclude held-out block histories in unseen-block experiments. |
| Calendar/context | Cyclical local hour/day and forecast lead | Known calendar time is not evidence that parking is legally allowed. |

The manifest must declare demand, supply and restriction families. Each must contribute predictors or have an explicit `unavailable_families` explanation. Missing predictors may be imputed within training; missing targets are never imputed. Test feature missingness is reported. Supply/rule features are not occupancy targets.

```powershell
.\.venv\Scripts\la-parking.exe prepare-unmetered --reviews data\observations\reviews.csv --features data\modeling\unmetered_asof_features.parquet
```

This joins approved observations to the real City inventory's physical block IDs and independent predictors. Output defaults to ignored `data/modeling/unmetered_reviewed.parquet`, with a source-hash/rejection audit. It does not train or activate forecasts. `prepare()` also accepts explicit observation/inventory paths from Python. Historical/current restrictions and context are still incomplete; this command does not manufacture missing histories.

## Frozen comparison

Declare feature columns and frozen observation ID lists in a JSON manifest:

```json
{
  "features": ["business_density_300m", "physical_capacity", "restriction_minutes_during_stay"],
  "feature_families": {
    "demand": ["business_density_300m"],
    "curb_supply": ["physical_capacity"],
    "time_dependent_restrictions": ["restriction_minutes_during_stay"]
  },
  "splits": {
    "future_time": {"train_ids": [], "validation_ids": [], "calibration_ids": [], "test_ids": []},
    "unseen_block": {"train_ids": [], "validation_ids": [], "calibration_ids": [], "test_ids": []}
  }
}
```

This is a structural template; empty partitions cannot run. Populate it with actual reviewed observation IDs and freeze it before examining final outcomes. The first implementation requires one recorded duration/vehicle/permit stratum per run. Run separate strata instead of silently mixing eligibility targets. The experiment table retains that context and its review evidence. `label_evidence=direct_reviewed_full_face` and `label_reviewed=true` are attestations backed by the review audit, not switches for relabelling proxies.

Both evaluations use distinct train, unmetered validation, unmetered calibration and unmetered test partitions. Labels must be available, including completed review/receipt, at least 180 minutes before the next partition's earliest issue time. A later review cannot be backdated into earlier training. Future-time testing revisits observed unmetered physical blocks. Unseen-block testing excludes every test block from all development data, including opposite curbs and metered rows. This implementation's unseen-block test also occurs later: it measures future predictions on new blocks, with temporal shift included. It does not isolate a contemporaneous spatial effect. Keep this qualification when comparing it with the existing retrospective spatial sensor experiment.

Minimums (20 unmetered training rows, 10 each validation/calibration/test, three unseen test blocks) are execution safeguards, **not evidence of adequate statistical power**. Preserve randomized sampling and increase independent blocks/days; the planned collection assignments are not observed data. If constructing lag/neighbor predictors, audit their inputs against the split manifest. Aggregate timestamp checks cannot prove that a feature builder excluded every forbidden observation.

Each axis compares six strategies on the **identical complete unmetered test rows**:

1. Unmetered training mean/prevalence.
2. Unmetered local day-of-week/hour mean with global fallback.
3. Unmetered face mean with global fallback on new faces.
4. Persistence of a previous direct state within 15 minutes of issue time, with the unmetered training mean as an explicit fallback. Optional columns are `lagged_observed_occupancy`, `lagged_observed_available_count`, `lagged_observed_at_least_one` and `lag_age_minutes`; their availability must be included in the as-of timestamp audit. Coverage/fallback are reported. Own-block persistence is unavailable on unseen blocks and falls back rather than accessing held-out history.
5. Gradient boosting trained on unmetered observations only.
6. The same learner trained on unmetered plus compatible direct metered observations.

Mixed training tests positive auxiliary weights of 0.25 and 1.0; domain balancing makes the total metered weight that fraction of total unmetered weight. Metered rows cannot overwhelm the unmetered target through volume. Leaf count and weight selection use only unmetered validation MAE/Brier. Binary logistic calibration uses the separate unmetered calibration set when both classes exist; otherwise the report explicitly records no fitted calibration. All preprocessing fits training rows. No final test outcomes select parameters, weights or calibrators.

```powershell
.\.venv\Scripts\la-parking.exe compare-unmetered
.\.venv\Scripts\la-parking.exe compare-unmetered --table data\modeling\unmetered_reviewed.parquet --manifest data\modeling\unmetered_frozen_manifest.json --output reports\unmetered_new_holdout
```

The first command reports current readiness without inventing observations. The second fits/evaluates only with valid real inputs. Use separately named outputs for later experiments; an inspected final test is no longer untouched.

Reports retain held-out **R², MAE, RMSE**, Brier/log loss/ECE and reliability bins, prediction coverage, capacity-basis strata, test blocks/dates, missing features, training populations and validation selection history. Paired MAE/Brier reductions compare adding metered labels against unmetered-only training; block-bootstrap intervals expose uncertainty. Negative reductions, negative R² and undefined R² remain visible. A small or biased block sample can invalidate broader interpretations even when an interval is positive. Metered accuracy stays in its own report and cannot stand in for these unmetered scores.

This experiment does not save a production model or enable numerical unmetered forecasts. Any later promotion requires an explicit evidence review across the claimed geography, lead times and profiles. **No fixed R² target applies; earlier rough ranges were speculative, not measured benchmarks.** Neither metered data nor a small Westwood survey establishes validated citywide performance.
