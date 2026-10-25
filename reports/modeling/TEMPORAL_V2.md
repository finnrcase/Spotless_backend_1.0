# Temporal v2: fixed-target legacy benchmark

All numeric results below concern partial metered sensor panels in Westwood. The August 25–31 test was already inspected before this experiment. It is a legacy benchmark, not an untouched test. No unmetered accuracy or citywide accuracy is validated. The 15-minute label policy and exact evaluation rows are unchanged.

Selection uses pooled chronological validation squared error (RMSE below), never legacy-test R². The northern geographic holdout is never used for tuning. Its validation score is temporal validation within the southern training geography, not a measured unseen-block validation score.

| Evaluation | Change | Validation RMSE | Legacy R² | Legacy RMSE | Legacy MAE | n / blocks | Label coverage |
|---|---|---:|---:|---:|---:|---:|---:|
| future_time_known | baseline_time_week | 0.3064 | 0.1010 | 0.3121 | 0.2563 | 6421 / 23 | 30.1% |
| future_time_known | baseline_pooled | 0.3051 | 0.1062 | 0.3112 | 0.2586 | 6421 / 23 | 30.1% |
| future_time_known | baseline_persistence | 0.3930 | -0.4598 | 0.3978 | 0.3100 | 6421 / 23 | 30.1% |
| future_time_known | frozen_v1_boosted | — | 0.1731 | 0.2994 | 0.2447 | 6421 / 23 | 30.1% |
| future_time_known | rmse_original_grid | 0.2916 | 0.1731 | 0.2994 | 0.2447 | 6421 / 23 | 30.1% |
| future_time_known | pooled_face_patterns | 0.3050 | 0.1087 | 0.3108 | 0.2551 | 6421 / 23 | 30.1% |
| future_time_known | causal_temporal | 0.2798 | 0.2279 | 0.2893 | 0.2343 | 6421 / 23 | 30.1% |
| future_time_known | consecutive_history | 0.2783 | 0.2364 | 0.2877 | 0.2317 | 6421 / 23 | 30.1% |
| future_time_known | broader_tuning | 0.2777 | 0.2397 | 0.2870 | 0.2309 | 6421 / 23 | 30.1% |
| future_time_known | asof_context | 0.2778 | 0.2423 | 0.2866 | 0.2307 | 6421 / 23 | 30.1% |
| future_time_known | without_housing | 0.2778 | 0.2416 | 0.2867 | 0.2307 | 6421 / 23 | 30.1% |
| future_time_known | without_jobs | 0.2779 | 0.2435 | 0.2863 | 0.2303 | 6421 / 23 | 30.1% |
| unseen_block | baseline_time_week | 0.2994 | -0.0301 | 0.3459 | 0.2936 | 3705 / 5 | 15.9% |
| future_time_unseen | baseline_time_week | 0.2994 | -0.0901 | 0.3632 | 0.3109 | 478 / 3 | 17.9% |
| unseen_block | baseline_pooled | 0.2994 | -0.0301 | 0.3459 | 0.2936 | 3705 / 5 | 15.9% |
| future_time_unseen | baseline_pooled | 0.2994 | -0.0901 | 0.3632 | 0.3109 | 478 / 3 | 17.9% |
| unseen_block | baseline_persistence | 0.2994 | -0.0301 | 0.3459 | 0.2936 | 3705 / 5 | 15.9% |
| future_time_unseen | baseline_persistence | 0.2994 | -0.0901 | 0.3632 | 0.3109 | 478 / 3 | 17.9% |
| unseen_block | frozen_v1_boosted | — | 0.0810 | 0.3267 | 0.2713 | 3705 / 5 | 15.9% |
| future_time_unseen | frozen_v1_boosted | — | -0.0612 | 0.3583 | 0.3071 | 478 / 3 | 17.9% |
| unseen_block | rmse_original_grid | 0.2876 | 0.0810 | 0.3267 | 0.2713 | 3705 / 5 | 15.9% |
| future_time_unseen | rmse_original_grid | 0.2876 | -0.0612 | 0.3583 | 0.3071 | 478 / 3 | 17.9% |
| unseen_block | pooled_face_patterns | 0.3181 | -0.0375 | 0.3471 | 0.2943 | 3705 / 5 | 15.9% |
| future_time_unseen | pooled_face_patterns | 0.3181 | -0.0901 | 0.3632 | 0.3109 | 478 / 3 | 17.9% |
| unseen_block | causal_temporal | 0.2876 | 0.0808 | 0.3267 | 0.2712 | 3705 / 5 | 15.9% |
| future_time_unseen | causal_temporal | 0.2876 | -0.0632 | 0.3587 | 0.3072 | 478 / 3 | 17.9% |
| unseen_block | consecutive_history | 0.2870 | 0.0788 | 0.3271 | 0.2717 | 3705 / 5 | 15.9% |
| future_time_unseen | consecutive_history | 0.2870 | -0.0773 | 0.3610 | 0.3096 | 478 / 3 | 17.9% |
| unseen_block | broader_tuning | 0.2863 | 0.0742 | 0.3279 | 0.2726 | 3705 / 5 | 15.9% |
| future_time_unseen | broader_tuning | 0.2863 | -0.0734 | 0.3604 | 0.3105 | 478 / 3 | 17.9% |
| unseen_block | asof_context | 0.2681 | -0.0372 | 0.3471 | 0.2777 | 3705 / 5 | 15.9% |
| future_time_unseen | asof_context | 0.2681 | -0.2788 | 0.3934 | 0.3267 | 478 / 3 | 17.9% |
| unseen_block | without_housing | 0.2696 | 0.0393 | 0.3340 | 0.2741 | 3705 / 5 | 15.9% |
| future_time_unseen | without_housing | 0.2696 | -0.3183 | 0.3994 | 0.3280 | 478 / 3 | 17.9% |
| unseen_block | without_jobs | 0.2686 | -0.0619 | 0.3512 | 0.2803 | 3705 / 5 | 15.9% |
| future_time_unseen | without_jobs | 0.2686 | -0.3072 | 0.3977 | 0.3296 | 478 / 3 | 17.9% |

