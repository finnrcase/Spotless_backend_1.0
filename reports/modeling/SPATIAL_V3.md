# Spatial transfer v3

Selection uses joint rolling chronological and inner-geographic validation, holding both sides of complete development blocks out. North-area legacy outcomes were not used to select candidates. All targets and evaluation rows match v1/v2.

Primary 60-minute feature variant: **calendar** (selected on validation RMSE before legacy scoring).

| Axis | Variant | Target | Geo/time validation RMSE | Legacy R² | Legacy MAE | Brier | n / blocks | Coverage |
|---|---|---|---:|---:|---:|---:|---:|---:|
| unseen_block | calendar | occupancy_rate | 0.2955 | 0.0771 | 0.2713 | — | 3705 / 5 | 15.9% |
| future_time_unseen | calendar | occupancy_rate | 0.2955 | -0.0747 | 0.3076 | — | 478 / 3 | 17.9% |
| unseen_block | plus_neighbors | occupancy_rate | 0.2963 | 0.0938 | 0.2718 | — | 3705 / 5 | 15.9% |
| future_time_unseen | plus_neighbors | occupancy_rate | 0.2963 | -0.0600 | 0.3074 | — | 478 / 3 | 17.9% |
| unseen_block | plus_housing | occupancy_rate | 0.2980 | 0.0659 | 0.2706 | — | 3705 / 5 | 15.9% |
| future_time_unseen | plus_housing | occupancy_rate | 0.2980 | -0.1470 | 0.3132 | — | 478 / 3 | 17.9% |
| unseen_block | plus_workplaces | occupancy_rate | 0.2970 | 0.1264 | 0.2689 | — | 3705 / 5 | 15.9% |
| future_time_unseen | plus_workplaces | occupancy_rate | 0.2970 | -0.0340 | 0.3037 | — | 478 / 3 | 17.9% |
| unseen_block | plus_geometry | occupancy_rate | 0.2963 | 0.1071 | 0.2697 | — | 3705 / 5 | 15.9% |
| future_time_unseen | plus_geometry | occupancy_rate | 0.2963 | -0.0688 | 0.3066 | — | 478 / 3 | 17.9% |
| unseen_block | minus_neighbors | occupancy_rate | 0.2970 | 0.1129 | 0.2689 | — | 3705 / 5 | 15.9% |
| future_time_unseen | minus_neighbors | occupancy_rate | 0.2970 | -0.0631 | 0.3058 | — | 478 / 3 | 17.9% |
| unseen_block | minus_housing | occupancy_rate | 0.2973 | 0.1182 | 0.2712 | — | 3705 / 5 | 15.9% |
| future_time_unseen | minus_housing | occupancy_rate | 0.2973 | -0.0403 | 0.3050 | — | 478 / 3 | 17.9% |
| unseen_block | minus_workplaces | occupancy_rate | 0.2965 | 0.0694 | 0.2722 | — | 3705 / 5 | 15.9% |
| future_time_unseen | minus_workplaces | occupancy_rate | 0.2965 | -0.1262 | 0.3112 | — | 478 / 3 | 17.9% |
| unseen_block | calendar | available_count | 0.5677 | 0.4463 | 0.7634 | — | 179 / 5 | 0.8% |
| future_time_unseen | calendar | available_count | 0.5677 | -0.2576 | 0.7617 | — | 39 / 2 | 1.5% |
| unseen_block | calendar | any_panel_vacant | — | — | — | 0.1791 | 179 / 5 | 0.8% |
| future_time_unseen | calendar | any_panel_vacant | — | — | — | 0.3174 | 39 / 2 | 1.5% |

Known-block results remain in TEMPORAL_V2.md; this experiment adds a distinct transferable model without own-face histories or identity encodings. Whole-block bootstrap intervals, probability calibration bins and ablations are in spatial_v3_results.json. New October 25-31 archive and November 15-21 manual reservations remain unopened, alongside earlier holdouts.

