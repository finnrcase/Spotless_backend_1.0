# Time-specific prediction: measured results

This run trains and evaluates metered **sensor-panel proxies**, not total or legally eligible curb parking. All user-facing numerical suitable-space predictions abstain.

Geography: 55 city faces have experimental panel labels; 162,575 have no occupancy labels. No verified unmetered labels exist.

The final chronological test is August 25–31, 2026. Model parameters use earlier rolling origins, with calibration August 18–23 and a gap before the final test. The primary unseen-area experiment withholds the north pilot area plus a 150 m training buffer at overlapping historical periods, so it measures spatial generalization, not prospective forecasting. The combined future/unseen-area experiment is separate.

| Test | Horizon | Model | Proxy rate R² | MAE | Labeled test rows | Target coverage |
|---|---:|---|---:|---:|---:|---:|
| future_time | 0 | time_week | 0.102 | 0.256 | 6428 | 0.299 |
| future_time | 0 | boosted | 0.262 | 0.232 | 6428 | 0.299 |
| future_time | 15 | time_week | 0.102 | 0.256 | 6425 | 0.300 |
| future_time | 15 | boosted | 0.188 | 0.243 | 6425 | 0.300 |
| future_time | 30 | time_week | 0.101 | 0.256 | 6423 | 0.300 |
| future_time | 30 | boosted | 0.175 | 0.244 | 6423 | 0.300 |
| future_time | 60 | time_week | 0.101 | 0.256 | 6421 | 0.301 |
| future_time | 60 | boosted | 0.173 | 0.245 | 6421 | 0.301 |
| future_time | 120 | time_week | 0.101 | 0.256 | 6414 | 0.302 |
| future_time | 120 | boosted | 0.153 | 0.247 | 6414 | 0.302 |
| unseen_area | 0 | time_week | -0.030 | 0.294 | 3721 | 0.160 |
| unseen_area | 0 | boosted | 0.077 | 0.272 | 3721 | 0.160 |
| unseen_area | 15 | time_week | -0.030 | 0.293 | 3714 | 0.160 |
| unseen_area | 15 | boosted | 0.082 | 0.271 | 3714 | 0.160 |
| unseen_area | 30 | time_week | -0.030 | 0.293 | 3712 | 0.160 |
| unseen_area | 30 | boosted | 0.084 | 0.271 | 3712 | 0.160 |
| unseen_area | 60 | time_week | -0.030 | 0.294 | 3705 | 0.159 |
| unseen_area | 60 | boosted | 0.081 | 0.271 | 3705 | 0.159 |
| unseen_area | 120 | time_week | -0.030 | 0.293 | 3701 | 0.159 |
| unseen_area | 120 | boosted | 0.083 | 0.271 | 3701 | 0.159 |
| future_unseen_area | 0 | time_week | -0.090 | 0.311 | 479 | 0.178 |
| future_unseen_area | 0 | boosted | -0.084 | 0.309 | 479 | 0.178 |
| future_unseen_area | 15 | time_week | -0.090 | 0.311 | 478 | 0.178 |
| future_unseen_area | 15 | boosted | -0.065 | 0.308 | 478 | 0.178 |
| future_unseen_area | 30 | time_week | -0.090 | 0.311 | 478 | 0.179 |
| future_unseen_area | 30 | boosted | -0.068 | 0.308 | 478 | 0.179 |
| future_unseen_area | 60 | time_week | -0.090 | 0.311 | 478 | 0.179 |
| future_unseen_area | 60 | boosted | -0.061 | 0.307 | 478 | 0.179 |
| future_unseen_area | 120 | time_week | -0.090 | 0.311 | 478 | 0.180 |
| future_unseen_area | 120 | boosted | -0.057 | 0.307 | 478 | 0.180 |

MAE is in occupancy-fraction units. Target coverage is the fraction of candidate face-times with sufficient reconstructed sensor-time; scores are conditional on those labels. Unknown intervals are not vacant intervals. The 0.50 unmetered R² aspiration is not a target achieved or evaluated by this run.

