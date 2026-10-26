# Start here

This Git root is **Spotless_backend_1.0**, the real app. Leave the separate `Spotless/` reference checkout untouched. Read [docs/current_status.md](docs/current_status.md) and [docs/project_map.md](docs/project_map.md) first, then inspect only task-relevant code, instructions and authoritative reports. Update those two documents when behavior or evidence changes; do not append session transcripts or duplicate reports. Preserve frozen experiment versions and reproducibility.

# Authorized workflow

After every task that changes project files:

1. Run relevant checks; fix failures where possible, otherwise report the blocker without claiming completion.
2. Inspect the complete diff and exact files to commit.
3. Commit only this task's changes with a descriptive message; no empty commits.
4. Push to the configured upstream branch without force.
5. Verify the remote contains the commit; report SHA, checks and blockers.

Normal commits/pushes have standing user authorization. Preserve existing/unrelated work and reconcile differing histories safely. Never commit credentials, local observations, raw data or model binaries; keep them ignored. Use bounded, cached free/public acquisition. No purchases or public deployment are authorized.

# Parking evidence and evaluation

City of Los Angeles is the jurisdiction; metered and unmetered parking are core targets. Additional datasets are predictors, not occupancy labels. Preserve unknown rules, uncertain sensor intervals, source vintages, geographic gaps and unsupported predictions. Curb polygons are not stalls. Evaluate rules for the entire stay separately from model confidence.

Use training-only causal features and chronological validation. Separate known-block forecasting, unseen-block transfer, metered and unmetered results. Select regression on validation squared error/RMSE; report R² and MAE. Select/calibrate probability heads separately. Never change labels or reporting populations merely to raise R².

Inspected tests are legacy benchmarks. Reserve new periods, physical blocks and sessions before tuning; keep reserved outcomes closed during development. Compare identical targets/observations and report coverage/uncertainty. Do not assume meter-to-unmetered transfer or citywide accuracy from Westwood.

# Model simplicity and evidence

Before acquisition/implementation, inventory inputs and state the parking mechanism, evidence gap and smallest justifying experiment. Do not duplicate information or add datasets, features, model families, services or dependencies merely because they are available.

Keep research acquisition separate from serving/promotion. New experiments must include the incumbent and appropriate training-only mean, calendar/weekhour and recent-observation persistence baselines; selecting among complex candidates alone is insufficient. Predeclare selection/intended use; prefer simplicity within validation uncertainty and allow no promotion. Do not rewrite completed/frozen experiments.

Promote a feature family only after identical-row/label ablation on relevant chronological/geographic validation shows useful improvement or measured coverage benefit without material subgroup harm. Report sample/label coverage, block/day uncertainty, missingness, latency, acquisition cost and maintenance burden. Score newly covered populations separately from paired accuracy. Keep marginal, unreliable or harmful inputs experimental or retire them from the active path, preserving provenance/frozen evidence.

Prioritize reviewed unmetered observations, verified legal supply and reliable recent-observation forecasts over more context. Do not expand geography, introduce deep learning or build autonomous collection merely for sophistication. Strength means validated predictions and parking outcomes, not source count, architecture size or selective R². See [model discipline review](docs/model_discipline_review.md) for frozen evidence and the selection limitation.