All numeric measurements are experimental metered-panel proxies in Westwood. Unmetered held-out n = 0; R², MAE and suitable-space probability calibration remain unavailable. Event-time replay assumes immediate delivery. Pure geographic results overlap historical training dates; only future_time_unseen measures forward-time transfer. Geographic probability calibration is not independently validated on new blocks.

Geometry features use the later October map and are a retrospective exploratory tier. Current business accounts are prospective predictors only; actual activity/hours, complete legal supply, posted restrictions and historical event information remain unavailable. Unknown rules do not mean unrestricted. No model was automatically activated in the app.

## Fixed-row references

V2 selected features using chronological validation within the development geography. V3 uses geographic and chronological validation together, so validation scores are not directly interchangeable. No reference legacy score selected the new variant.

| Axis | Version | Target | R² | MAE | Brier | ECE | n |
|---|---|---|---:|---:|---:|---:|---:|
| unseen_block | v1 | occupancy_rate | 0.0810 | 0.2713 | — | — | 3705 |
| unseen_block | v2 validation-selected | occupancy_rate | -0.0372 | 0.2777 | — | — | 3705 |
| unseen_block | v3 validation-selected | occupancy_rate | 0.0771 | 0.2713 | — | — | 3705 |
| unseen_block | v1 | available_count | 0.5593 | 0.7337 | — | — | 179 |
| unseen_block | v2 | available_count | 0.4522 | 0.7855 | — | — | 179 |
| unseen_block | v3 validation-selected | available_count | 0.4463 | 0.7634 | — | — | 179 |
| unseen_block | v1 | any_panel_vacant | — | — | 0.1847 | 0.1268 | 179 |
| unseen_block | v2 | any_panel_vacant | — | — | 0.2247 | 0.2277 | 179 |
| unseen_block | v3 validation-selected | any_panel_vacant | — | — | 0.1791 | 0.1194 | 179 |
| future_time_unseen | v1 | occupancy_rate | -0.0612 | 0.3071 | — | — | 478 |
| future_time_unseen | v2 validation-selected | occupancy_rate | -0.2788 | 0.3267 | — | — | 478 |
| future_time_unseen | v3 validation-selected | occupancy_rate | -0.0747 | 0.3076 | — | — | 478 |
| future_time_unseen | v1 | available_count | -0.7613 | 0.8942 | — | — | 39 |
| future_time_unseen | v2 | available_count | -1.0612 | 0.9952 | — | — | 39 |
| future_time_unseen | v3 validation-selected | available_count | -0.2576 | 0.7617 | — | — | 39 |
| future_time_unseen | v1 | any_panel_vacant | — | — | 0.3181 | 0.3882 | 39 |
| future_time_unseen | v2 | any_panel_vacant | — | — | 0.3289 | 0.3917 | 39 |
| future_time_unseen | v3 validation-selected | any_panel_vacant | — | — | 0.3174 | 0.3693 | 39 |

## Interpretation

The added demand and geometry families did not improve joint geographic/time validation over the calendar model in this sample. V3 occupancy transfer recovered much of the v2 regression, but did not exceed v1 on the forward-time/new-block test; R² remains negative. Forward-time/new-block count error improved, but that test contains only 39 labels on two blocks and still has negative R². Probability reliability is weak in that tiny transferred sample. These results do not authorize numerical unmetered or citywide forecasts.

Useful completed joins: housing/vehicle predictors, vintage-consistent 2022 employment for September 2025, and later 2023 employment with retail, education, health, arts and food-sector counts. Current active-business counts remain prospective only. Source dates, partial workplace matches and geometry limitations remain explicit in spatial_v3_context.json.

Collection next: first eight unmetered development counts at 0/15/30/60 minutes; optional independently timestamped meter-bay checks on October 28. Preserve the reserved November 17/21 sessions and three whole new blocks for evaluation. No new occupancy labels have been collected.
