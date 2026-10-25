# Model card: sensor-panel-v1

This is an auxiliary metered experiment. Unmetered parking remains a core target with a separate [direct-label training comparison](unmetered_modeling.md); this model does not demonstrate transfer to unmetered streets.

## Intended use and target

Local research diagnostics and ground-truth collection design. The unit is a block face × configurable 15-minute interval, with 0/15/30/60/120-minute leads. All trained/evaluated labels are **metered sensor-panel proxies** reconstructed from September 2025 and August 2026 LADOT events. Physical curb capacity, full-duration eligible capacity, full-face occupied/available eligible counts and true probability of a suitable space are unavailable. They remain null in forecast artifacts.

Rate labels are occupied sensor-seconds / known sensor-seconds; at least 25% of fixed-panel sensor-time must be known. That missingness threshold is a research rule, not verified sensor accuracy. Point counts and binary panel vacancy require every sensor in that panel to have a known reconstructed state. A complete sensor panel is not a complete block face. Missing target windows are retained and reported as label/abstention coverage.

## Data and inference assumptions

Rosters are fixed using each month’s first seven calendar days; no later IDs enter that month’s panel. Labels begin after discovery. State intervals stop at the next event, UNKNOWN/conflicting state, month end or persistence cap (primary 15 minutes). No backfill occurs before the first observation. Caps 5/15/60 are compared on coverage and fixed-model common-row sensitivity, not tuned against the final test to manufacture performance. Event counts measure transitions only when close observed opposite states exist; rows are never treated as time-weighted occupancy.

Historical sensor delivery/heartbeat times are unavailable: the replay assumes an event becomes available at its UTC timestamp. Geometry and meter identity mapping use October 2026 snapshots. Thus the entire experiment is retrospective, even for event-causal features. Independent sensor reliability, historical location consistency, street-side accuracy and nonrandom reporting remain unresolved.

## Models and feature availability

Implemented neighborhood/time-of-week mean, persistence, partially pooled face/neighborhood means, regularized rate Ridge/logistic binary models and histogram gradient boosting. Count heads use regularized Poisson regression/Poisson boosting with known panel size, followed by bounds at zero/panel size. Panel size is not inferred physical curb capacity. Binary panel vacancy is modeled directly and calibrated, with no independent-space product formula. Model types: [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), [Poisson](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.PoissonRegressor.html), [boosting](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html), [calibration](https://scikit-learn.org/stable/modules/calibration.html).

Primary features: deterministic cyclical calendar terms and observed causal lags, coverage, close observed arrivals/departures, week-ago state, previous-bin neighbors at 300/600 m and selected interactions. Last completed intervals strictly precede the origin. Recent-state features do not carry a state beyond its freshness policy. A typical-pattern artifact uses neighborhood/time of week without recent state.

Additional 100/300/600 m business/building density and curb context plus current tariff/time limits are evaluated only in a labelled retrospective ablation. Their October 2026 availability is later than the backtest. The context feature family is not silently allowed into primary as-of claims. ACS housing/vehicles remain blocked; LODES lacks a verified block-geography join. Opening hours, attendance, past issued weather forecasts, full restrictions/capacity, historical transit and effective closures are excluded with reasons in feature_catalog.json. Broad holiday terms are not parking-rule exemptions. Two nonconsecutive months do not establish annual seasonality.

## Splits, selection and calibration

Configuration and source hashes are in experiment_protocol.json. Rolling origins August 9 and 13 choose rate-model parameters; all imputation/scaling is fit within each training fold. Final training label windows end before August 17 minus a 180-minute embargo. Calibration is August 18–23. The frozen final chronological test is August 25–31, 2026. No feature-selection step or Boruta/VIF/Cp filter is run on test data.

Pure spatial evaluation withholds the north pilot area (latitude ≥34.0635) and a 150 m buffer, removes own-block histories, and computes neighbor features only from training-area blocks. Both sides share their physical segment/block role. That test overlaps historical time periods and is an explicit retrospective geography test. Combined future-time + unseen-area results are separately reported. Related future targets across horizons share observations; horizons are not independent test replications. No random sample split or random early-stopping validation is used.

One preliminary rate result inspection occurred before a methodological correction adding known panel size and nonnegative count losses to count/binary heads. Initial rate results are preserved, and the final run verifies that rate metrics did not change. Splits, rate features and tuning were unchanged; no change was selected to reach a test R² threshold. Future development should use a new prospective final test rather than repeatedly treating this inspected period as untouched.

Probability calibration is fit on the separate calibration period. Regression ranges use its absolute residuals (nominal 90%). Held-out coverage/width are measured rather than guaranteed; serial dependence and domain shift can invalidate exchangeability. Calibration/Brier/log loss apply to the reconstructed panel-vacancy proxy, not verified suitable parking. Detailed metrics and group counts are in results.json/metrics.csv; negative and undefined R² remain visible. No fixed R² target applies; no unmetered performance is measured here.

## Deployment and unsupported populations

Nothing is publicly deployed. Saved joblib files are local trusted artifacts; never load an untrusted downloaded pickle. ForecastArtifact separates rules, capacity and model uncertainty, eligible numeric fields and sensor diagnostics. Freshness gaps, unknown faces, missing histories and unsupported horizons return insufficient data. Typical patterns are labelled separately. Experimental transfer is a current business-density rank/demand prior, not a calibrated unmetered probability.

No validated unmetered/residential, full-curb, legal-duration or citywide numerical prediction is supported. Randomized/repeated manual observations, independently reviewed capacity/rules, source history alignment, wider geographic labels and prospective calibration are required before exposing numerical parking promises. Expected net panel count change does not guarantee any absolute number of available suitable spaces.
