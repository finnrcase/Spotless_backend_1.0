# Census and regional coverage v4

The 2023 ACS static tables now cover all 2,498 Los Angeles County tracts. Existing 53-tract estimate/MOE cells and 964 Westwood vehicle-ratio pairs match exactly. No previously missing Westwood vehicle ratio was filled. All source estimate/MOE columns, sentinel codes, GEOIDs, release dates and raw hashes remain available locally. The authenticated one-tract Census request failed (invalid-key HTML with HTTP 200); cached official public files supplied this experiment.

Additional features are a lower bound on vehicles per household (four represents the 4+ category) and the one-person-household fraction. They do not duplicate the existing no-vehicle fraction or housing density. Derived ratio MOEs stay null without covariance; source MOEs are preserved. These are 2019–2023 contextual estimates, not occupancy truth.

## Rolling validation

60-minute horizon, Aug9/Aug13 origins, three-day windows, 180-minute embargo, fixed ExtraTrees complexity. All variants and baselines use identical target rows. Known-block rows are chronological validation of static transferable models; temporal-v2 own-history forecasting remains a separate approach. Neighborhood holdouts exclude both sides of all physical blocks in the held-out region. Select regression heads on geographic/time validation MSE and the binary head separately on Brier.

| Validation axis | Feature variant | R² | MAE | RMSE | n / blocks |
|---|---|---:|---:|---:|---:|
| known_blocks | calendar | 0.0632 | 0.2799 | 0.3285 | 7269 / 32 |
| known_blocks | existing_census | 0.1889 | 0.2556 | 0.3057 | 7269 / 32 |
| known_blocks | additional_census | 0.1975 | 0.2535 | 0.3041 | 7269 / 32 |
| known_blocks | pooled_mean | -0.0028 | 0.2942 | 0.3399 | 7269 / 32 |
| known_blocks | weekhour | 0.0581 | 0.2797 | 0.3294 | 7269 / 32 |
| unseen_neighborhood | calendar | -0.1069 | 0.3085 | 0.3571 | 7269 / 32 |
| unseen_neighborhood | existing_census | -0.0244 | 0.2983 | 0.3435 | 7269 / 32 |
| unseen_neighborhood | additional_census | -0.0294 | 0.2991 | 0.3444 | 7269 / 32 |
| unseen_neighborhood | pooled_mean | -0.1046 | 0.3116 | 0.3567 | 7269 / 32 |
| unseen_neighborhood | weekhour | -0.1056 | 0.3082 | 0.3569 | 7269 / 32 |

The new variables slightly improve known-block chronological rate validation but worsen unseen-neighborhood rate validation. The selected rate variant remains **existing_census**. Added variables are selected for count and binary heads separately; they are experimental and not automatically activated.

## Legacy diagnostics

These are previously inspected periods, never fresh untouched tests. Original Westwood unseen-block rows match v1/v2 exactly (3,705 pure geographic and 478 future/geographic rate labels). The known-block comparison below uses the same 5,274 South development labels for each frozen version; it is a subset of the prior 6,421-row all-known-block benchmark. Frozen v2 was trained on a different broader known-block population, so this is a model-version comparison, not a controlled Census-only ablation. Complete controlled ablations, count metrics, calibration bins and block-bootstrap intervals are in coverage_v4_results.json / coverage_v4_experiments.csv.

| Axis | Version/variant | R² | MAE | n / blocks | Rate coverage |
|---|---|---:|---:|---:|---:|
| future_time_known | frozen_v2_broader_tuning | 0.2642 | 0.2195 | 5274 / 17 | same paired rows |
| future_time_known | frozen_v1_boosted | 0.1983 | 0.2336 | 5274 / 17 | same paired rows |
| future_time_known | existing_census | 0.1516 | 0.2439 | 5274 / 17 | 32.9% |
| future_time_known | additional_census | 0.1521 | 0.2425 | 5274 / 17 | 32.9% |
| future_time_known | weekhour | 0.1203 | 0.2560 | 5274 / 17 | 32.9% |
| unseen_block | frozen_v2_asof_context | -0.0372 | 0.2777 | 3705 / 5 | same paired rows |
| unseen_block | frozen_v1_boosted | 0.0810 | 0.2713 | 3705 / 5 | same paired rows |
| unseen_block | existing_census | -0.0224 | 0.2976 | 3705 / 5 | 15.9% |
| unseen_block | additional_census | 0.0519 | 0.2860 | 3705 / 5 | 15.9% |
| unseen_block | weekhour | 0.0759 | 0.2806 | 3705 / 5 | 15.9% |
| future_time_unseen | frozen_v2_asof_context | -0.2788 | 0.3267 | 478 / 3 | same paired rows |
| future_time_unseen | frozen_v1_boosted | -0.0612 | 0.3071 | 478 / 3 | same paired rows |
| future_time_unseen | existing_census | 0.0495 | 0.2962 | 478 / 3 | 17.9% |
| future_time_unseen | additional_census | 0.0377 | 0.2984 | 478 / 3 | 17.9% |
| future_time_unseen | weekhour | 0.0222 | 0.2989 | 478 / 3 | 17.9% |
| future_time_Downtown | existing_census | 0.0860 | 0.2641 | 1655 / 8 | 20.7% |
| future_time_Downtown | additional_census | 0.0956 | 0.2626 | 1655 / 8 | 20.7% |
| future_time_Downtown | weekhour | -0.1588 | 0.2969 | 1655 / 8 | 20.7% |
| future_time_Hollywood | existing_census | 0.0965 | 0.2937 | 1653 / 7 | 27.5% |
| future_time_Hollywood | additional_census | 0.1150 | 0.2905 | 1653 / 7 | 27.5% |
| future_time_Hollywood | weekhour | -0.0943 | 0.3303 | 1653 / 7 | 27.5% |

