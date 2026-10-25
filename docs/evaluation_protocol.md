# Evaluation commitments

Confirmed project decisions are machine-readable in `config/project_decisions.json`. Geographic scope is the City of Los Angeles. The initial pilot is Westwood/UCLA and does not validate other neighborhoods. Free/public data comes first; paid data may be investigated later for demonstrable value, with no purchases authorized.

**Unmetered parking is a core target.** The executable [unmetered comparison](unmetered_modeling.md) requires direct reviewed labels, demand/supply/restriction predictors, and unmetered-only versus compatible mixed training on identical unmetered test observations. Additional datasets remain predictors. Whether metered training improves unmetered performance must be measured rather than assumed. Its later unseen-block test includes temporal shift and is explicitly labelled that way.

## Two distinct generalization questions

**Future-time:** train on earlier label windows; evaluate later prediction issue times after an explicit embargo (default 60 minutes, increase to cover the longest label/feature overlap). Use previously observed physical blocks for this primary test so that time and geography are not conflated. Keep validation and final test windows separate; freeze the final test before model selection or calibration. Every feature must be available by prediction issue time.

**Unseen-block:** hold out complete physical blocks, including both sides and all repeat observations. No block ID may occur in training. Report this as spatial generalization, separately from future-time performance; it does not independently establish future-time performance. Avoid overlapping context buffers across splits or additionally hold out buffered neighborhoods. A later future-time × unseen-block test can be added and named explicitly.

No random row split across repeated visits to the same face. Physical IDs come from the street inventory and join both sides; use `segment_id` as the initial `block_id`, with topology review for real-world blocks spanning multiple source segments. Preserve a split manifest and source snapshot hashes. Never move difficult examples out of a test set after seeing performance.

## Targets and metrics

Report metered and unmetered results **separately**, with mixed and unknown faces separate as well. No pooled score substitutes for either result. Show sample counts, distinct blocks, observation dates, geography, evidence quality, missing labels and prediction/abstention coverage.

* Occupancy-rate regression: `occupied / surveyed_capacity` only for a complete, reconciled survey with meaningful capacity. Rates based on estimated vehicle positions are derived estimates and must be reported separately from marked/measured capacity, with sensitivity to the denominator. Sensor-only rates retain their inference/freshness policy. Do not relabel partial observations as full-block occupancy.
* Count regression: occupied count and/or suitable available count, specifying which. Report **held-out test R², MAE and RMSE** in target units. Compare against training-only global mean, time-of-week mean and face mean with global fallback on identical paired test rows. Report prediction coverage so abstentions cannot invisibly improve headline scores. Keep negative R². R² is unavailable for a constant target or fewer than two paired samples; do not replace that with zero or one. [R² reference](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.r2_score.html).
* Finding a space: binary target `vacant_legal >= 1` only for a complete count with checked rules, recorded duration and permit/vehicle class. This is the observed chance of at least one suitable vacant position at the snapshot; it does not establish availability at a later arrival or a survival probability throughout a stay. Report **Brier score, log loss and a reliability table/plot**, bin counts, event prevalence and prediction coverage. Include a training-prevalence baseline. Expected calibration error is descriptive and depends on bins; Brier and log loss are not pure calibration measures. Fit any calibrator on training/validation data, never the final test. [Calibration reference](https://scikit-learn.org/stable/modules/calibration.html).

Present uncertainty using block/day resampling once there are sufficient independent observations; repeated snapshots are not independent blocks. Small-sample results are exploratory regardless of point estimates. Explain differences between sensor evidence, field counts, estimated capacity and reviewed labels rather than averaging their confidence away.

**No fixed R² target applies. Earlier rough conversation ranges were speculative, not measured benchmarks or acceptance criteria.** Never choose splits to reach a score or suppress negative/undefined results. Citywide accuracy requires evidence across the claimed citywide domain; meter-only data and a small Westwood sample cannot establish it.

## Executable reporting

`la-parking evaluate` consumes two CSV/Parquet tables. Each row must have:

```
observation_id, block_id, block_face_id, parking_type,
observed_at_utc, window_end_utc, prediction_issued_at_utc,
feature_available_at_utc
```

All times must already be timezone-aware. `feature_available_at_utc` is the maximum availability timestamp across every feature used, not a nominal dataset date. Optional target columns are `occupancy_rate`, `occupied_count`, `available_count` and `at_least_one`; corresponding model predictions are `pred_<target>`. Missing predictions are explicit abstentions. Predictions are supplied by a separately trained model; this command does not manufacture labels, tune a model or produce predictions.

```powershell
.\.venv\Scripts\la-parking.exe evaluate --train data\evaluation\train.csv --test data\evaluation\future.csv --axis future_time --output reports\evaluation_future.json
.\.venv\Scripts\la-parking.exe evaluate --train data\evaluation\spatial_train.csv --test data\evaluation\unseen_blocks.csv --axis unseen_block --output reports\evaluation_unseen_blocks.json
```

Outputs include separate parking-type regression metrics and baselines, probability scores and reliability bins, support counts and adjacent Markdown tables. Leakage checks reject observation overlap, naive times, future feature access and the applicable temporal/block overlap. Data lineage, feature construction, tuning/calibration splits and all target-quality review still need independent audit; a score file alone does not certify those.

There are currently no reviewed unmetered training/test labels. The executed sensor-panel pipeline now has trained models and retrospective metered-panel metrics in [results_report.md](../reports/modeling/results_report.md); these do not establish true suitable-space calibration or unmetered performance. Numeric fixtures in automated tests remain isolated tests of formulas, not performance evidence. See [model_card.md](model_card.md) for the exact label, missingness and historical-vintage limitations.
