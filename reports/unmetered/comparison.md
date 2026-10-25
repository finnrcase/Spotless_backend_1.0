# Unmetered prediction comparison

Status: **awaiting_direct_unmetered_labels_and_frozen_splits**.

Unmetered streets are a core target. Demand, curb supply and time-dependent restrictions are predictors; only direct reviewed observations provide test occupancy labels.

No reviewed unmetered train/validation/test labels and as-of predictor table have been supplied. Existing metered proxy scores cannot answer this question.

## future_time

| Training / baseline | Target | Test N | R² | MAE | Brier |
|---|---|---:|---:|---:|---:|
| unmetered_mean | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_time_week | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_face_mean | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_persistence_with_mean_fallback | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_only | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_plus_metered | unavailable | 0 | unavailable | unavailable | unavailable |

## unseen_block

| Training / baseline | Target | Test N | R² | MAE | Brier |
|---|---|---:|---:|---:|---:|
| unmetered_mean | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_time_week | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_face_mean | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_persistence_with_mean_fallback | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_only | unavailable | 0 | unavailable | unavailable | unavailable |
| unmetered_plus_metered | unavailable | 0 | unavailable | unavailable | unavailable |

Transfer is not assumed beneficial. Inspect paired unmetered metric changes, uncertainty and coverage for each axis before choosing a training population. This experiment does not automatically publish a model or enable numerical unmetered service forecasts.

No fixed R² target. Earlier rough ranges were speculative, not measured benchmarks or acceptance criteria.