All five horizons, count heads, probability reliability bins, paired block/day bootstrap intervals, fixed-row hashes and candidate metrics are in the companion CSV/JSON. Bootstrap intervals are conditional on the uncertain sensor labels. They do not measure sensor accuracy.

The new September 21–30 archive holdout remains unopened and is not yet published in the checked official catalog. Lock all choices before its first evaluation. November 7–14 manual sessions and entirely new blocks are reserved prospectively, with no observations yet.

Remaining gaps: no independent sensor truth, no verified reporting heartbeat/SLA or historical sensor relocation map, no unmetered occupancy labels, no historically complete legal curb supply/sign rules, no pre-issue business/event versions. Housing/vehicles/employment are demand predictors only. Models are saved separately and are not automatically promoted into the app.

## Known blocks across horizons

Lowest validation RMSE across the declared comparisons; no legacy metric selects the row. Whole-block intervals resample all days of each physical block together. Few blocks and neighboring-block dependence still limit interpretation.

| Minutes | Validation-selected comparison | Validation RMSE | V1 legacy R² | Selected legacy R² | Selected legacy MAE | n / blocks | Paired ΔR² 95% whole-block interval |
|---:|---|---:|---:|---:|---:|---:|---|
| 0 | asof_context | 0.2577 | 0.2615 | 0.3536 | 0.2122 | 6428 / 23 | [0.067, 0.119] |
| 15 | without_jobs | 0.2747 | 0.1880 | 0.2632 | 0.2275 | 6425 / 23 | [0.049, 0.107] |
| 30 | without_jobs | 0.2774 | 0.1749 | 0.2472 | 0.2296 | 6423 / 23 | [0.045, 0.110] |
| 60 | broader_tuning | 0.2777 | 0.1731 | 0.2397 | 0.2309 | 6421 / 23 | [0.038, 0.107] |
| 120 | without_housing | 0.2777 | 0.1531 | 0.2336 | 0.2323 | 6414 / 23 | [0.055, 0.124] |

