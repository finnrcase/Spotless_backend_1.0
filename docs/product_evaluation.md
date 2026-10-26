# Suitable-space and product evaluation

Occupancy regression remains in the existing frozen metered experiments and direct-observation comparison workflow. This continuation adds a separate product target: **at least one vacant position on the specified block face at arrival that is suitable for the recorded vehicle/permit profile for its entire intended stay**. A face result is not a claim about both sides of a physical block. Neither a meter-panel vacancy nor a historic curb polygon establishes this target.

## What can run now

```powershell
.\.venv\Scripts\la-parking.exe product-pilot prepare
.\.venv\Scripts\la-parking.exe field-route
.\.venv\Scripts\la-parking.exe collector
.\.venv\Scripts\la-parking.exe schemas
.\.venv\Scripts\la-parking.exe serve
# Open http://127.0.0.1:8765/pilot, /field-route and /collector.
# Standalone phone files: reports/product/pilot.html and reports/collector.html.
.\.venv\Scripts\la-parking.exe product-readiness
```

The [current readiness report](../reports/product/readiness.md) scores zero observed outcomes: suitability calibration, recommendation success, actual search/walking time and search-time reduction are **unavailable**. No local observation/trial store is opened by `prepare` or `product-readiness`. No trained model, existing R² benchmark, expiry rule or label is overwritten. The capacity audit reads only the supply inventory: all 162,630 faces currently have unknown physical/eligible capacity and incomplete exclusions.

## Repeated counts and review

Start with the existing eight-count Westwood batch: both sides of S Levering Avenue between W Roebling and W Le Conte, at 0/15/30/60 minutes, second side four minutes later. Verify actual unmetered status, public access and posted/temporary rules. This batch checks feasibility and count quality; it cannot validate accuracy. Route links prefill face/session/assignment/offset. The collector's **Prepare next repeat** button clears counts, advances the planned offset, keeps the real prior observation ID and displays count age and the next due time. Actual clocks always govern analysis; overdue/skipped rounds are never filled with zero or planned timestamps. Drafts and saved records persist locally and export as JSONL.

Optional movement watching records actual start/end, arrivals, departures and partial/continuous coverage. Blank means unobserved; zero means watched and no movement. Continuous watching requires both counts. Partial watching may miss movements, and snapshot differences never become arrival/departure counts. The intake recomputes prior age from actual timestamps; an unknown, wrong-face or out-of-order prior link keeps age unknown and is flagged for review. Raw gap lengths, obstructions, counting convention, observed restrictions and confidence remain separate. No gap is converted automatically into legal stalls.

`ManualObservation` now distinguishes total positions inspected, optional physical capacity, optional eligible capacity for the stay/profile, occupancy and suitable vacancies. Eligible supply cannot exceed known physical supply; suitable vacancies cannot exceed known eligible supply. The historic asset inventory is a supply prior, meter roster size is instrument coverage, and centerline length alone is not capacity. Record unmarked-space assumptions and raw lengths; review an estimated denominator rather than treating it as exact. Current official rule coverage, posted-sign verification, count confidence and model confidence remain distinct.

`SuitabilityReview.schema.json` defines an independent review keyed by observation ID. Require count/location review, exact vehicle/permit/duration match, a resolved eligibility status, an explicit posted-sign or official rule evidence source, and a verification interval covering the **whole intended stay**. The review timestamp must follow actual receipt and survey completion. A verified visible suitable vacancy can prove a positive on a partial face without inventing capacity. A zero needs complete inspection, separately verified complete visibility and no recorded obstructed curb. Unknown/conflicting rules or an overlong arrival sweep remain unavailable. Occupancy regression additionally requires reviewed capacity and complete visible counts; its denominator remains the stated position-count convention. The original unmetered model comparison is preserved separately.

## Offline forecasts and rankings

Use explicitly exported direct observations and suitability reviews, plus forecasts logged before arrival. `ProductForecast`, `RankingDecision` and `EvaluationManifest` JSON schemas are generated under `schemas/`. They document every input; no numeric example fixture is presented as measured performance. The forecast includes issue/arrival/training-cutoff/feature-availability/evidence timestamps, model version, profile, scope and optional numeric heads. Meter-panel proxies cannot supply suitable probabilities/counts. Unsupported heads stay null. Compare model versions in separate runs on identical declared targets.

```powershell
.\.venv\Scripts\la-parking.exe evaluate-product `
  --manifest data/product/development_manifest.json `
  --observations data/observations/manual_observations.parquet `
  --reviews data/product/suitability_reviews.jsonl `
  --forecasts data/product/prearrival_forecasts.jsonl `
  --decisions data/product/candidate_decisions.jsonl `
  --output reports/product/development_evaluation.json
```

The manifest declares `data_kind` (`observed` or `synthetic_demo`), phase, future-time/unseen-block axis, train/evaluation observation IDs and the evaluation period. All times require explicit offsets and normalize to UTC. Train/evaluation IDs are disjoint. Both curb sides share physical-block membership. Future-time testing revisits known blocks; unseen-block testing excludes entire physical blocks. A 180-minute embargo applies to **review availability**, not just event time. Historical means and face/hour/day baselines use only declared reviewed training labels available before each issue, within the same metered/unmetered and vehicle/permit/duration stratum. No test outcomes or future rules train a baseline. Development use of any earlier reserved block/session/period or the new product period is rejected. For Parquet, metadata is checked before occupancy columns are loaded; only explicit cohort IDs are loaded. Never point this command at an undeclared JSONL export containing other holdouts.

