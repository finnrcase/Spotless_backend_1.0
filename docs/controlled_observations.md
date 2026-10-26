# Controlled context and direct-observation experiment

This is a new experiment, not a rewrite of temporal-v2/spatial-v3/coverage-v4. The actual current [readiness table](../reports/controlled_observations/readiness.md) contains **unavailable** scores at 15/30/60 minutes, separately for metered/unmetered and known-block future/unseen-block future. No real direct cohort has been supplied, no outcome store was opened and no model was fit for this report. Do not infer direct legal-vacancy accuracy from archived sensor panels.

Mechanism and smallest test: current context may explain demand/rules, while a recent human observation may explain near-term state. Compare those information sources on exactly the same reviewed face/time targets. Preserve the actual serving incumbent, which presently abstains on full-face suitable-space heads. **A_reference is an explicitly named compatible simple reference, not a relabeled meter-panel model.** B adds verified context, C adds recent direct observations, D combines both. The unsupported incumbent has no fabricated numeric score; coverage is zero. Existing metered-panel regression reports remain separate authoritative historical evidence.

```powershell
.\.venv\Scripts\la-parking.exe controlled-experiment readiness
# Explicit development export and new suitability-review schema from product_evaluation.md:
.\.venv\Scripts\la-parking.exe controlled-experiment prepare `
  --table data/product/development_observations.jsonl `
  --reviews data/product/development_reviews.jsonl `
  --manifest data/product/controlled_manifest.json `
  --output data/product/development_reviewed.parquet
.\.venv\Scripts\la-parking.exe controlled-experiment fit `
  --table data/product/development_reviewed.parquet `
  --context data/product/issue_time_context.parquet `
  --manifest data/product/controlled_manifest.json
```

The manifest has `data_kind` (`observed`/`synthetic_demo`), `splits` for `known_block_future` and `unseen_block_future`, each with disjoint `train_ids`, `validation_ids`, `calibration_ids`, `test_ids`, plus a future `release` (phase `locked_test`, aware evaluation start/end and prospective freeze file). Keep final test rows out of the development file. Training/validation/calibration only are read for fitting; IDs declared as test on another axis cannot enter development. All earlier reserved physical blocks/sessions/periods remain protected. Context rows key observation ID and horizon, carry **received and available timestamps**, and include each declared numeric context column with null for unavailable values. Both timestamps must precede issue. Current event/rule snapshots cannot backfill historical features.

Prepare labels from the new independent suitability reviews: direct human source, complete face and verified visibility, exact capture/receipt/review chronology, matching vehicle/permit/duration, and full-stay rule evidence. Physical blocks group both sides. Capacity-unverified rows cannot supply occupancy rates or verified vacant-count targets. Missing targets remain missing, and every variant uses the same valid targets; missing context/history never removes an otherwise valid label. Report missing declared IDs and unknown population coverage rather than silently changing the denominator.

Forecast issue equals the actual target observation start minus 15/30/60 elapsed minutes. Recent evidence must have ended and been received/reviewed by issue, with the same face/profile and at most 90 minutes of age. Exclude the target observation ID, source-record ID and any declared common `sample_unit_id`; adjacent frames cannot masquerade as a recent input. No planned collection time or target capture is used as an input. Age/confidence and missingness accompany recent occupancy/vacancy; arrivals/departures use only actual watching windows ending before issue, with partial/continuous quality. Snapshot differences never become movements.

Per population, horizon, target and information variant, the validation candidates include pooled mean, weekhour, persistence when the variant has recent inputs, hierarchical block shrinkage, regularized ridge and one small existing tabular tree. A/B cannot access recent columns through persistence. Select regression on validation MSE/RMSE aligned with R²; legal-vacancy heads use Brier separately. Prefer the simplest candidate whose paired block/day 95% loss-difference interval includes zero relative to the validation best; with insufficient groups, retain the simple reference. A separate chronological calibration partition fits Platt scaling for binary probabilities. There is no automatic model promotion. This is a small tabular assessment, not a reason to add a deep architecture.

Hierarchical candidates and D plus actual movement features are assessed on validation **before** any final evaluation. The movement variant is validation-only and never silently adopted. With current labels their benefits are unavailable. Training-session-prefix learning curves (25/50/100%) use fixed chosen complexity and **validation only**, so final outcomes are not repeatedly tuned to draw a favorable curve. A curve from one training session cannot establish a data-scaling benefit.

Freeze the model directory's `complete.json`, its `.joblib` files, the split manifest and feature policy before the prospective period using `product-pilot freeze --artifacts ...`. Complete development refuses overwrite; register a new experiment/version if changing choices. After the period and freeze gates permit release:

```powershell
.\.venv\Scripts\la-parking.exe controlled-experiment prepare `
  --table data/product/explicit_final_cohort.jsonl `
  --reviews data/product/explicit_final_reviews.jsonl `
  --manifest data/product/controlled_manifest.json --release-test `
  --output data/product/final_reviewed.parquet
.\.venv\Scripts\la-parking.exe controlled-experiment evaluate `
  --table data/product/final_reviewed.parquet `
  --context data/product/issue_time_context.parquet `
  --manifest data/product/controlled_manifest.json
```

Release is checked before opening final data. Evaluation loads frozen model bytes and never fits/selects/calibrates a model. Test membership cannot change from the development registration. Target-row hashes prove identical comparisons. Re-running the same frozen evaluation is reproducible; changing a model or inspected target at the same output path fails and requires a newly reserved period. Include development rows in the final permitted cohort for verified block lineage/history, retaining their original receipt/review vintages. Earlier evaluation observations can be operational C/D inputs only if their recorded review was actually available by that forecast issue; models remain fixed. C/D on untrained blocks with such direct evidence is **cold start with observations**, not pure transfer with no new-block evidence.

Report R²/MAE/RMSE, capacity-reviewed vacant-count error, legal-vacancy Brier/log loss/ECE/reliability bins, declared/provided/valid N, feature coverage, physical blocks and grouped squared-loss intervals by block, day and block/day. Fewer than three groups yields unavailable intervals, not false precision. These conditional intervals do not cover label/schedule error or every cross-day dependence. Metered and unmetered models/results remain separate; mixing training populations is not presumed useful. Newly covered populations are distinct from paired accuracy improvements.

Minimum workflow floors per population and axis are 40 training, 12 validation, 12 calibration and 12 test direct outcomes, four training physical blocks and three distinct unseen test blocks. These are not power guarantees, R² thresholds or a license to treat repeats as independent. Each horizon also needs suitable earlier observations available by issue; 0/15/30/60 snapshots do not guarantee that their review finished early enough. The first eight-count batch checks quality; the 16-face plan yields only 64 planned snapshots across types. More independently reviewed sessions and held-out blocks are needed before the full comparison is credible. No measured score or learning curve has been fabricated from this shortfall.
