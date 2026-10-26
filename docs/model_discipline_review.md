# Model discipline review

Reviewed remote main f08837aa81c2517bf203d867129703e7f6e36fa9. This is a targeted review of coverage-v4 selection, results, forecasting and serving paths, not a full repository correctness audit. No model was retrained, promoted, removed or re-scored for this review.

## What the evidence supports

- Coverage-v4 tests calendar, existing Census and additional Census variants on matched rows with fixed ExtraTrees complexity. It preserves label expiry and reserved outcomes, and explicitly disables automatic promotion.
- In known-block rolling validation, additional Census features change occupancy-rate R² from 0.1889 to 0.1975. In unseen-neighborhood validation, they change it from -0.0244 to -0.0294. The selected rate variant remains existing_census. A small known-block improvement is not evidence to activate the additions for neighborhood transfer.
- The report retains temporal-v2 separately. On the paired 5,274-row legacy known-block subset, frozen temporal-v2 R² is 0.2642, versus 0.1516 for the selected static Census model. This is a version comparison, not a controlled feature ablation, and the inspected period is not a fresh test. Do not replace the temporal model with the static regional experiment based on broader data coverage.
- New-region known sensor-time is only 13.59% under the unchanged expiry policy. Complete sensor-panel count labels are especially sparse. More context does not resolve uncertain outcomes or establish full-curb coverage.
- Reviewed unmetered validation labels remain zero. No unmetered accuracy or citywide performance claim is supported.
- The serving adapter declines short-horizon live numeric estimates when a reconstructed recent feature window is missing. Successful acquisition alone does not establish an operational forecast pipeline.

Sources: reports/modeling/COVERAGE_V4.md, config/coverage_v4.json, src/la_parking/coverage_experiment.py, src/la_parking/forecasting.py and src/la_parking/service/inference.py.

## Selection limitation to address in the next experiment

Coverage-v4 reports pooled-mean and weekhour baselines, but its `selected` comprehension restricts candidates to `cfg['variants']`. Consequently, “selected” means best configured feature variant, not necessarily best available predictor. Automatic promotion is disabled, so this is not evidence that a worse model was deployed. Leave the frozen experiment intact. Future selection must explicitly consider the incumbent and appropriate simple baselines, allow no promotion, and prefer simplicity within validation uncertainty. Negative R² alone does not decide promotion: compare paired errors and the intended deployment population.

## Smallest useful next experiment

1. Use existing Westwood development routes and collectors. Verify legal supply and collect repeated reviewed counts, including unmetered faces. Preserve every existing reserved block/session; planned visits are not observations.
2. Evaluate a pooled/calendar baseline, a training-only block/weekhour baseline, recent-count persistence with observation age, and one existing small tree model. Only include recent counts available at issue time. Start at a 15-minute horizon and report 30/60-minute results where matched repeat visits permit.
3. Compare context-only versus recent-observation versus combined variants on identical eligible outcomes. Keep manual full-face counts distinct from sensor-panel targets. Hold out whole days and physical blocks, report missingness and coverage, and keep final reserved outcomes closed until choices are fixed.
4. Measure occupied/vacant count MAE, vacancy probability calibration and R² where defined. When sample size permits, use a predeclared prospective comparison of search time and legal parking success against a simple recommendation baseline. Track collection cost per reviewed observation.
5. Add one source family only when this experiment identifies an error it plausibly resolves. Keep weather/events/rules acquisition available for prospective trials; do not activate unused context merely because it was downloaded. Defer more neighborhoods and custom autonomous flight until Westwood results and collection economics justify them.

This review adds instructions for future work, not an executable promotion gate. The next implemented experiment must enforce its declared candidate selection and report any unmet acceptance condition.