| Test | Lead | Complete panel N | Panel count R² | Panel count MAE | Panel vacancy Brier | Log loss | Regression range coverage | Mean range width |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| future_time | 0 | 839 | 0.668 | 0.271 | 0.084 | 0.273 | 0.908 | 1.016 |
| future_time | 15 | 839 | 0.298 | 0.505 | 0.204 | 0.596 | 0.907 | 1.229 |
| future_time | 30 | 838 | 0.260 | 0.519 | 0.210 | 0.609 | 0.909 | 1.251 |
| future_time | 60 | 838 | 0.256 | 0.519 | 0.211 | 0.612 | 0.907 | 1.237 |
| future_time | 120 | 836 | 0.225 | 0.529 | 0.213 | 0.617 | 0.900 | 1.250 |
| unseen_area | 0 | 180 | 0.569 | 0.720 | 0.184 | 0.541 | 0.711 | 1.756 |
| unseen_area | 15 | 180 | 0.547 | 0.723 | 0.182 | 0.534 | 0.728 | 1.710 |
| unseen_area | 30 | 179 | 0.511 | 0.755 | 0.189 | 0.554 | 0.709 | 1.806 |
| unseen_area | 60 | 179 | 0.559 | 0.734 | 0.185 | 0.541 | 0.682 | 1.704 |
| unseen_area | 120 | 179 | 0.591 | 0.681 | 0.191 | 0.557 | 0.732 | 1.665 |
| future_unseen_area | 0 | 39 | -0.747 | 0.907 | 0.306 | 0.817 | 0.564 | 1.524 |
| future_unseen_area | 15 | 39 | -0.726 | 0.897 | 0.299 | 0.799 | 0.615 | 1.468 |
| future_unseen_area | 30 | 39 | -0.677 | 0.887 | 0.306 | 0.819 | 0.615 | 1.570 |
| future_unseen_area | 60 | 39 | -0.761 | 0.894 | 0.318 | 0.850 | 0.564 | 1.469 |
| future_unseen_area | 120 | 39 | -0.639 | 0.867 | 0.285 | 0.783 | 0.538 | 1.498 |

Count labels require every member of the fixed sensor panel to be reconstructed as known at the target point. They are **not** full-block counts. The binary target is any vacant member of that panel, fit directly, without an independence assumption or conversion from expected occupancy. It is a derived sensor-state proxy, not a verified suitable-space outcome.

Prediction ranges use calibration-period absolute residuals (nominal 90%). Empirical coverage/width are reported; temporal dependence, missingness selection and domain shift mean nominal coverage is not guaranteed. Probability calibration uses separate calibration labels; reliability plots include bin counts in results.json.

## Feature-family ablations