Do not replace the known-block temporal model with these static models: consult the paired scores above. The geographic selection result is still negative on neighborhood validation. Positive Downtown/Hollywood future scores use previously observed blocks, and do not validate transfer to other streets.

| Axis | Available-count R² / MAE | Binary Brier / ECE | n / blocks | Complete-point coverage |
|---|---:|---:|---:|---:|
| future_time_known | 0.2756 / 0.5323 | 0.1930 / 0.0353 | 654 / 12 | 4.1% |
| unseen_block | 0.3901 / 0.7646 | 0.1829 / 0.1480 | 179 / 5 | 0.8% |
| future_time_unseen | -0.2421 / 0.7747 | 0.2461 / 0.2477 | 39 / 2 | 1.5% |
| future_time_Downtown | 0.1322 / 0.7150 | 0.1567 / 0.0388 | 85 / 6 | 1.1% |
| future_time_Hollywood | 0.1289 / 0.4661 | 0.2164 / 0.0408 | 583 / 6 | 9.7% |

Binary probabilities refer only to at least one vacant sensor-panel bay, not legal/suitable curb space. Platt calibration used Aug17–21 development rows. Geographic calibration transfer remains unvalidated; 39 future/unseen points on two blocks are particularly weak evidence. Whole-block bootstrap intervals condition on sparse, selected sensor labels and do not capture sensor error, cross-block dependence or mapping uncertainty.

## Coverage and gaps

Eight physical blocks each in Downtown and Hollywood were selected in fixed hash order from discovery-reporting sensors, without occupancy values/errors. August has supported rate bins on eight Downtown and seven Hollywood blocks; complete city street faces remain in the collector even when no label exists. No occupancy archive was downloaded again; cached Sep2025 and Jun–Aug2026 files were filtered locally. Full 16-block Census joins have no missing tracts/household features. This is limited, purposive metered coverage, not a representative LA sample.

Only 13.59% of expected new-region August sensor-time remains known under the unchanged 15-minute expiry. Reaffirmations comprise about 0.36% of comparable August Downtown states and 0.042% in Hollywood. Long silences/UNKNOWN remain uncertain. No official heartbeat/outage SLA or reviewed independent bay observations establishes a better expiry; no rule changed for R². Current location checks reconcile 4,002 Downtown and 1,511 Hollywood object IDs, explicitly excluding SENSOR_STATUS values. 150/38 respectively lie over 35m from the nearest meter point; 363/115 nearest matches are ambiguous within 3m. These flags do not establish faults, identity or historical installation/move dates. Historical reporting-ID counts changed; current map IDs/positions do not resolve lineage.

The Census joins are available by their 2024-12-12 public release, but street/meter assignments still use the October 2026 inventory retrospectively. Current restrictions, legal capacity, business operating hours, event information vintages and broader workplace joins remain incomplete; this task does not fabricate them. Numeric live predictions and suitable-space probabilities remain unsupported where the existing model/rules do not support them. All earlier prospective archive/manual reservations remain untouched.

**Unmetered validation n = 0.** R², count MAE, probability calibration and the benefit of mixed metered/unmetered training are unavailable until reviewed direct counts exist. The collector now has 2,002 faces and 32 optional regional planned visits; planned visits are never labels. Start with the existing eight-count Westwood batch. See docs/coverage_v4.md for exact commands, field dates and remaining actions.
