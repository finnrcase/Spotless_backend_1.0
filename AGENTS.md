# Project workflow

After every task that changes project files:

1. Run the relevant checks. Fix failures where possible; otherwise report the blocker and do not claim completion.
2. Inspect the diff, including the exact files to be committed.
3. Commit this task's changes with a descriptive message. Do not create empty commits.
4. Push to the configured upstream branch.
5. Verify that the remote branch contains the commit.
6. Report the commit SHA, checks, and any blockers.

The user gives standing authorization for normal commits and pushes. Do not force-push, commit credentials or large raw datasets, or include unrelated changes. Preserve existing work, reconcile differing histories safely, and leave unrelated work untouched. This authorization does not authorize purchases or public deployment.

# Parking evidence and evaluation

The jurisdiction is the City of Los Angeles. Metered and unmetered parking are core targets. Additional datasets are predictors, not occupancy labels. Preserve unknown rules, uncertain sensor intervals, historic source vintages, geographic gaps and unsupported predictions explicitly. Curb asset polygons are not parking stalls.

Use training-only causal features and chronological validation. Separate known-block forecasting, unseen-block transfer, metered results and unmetered results. Select regression models on validation squared error/RMSE; report R² and MAE. Select and calibrate probability heads separately. Never change label rules or reporting populations merely to raise R².

Previously inspected tests are legacy benchmarks. Reserve new periods, blocks and sessions before tuning; do not open reserved outcomes during development. Compare versions on identical targets and observations, and report coverage and uncertainty. Do not assume meter models transfer to unmetered streets or imply citywide accuracy from a Westwood sample.

Use bounded, cached free/public acquisition. Keep raw data, credentials, local observations and model binaries excluded from Git. Do not purchase services or publicly deploy.

# Model simplicity and evidence

Do not add datasets, features, model families, services or dependencies merely because they are available. Before acquisition or implementation, state the parking mechanism, the specific evidence gap, and the smallest experiment that could justify the addition. Inventory existing inputs first and avoid duplicating their information.

Keep research acquisition separate from serving and model promotion. For future experiments, eligible candidates must include the incumbent and appropriate simple baselines (training-only mean, calendar/weekhour, and persistence when recent observations exist). Selecting the best of several complex candidates alone does not demonstrate improvement. Prefer the simpler candidate when differences are within validation uncertainty; predeclare the selection rule and intended use before scoring. Do not rewrite completed/frozen experiments.

Promote a feature family only after an identical-row, identical-label ablation on relevant chronological/geographic validation demonstrates useful improvement or an explicitly measured coverage benefit, without a material subgroup regression. Report sample/label coverage, block/day uncertainty, missingness, latency, acquisition cost and maintenance burden alongside scores. Score newly covered populations separately from paired accuracy comparisons. Keep marginal, unreliable or harmful inputs experimental or retire them from the active path; retain provenance and frozen evidence.

Prioritize reviewed unmetered observations, verified legal supply and a reliable recent-observation-to-forecast path over additional contextual variables. Do not expand geography, introduce deep learning, or build autonomous collection infrastructure solely to make the project appear more sophisticated. Model strength means validated predictions and better parking outcomes, not source count, architecture size or a selectively reported R². See docs/model_discipline_review.md for the current evidence and next experiment.