Reports retain R²/MAE/RMSE for direct occupancy and suitable-count regression, Brier/log loss/ECE/reliability bins for suitability probability, prediction coverage, rejected/unmatched/missing outcomes, block/session counts, evidence age and capacity diagnostics. The binary head does not require a fabricated physical-capacity denominator. Calibration and occupancy objectives remain separate; the evaluator fits neither a model nor a calibrator. It reports no confidence interval pretending that a few repeated snapshots are independent. Geographic selection, counting error, rule interpretation, estimated positions and dependence remain material uncertainty; results are exploratory.

Each ranking decision contains a complete predeclared nearby candidate set, issued and arrival times, walking constraint, price preference, profile and full-stay eligibility evidence available at issue. Candidate parking type is declared before outcomes, not inferred from arrival labels. Unknown/prohibited/conflicting/stale rules and an incomplete whole-stay rule interval exclude a candidate from the eligible-policy comparison. Prices stay unknown; a declared maximum price cannot be checked from a missing quote.

The offline evaluator compares (1) supported suitable-probability ranking, falling back explicitly to nearest eligible when no suitable head exists, (2) nearest eligible, and (3) a training-only historical face/time baseline. It never uses panel probability as suitable availability. Primary comparisons use identical decisions with complete candidate sets and direct arrival outcomes for all policy-selected faces; coverage and excluded/incomplete cases are reported. Selected-only trip outcomes do not supply counterfactual labels for other faces. Arrival matching uses the preregistered two-minute tolerance to the midpoint of a survey no longer than five minutes; this is temporal measurement uncertainty, not persistence truth. Offline top-choice observed success is not actual driver search time. Walking distance is an input estimate, not a measured walking duration. Unsupported search-time reduction stays null.

## Prospective trial protocol

`config/product_pilot.json` reserves **November 23–December 6, 2026**, with a December 7 exclusive end in Los Angeles time. All prior archive/block/session reservations remain intact. Twenty-four trial slots form twelve time/session pairs over six days, with one app and one nearest-eligible assignment in randomized order per pair. Use the same predeclared search area, destination, driver/profile, walking budget and price preference within each pair. The nearest policy requires verified full-stay eligibility; if the app lacks suitable-space support, log its distance/price fallback rather than inventing a probability. With no verified eligible candidate, record that condition rather than treating unknown rules as permission.

Use consecutive allocation IDs; log skips, deviations and unavailable recommendations. Do not enroll only easy requests, replace failed trials, cross over to the other arm, or inspect held-out outcomes to change the policy. These are purposive exploratory slots; 24 trials do not establish statistical power or citywide benefit. Use development data to estimate variability and preregister a larger independent follow-up if needed. Freeze the exact app/model/policy artifacts and candidate-selection protocol before November 23:

```powershell
.\.venv\Scripts\la-parking.exe product-pilot freeze `
  --artifacts path/to/frozen_model.joblib path/to/frozen_policy.json
```

The command records real freeze time, config/allocation hashes and artifact hashes under ignored `data/product/pilot_freeze.json`, refuses overwriting or retrospective freezing, and does not assert that a suitable-space model already exists. The proposed R² **0.50–0.70** and search reduction **20–30%** are planning goals only, not measured results, launch thresholds or acceptance criteria.

The phone ledger prefills allocation and records recommendation receipt, entry into the predeclared search area, first recommended-face arrival, parking, end/abandonment/20-minute limit, walking start and destination arrival. Record while stopped or use a passenger. Actual first-face parking success is a trip outcome; existence of a suitable vacant space is a separate independently reviewed curb label. Do not calibrate existence probability against eventual success elsewhere. Unknown clocks/outcomes stay null. Save/export after each trip. Face links in the local map prefill the recommended face ID. The standalone ledger includes backup restore; API access/accounts/GPS are not required.

```powershell
.\.venv\Scripts\la-parking.exe product-pilot intake --input path/to/trips.jsonl
# After human review in a separate file AND the period's exclusive end:
.\.venv\Scripts\la-parking.exe product-pilot evaluate `
  --input data/product/reviewed_trials.jsonl `
  --observations data/product/pilot_arrival_observations.jsonl `
  --reviews data/product/pilot_suitability_reviews.jsonl
```

Intake validates allocation, actual period, timelines, conflicts and scope; imports are atomic, duplicate-identical IDs are idempotent, and conflicting IDs require explicit review. Device records default to unreviewed. Evaluation checks period completion and immutable freeze hashes **before opening outcomes**. Reviewed trials need a reviewer and post-search review time. Calibrating probability requires a supported pre-search forecast/model version and a matching direct reviewed observation at actual first-face arrival; meter proxies and self-reported eventual parking are insufficient.

Report assigned-arm results, nonadherence, missingness and censoring. Restrict search duration to 20 minutes: a parking event or an observed no-parking search through 20 minutes identifies the restricted duration. Early abandonment is right-censored, not a successful five-minute search and not silently imputed to 20. Conditional observed means and all-assigned lower/upper bounds expose missing follow-up; the point search-reduction metric stays unavailable unless all assigned restricted outcomes are known. Report actual walking time separately, with its measured N. All examples in tests/browser QA are explicitly isolated synthetic fixtures, never product evidence. The local service remains unpublished and no service was purchased.