## Changes and evidence gaps

| Variant | Implemented change | Remaining gap |
|---|---|---|
| rmse_original_grid | Original features/grid; select on squared error | Sparse histories and uncertain labels |
| pooled_face_patterns | Training-only face/hour/day/week-hour shrinkage | Few repeated days per block |
| causal_temporal | Day/week lags, rolling trends, age and quality, expanding training-only patterns | Event delivery assumed immediate |
| consecutive_history | June and July added with the same candidate grid | Reporting roster churn; historical mapping unverified |
| broader_tuning | Wider Ridge and boosted complexity/learning/regularization settings | Two validation origins; selection uncertainty |
| asof_context | Housing, vehicle ownership, employment with publication gates | No verified legal supply or historical business/events |
| without_housing / without_jobs | Demand-family ablations | Demand predictors do not supply missing occupancy truth |

All test metrics are conditional on the fixed 15-minute label policy. The pure unseen-block axis overlaps historical training dates and is retrospective geographic transfer, not future-time validation. The future/unseen axis tests both together. Geographic tuning uses chronological folds inside the training geography; independent unseen-block validation remains unavailable.

**Sensor availability limitation:** histories are causal by event time assuming immediate delivery. Monthly archive publication lags two months; actual historical live-feed delivery was not recorded. These benchmarks do not validate an archive-only operational pipeline.

## Complete-panel count at 60 minutes

| Axis | Version | Validation RMSE | Legacy R² | Legacy MAE | n / blocks | Label coverage |
|---|---|---:|---:|---:|---:|---:|
| future_time_known | frozen_v1_boosted | — | 0.2555 | 0.5195 | 838 / 17 | 3.9% |
| future_time_known | asof_context_auxiliary | 0.5730 | 0.2790 | 0.5039 | 838 / 17 | 3.9% |
| unseen_block | frozen_v1_boosted | — | 0.5593 | 0.7337 | 179 / 5 | 0.8% |
| unseen_block | asof_context_auxiliary | 0.5525 | 0.4522 | 0.7855 | 179 / 5 | 0.8% |
| future_time_unseen | frozen_v1_boosted | — | -0.7613 | 0.8942 | 39 / 2 | 1.5% |
| future_time_unseen | asof_context_auxiliary | 0.5525 | -1.0612 | 0.9952 | 39 / 2 | 1.5% |

## Complete-panel vacancy probability at 60 minutes

This binary target is at least one monitored bay vacant, not at least one legally suitable full-curb space. Calibration is fitted separately; reliability bins and sample sizes are in temporal_v2_results.json.

| Axis | Version | Validation Brier | Legacy Brier | ECE | n / blocks | Label coverage |
|---|---|---:|---:|---:|---:|---:|
| future_time_known | frozen_v1_boosted | — | 0.2111 | 0.0370 | 838 / 17 | 3.9% |
| future_time_known | asof_context_auxiliary | 0.1857 | 0.2025 | 0.0373 | 838 / 17 | 3.9% |
| unseen_block | frozen_v1_boosted | — | 0.1847 | 0.1268 | 179 / 5 | 0.8% |
| unseen_block | asof_context_auxiliary | 0.1774 | 0.2247 | 0.2277 | 179 / 5 | 0.8% |
| future_time_unseen | frozen_v1_boosted | — | 0.3181 | 0.3882 | 39 / 2 | 1.5% |
| future_time_unseen | asof_context_auxiliary | 0.1774 | 0.3289 | 0.3917 | 39 / 2 | 1.5% |

## Unmetered and next observations

Unmetered held-out n = 0; R², MAE, count accuracy and suitable-space calibration are unavailable. Metered training benefit on unmetered observations remains untested. The existing unmetered-only versus mixed workflow is preserved.

Start the eight-count development batch using the field-route button, export/import and review it. Add independent metered bay checks to investigate sensor validity. Keep whole reserved blocks and November 7–14 sessions untouched. Wait for the reserved September archive, then lock the model before its first evaluation. No purchase, key or public deployment is needed.