| Test | Lead | Feature set | Rate R² | MAE |
|---|---:|---|---:|---:|
| future_time | 0 | calendar_only | 0.123 | 0.253 |
| future_time | 0 | no_neighbors | 0.264 | 0.231 |
| future_time | 0 | retrospective_context | 0.278 | 0.228 |
| unseen_area | 0 | calendar_only | 0.074 | 0.271 |
| unseen_area | 0 | no_neighbors | 0.074 | 0.271 |
| unseen_area | 0 | retrospective_context | 0.060 | 0.273 |
| future_time | 15 | calendar_only | 0.122 | 0.253 |
| future_time | 15 | no_neighbors | 0.192 | 0.242 |
| future_time | 15 | retrospective_context | 0.229 | 0.234 |
| unseen_area | 15 | calendar_only | 0.076 | 0.271 |
| unseen_area | 15 | no_neighbors | 0.076 | 0.271 |
| unseen_area | 15 | retrospective_context | 0.063 | 0.272 |
| future_time | 30 | calendar_only | 0.122 | 0.253 |
| future_time | 30 | no_neighbors | 0.177 | 0.244 |
| future_time | 30 | retrospective_context | 0.219 | 0.235 |
| unseen_area | 30 | calendar_only | 0.075 | 0.271 |
| unseen_area | 30 | no_neighbors | 0.075 | 0.271 |
| unseen_area | 30 | retrospective_context | 0.052 | 0.273 |
| future_time | 60 | calendar_only | 0.122 | 0.253 |
| future_time | 60 | no_neighbors | 0.172 | 0.245 |
| future_time | 60 | retrospective_context | 0.220 | 0.235 |
| unseen_area | 60 | calendar_only | 0.076 | 0.271 |
| unseen_area | 60 | no_neighbors | 0.076 | 0.271 |
| unseen_area | 60 | retrospective_context | 0.063 | 0.271 |
| future_time | 120 | calendar_only | 0.122 | 0.253 |
| future_time | 120 | no_neighbors | 0.153 | 0.247 |
| future_time | 120 | retrospective_context | 0.217 | 0.235 |
| unseen_area | 120 | calendar_only | 0.073 | 0.271 |
| unseen_area | 120 | no_neighbors | 0.073 | 0.271 |
| unseen_area | 120 | retrospective_context | 0.058 | 0.271 |

The retrospective context ablation uses October 2026 building/business/curb/meter snapshots. It is explicitly excluded from historically available feature claims. Housing/vehicles, fine-grained employment, opening hours, historical weather forecasts, reliable event attendance, complete restrictions, transit and closures remain unavailable or lack verified as-of joins. No zero-valued substitutes were used.

## Supported claims and limits

- Reproducible time-weighted sensor-panel reconstruction, causal recent-state features, trained models and held-out diagnostics are supported.
- Absolute performance on the reconstructed metered panel is conditional on freshness/coverage assumptions. It is not independently verified sensor accuracy.
- Sensor identity and block assignment use October 2026 meter/geometry snapshots, and historical ingestion times are absent. All experiments are retrospective; immediate event delivery is an explicit assumption.
- No unmetered/residential occupancy accuracy, legal duration suitability, total eligible capacity, or validated citywide accuracy is supported.
- Advanced transition/state-space models are deferred: the large unknown gaps and unverified event delivery do not yet establish reliable transitions that would resolve the demonstrated geographic transfer gap.
- Before numerical user predictions: verify historical/current mapping, inventory capacity and full-stay rules, collect random/repeated independent counts, validate sensor assumptions, improve missing source vintages, and repeat prospective time/area validation.

Artifacts: metrics.csv, results.json (strata/reliability), rolling_validation.json, ablations.json, label_manifest.json, feature_catalog.json, forecast_examples.jsonl and artifacts/models/*.joblib. No purchase or public deployment.

## Persistence-policy sensitivity

Same fixed model, common labelled final-test rows; changing the label reconstruction is not independent sensor validation.

| Horizon | Cap (min) | Paired N | Proxy rate R² | MAE |
|---|---:|---:|---:|---:|
| 0 | 5 | 1991 | -0.034 | 0.205 |
| 0 | 15 | 1991 | 0.130 | 0.207 |
| 0 | 60 | 1991 | 0.226 | 0.194 |
| 15 | 5 | 1990 | -0.031 | 0.204 |
| 15 | 15 | 1990 | 0.094 | 0.209 |
| 15 | 60 | 1990 | 0.183 | 0.198 |
| 30 | 5 | 1990 | -0.046 | 0.205 |
| 30 | 15 | 1990 | 0.083 | 0.209 |
| 30 | 60 | 1990 | 0.175 | 0.197 |
| 60 | 5 | 1990 | -0.056 | 0.206 |
| 60 | 15 | 1990 | 0.067 | 0.211 |
| 60 | 60 | 1990 | 0.151 | 0.201 |
| 120 | 5 | 1988 | -0.089 | 0.208 |
| 120 | 15 | 1988 | 0.033 | 0.215 |
| 120 | 60 | 1988 | 0.121 | 0.205 |
