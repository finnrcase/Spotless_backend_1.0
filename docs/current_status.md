# Current status

Verified against code and tracked reports on **2026-10-26**. Start with [project_map.md](project_map.md) for paths and commands. Update this document when supported behavior or evidence changes; do not append session logs.

## Supported local product

`la-parking serve` runs the working loopback API/map: local street/coordinate destination lookup, nearby City block faces, approximate walking-distance ranking, arrival slider, full-stay permit/vehicle/restriction evaluation, source ages, cache/refresh reporting and manual observation import. Historical replay uses real August events; it is explicitly not live parking. Rule coverage is currently incomplete; missing rules remain unknown and source verification is distinct from model confidence. See [local service](local_service.md) and [refresh behavior](service_refresh.md).

Physical curb assets are historic footprints, not stalls. The citywide foundation has 81,315 segments / 162,630 faces, predominantly approximate curb-side geometry; geometry coverage is not prediction validation. Verified physical and full-stay legal capacity are unavailable in the [capacity audit](../reports/product/capacity_audit.json). Suitable-space counts/probabilities remain null. Ranking falls back to eligibility status, estimated walking distance and optional indicative snapshot price. No validated search-time estimate exists.

The standalone phone form supports actual 0/15/30/60 repeat times, gaps, visibility, uncertainty, separate physical/legal capacity and observed movement windows. A [16-face development plan](../reports/collection/development_plan.json), duplicate-aware image/video import, blinded review, count agreement and effort accounting are implemented. The [collection audit](../reports/collection/audit.json) has **zero supplied modern captures or reviewed full-face count units**. Planned assignments are not observations. Desktop phone-sized checks do not establish actual field-phone usability. Start with [the eight-count batch](phone_collection.md), then [capture/review instructions](capture_collection.md).

## What serving loads

`config/service.json` declares **sensor-panel-v1**. `service/inference.py` calls `forecasting.request_forecast()`, which loads:

- `artifacts/models/future_time_h{0,15,30,60,120}_{occupancy_rate,available_count,any_panel_vacant}_boosted.joblib` for supported short horizons, plus available later count heads for 15/30/60 changes.
- `artifacts/models/future_time_typical_pattern.joblib` above 120 minutes, explicitly a typical calendar pattern.

These ignored local bundles depend on `data/modeling/design.parquet`, mapped archived events and calibration cutoffs. Live short-horizon panel forecasts abstain because the service does not reconstruct a recent feature window from current polls. Replay requires the supported origin and fresh-enough reconstructed sensor evidence. Even supported panel estimates do not establish whole-curb or legally suitable parking. The optional business-density percentile is an unvalidated activity prior.

Temporal-v2, spatial-v3, coverage-v4 and direct-observation experiments are **not promoted into serving**. `/api/model-evidence` currently summarizes v2/v3; use the v4 report below for later research. No retraining or prediction change was performed for this cleanup.

## Measured evidence and limits

The [temporal-v2 table](../reports/modeling/TEMPORAL_V2.md) is the relevant known-block meter-panel forecasting comparison: at 60 minutes, validation-selected broader tuning has validation RMSE 0.2777, legacy-test R² 0.2397 and MAE 0.2309 on 6,421 rows / 23 physical blocks. The period was already inspected; it is not an untouched test. The [spatial-v3 report](../reports/modeling/SPATIAL_V3.md) separately records unseen-block behavior and failures.

The latest [Census/regional-v4 comparison](../reports/modeling/COVERAGE_V4.md) tests static context on matched targets. Added Census variables slightly improve known-block validation but worsen unseen-neighborhood validation; no rate-head promotion follows. Frozen temporal-v2 is stronger on the paired known-block legacy subset. Preserve the [v4 candidate-selection limitation](model_discipline_review.md); do not rewrite frozen results. These reports concern selective, uncertain **metered sensor panels**, not validated citywide or unmetered accuracy. The 15-minute expiry is unchanged; heartbeat guarantees, outage truth and historical sensor relocation remain unresolved.

Reviewed unmetered test labels remain **zero**. [Unmetered transfer results](../reports/unmetered/comparison.md), [direct A/B/C/D metrics](../reports/controlled_observations/readiness.md), [suitable-space calibration/ranking/search outcomes](../reports/product/readiness.md) and detector performance are unavailable. No R² gain or search-time reduction was measured by the new workflows.

## Sources and remaining blockers

The [Westwood source report](../reports/westwood_context/coverage.md) records actual bounded downloads, source dates, pagination and limitations: UCLA events lack source coordinates; Village events have coordinates but unresolved UTC timing; sweeping polygons supply route schedules, not complete curb rules; public-way reservations are not verified closures; the historical study extraction is explicitly partial and never current truth. [NWS and sensor-location checks](../reports/signals_verification.json) provide prospective context only. Current snapshots cannot backfill historical experiments.

Optional Ticketmaster/CurbIQ keys are absent. The saved Census key loaded but the authenticated request failed; cached official public ACS data supplied the frozen experiment. No key is required to start collection. Old NAIP is May 11, 2022 date-only imagery, native 0.6 m; [its feasibility report](../reports/imagery/feasibility.md) has no measured detector result. [Drone feasibility](drone_feasibility.md) runs offline arithmetic and pinned SDK object validation; PX4/Gazebo flight execution is blocked by missing runtime, and no real-aircraft connection or route approval exists.

## Single next experiment

Collect and independently review **eight development counts: two verified unmetered faces at 0/15/30/60 minutes**, with actual capture/receipt/review times, whole-stay signs and explicit capacity/visibility uncertainty. Preserve all existing reserved physical blocks, sessions and archive periods. Verify the first export/review before expanding the development plan.

Then accumulate independent sessions/blocks for the predeclared [controlled A/B/C/D experiment](controlled_observations.md), starting with 15-minute recent-observation value against calendar/hierarchical/persistence/simple tabular references on identical direct outcomes. The first batch establishes workflow quality, not accuracy; the protocol's sample floors and separate future/unseen/metered/unmetered cohorts still apply. Keep reserved outcomes closed, select on validation and freeze before release. Further source acquisition, autonomous capture and model complexity should follow a measured gap from that experiment.
