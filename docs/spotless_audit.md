# Spotless audit

Read-only upstream: https://github.com/finnrcase/Spotless/tree/4fc449ac2d8302fc7d8856345867bc0483e35ca8

Audited the recursive repository tree, acquisition scripts, requirements, source dictionary, design audit, Notebook 03 completion report, a retrieval manifest, and the code and saved outputs in all eight notebooks. Reference copies live under ignored `data/reference/spotless`. No upstream files or branches were changed. The source commit is the reproducibility anchor; local connector-decoded reference files are not claimed to have byte-identical Git blob hashes.

## What exists and what runs

The repository has acquisition Python modules (`collect`, `audit`, `document`, `supplement`, `retry_zoning`, `zoning_source_ids`). Reusable cleaning/features/modeling directories contain only placeholders; the substantive pipeline is in notebooks. Requirements are mostly unpinned, and inputs use literal retrieval-directory paths. Raw/processed analytical inputs are absent from the tracked tree, so a fresh clone cannot execute the analytical pipeline without reconstructing those inputs. We inspected saved executions; we did **not** rerun upstream notebooks against unavailable original inputs or execute upstream acquisition scripts.

| Notebook | Actual contents at pinned commit | Code cells | Saved errors |
|---|---|---:|---:|
| 01 | August 2025 event inspection, inter-event durations, monthly outcome | 15 | 0 |
| 02 | Meter parsing, exact duplicate handling, numeric tariff/time limits, coordinates | 14 | 0 |
| 03 | Census tract/ACS joins, business buffers, zoning checks, cross-section export | 20 | 0 |
| 04 | Executed EDA, missingness, distributions and relationships | 16 | 0 |
| 05 | Executed variable-selection analysis | 16 | 0 |
| 06 | Three OLS specifications and shuffled five-fold validation | 12 | 0 |
| 07 | Residual, influence, robust inference and sensitivity diagnostics | 21 | 0 |
| 08 | One effectively empty code cell; results narrative unfinished | 1 | 0 |

The Notebook 03 completion report says Notebook 04 was not started **at the date of that report**. The pinned notebooks now contain later executed EDA, regression and diagnostics. Those notebook contents take precedence over the older report/README progress claims. Saved error-free outputs demonstrate previous executions, not a successful clean-room rerun today.

## Reuse

Keep immutable original response bodies, UTC retrieval directories, SHA-256 manifests, byte ceilings, API error/HTML detection, and explicit source IDs. Keep meter ID string types, metre-based EPSG:26911 buffers, unique containment joins, missing-denominator handling, and status columns for unmatched/ambiguous joins. Acquisition documents identify real LADOT attachment assets, Census/NOAA/Metro/calendar sources. They are useful discovery leads; every connector here checks current metadata independently.

The original collector downloads an entire chosen month, uses a 600 MB/file bound, retrieves several complete current exports, and requests zoning pages by offset. It does not implement persistent HTTP request caching, robust retry/backoff, or universal end-to-end ID reconciliation. The separate zoning source-ID/retry scripts and manifests expose changing page contents and failed responses. This foundation uses cached count/ID snapshots, reconciles every spatial batch and rejects changing pagination counts; mutable SODA feeds still lack snapshot isolation.

## App-relevant limitations

* **Different target.** Notebook 01 estimates occupied minutes divided by accepted observed minutes for one August 2025 cross-section. It discards event-time structure in the final monthly outcome. A monthly space occupancy rate does not answer whether an eligible space will exist at a particular arrival time, remain legal for a requested duration, or be suitable for a permit/vehicle class.
* **Selection and missingness.** The reported August raw sample has 4,905 sensor IDs and 3,707,820 events. The 25-active-day filter retains 4,185; matching to current inventory yields 4,139. These are documented upstream results, not measurements recomputed here. Sensor coverage is geographically selective and metered; it cannot establish citywide or unmetered performance.
* **24-hour rule.** Notebook 01 drops intervals longer than 1,440 minutes, retains shorter intervals by carrying the state to the next event, and excludes UNKNOWN starts. A long no-change interval could be true persistence or sensor failure. A short one can also be wrong. The cutoff changes the denominator and may select operating hours. Evaluate 5/15/60-minute conservative caps and held-out survey agreement rather than inheriting 24 hours. Our 15-minute default is explicitly an unvalidated research policy, with sensitivity outputs.
* **25 active days.** A raw event on a day is not 24 hours of reliable coverage. This filter selects frequent-reporting sensors and can discard useful sparse observations. Here there is no minimum active-day exclusion; coverage is a separate time-window measure.
* **UNKNOWN and boundaries.** UNKNOWN must end prior known-state intervals and never become VACANT. Beginning-of-month state, end-of-month censoring, same-time conflicting states, repeated states, missing heartbeats and across-month gaps need explicit treatment. This foundation limits persistence, keeps conflicts unknown, partitions unsampled months, and never backfills before the first observation.
* **Time handling.** Notebook 01 parses naive `EventTime_Local`, ignoring the UTC column. August lacks a daylight-saving transition, hiding a problem that becomes material citywide/year-round. Prefer the documented UTC transaction column; local schedules use America/Los_Angeles. Ambiguous/nonexistent wall times are quarantined rather than guessed. Current `eventtime` is a floating SODA timestamp whose column documentation explicitly says UTC.
* **Stale current data.** Last known state is not a heartbeat, a fresh occupancy survey, or an arrival-time forecast. Dataset row-update time cannot substitute for each meter's transaction timestamp. Store both observation and retrieval time; report age and abstain outside the selected freshness policy.
* **Coordinates.** Broad valid coordinate ranges and nonzero values do not prove curb accuracy. Check City jurisdiction, distance to streets, intersection ambiguity and left/right orientation. Do not silently snap displaced points or transfer sensors between nearby streets. Current coordinates cannot prove historical locations.
* **Zoning.** Notebook 03 finds only 49 nonblank codes among 4,139 street points (1.1839%); only 20 class labels are present. Streets often fall outside parcel zoning polygons. The mixed original/supplemental pages retain 97 repeated IDs and changed multiplicities. Avoid treating unmatched streets as a zoning class or applying an arbitrary nearest parcel. Future features should summarize adjacent parcel frontage or local area, with ambiguity and version evidence.
* **Vintage mismatch.** August 2025 labels, October 2026 meter/business snapshots, 2020–2024 ACS estimates and mixed-date zoning are not a historical feature panel. Current tariff ranges omit exact hour schedules; current registrations omit historical closures and true hours. Preserve availability/effective dates and avoid future information in backtests.
* **Validation.** Shuffled space-level KFold in Notebook 06 evaluates a monthly cross-section. Nearby streets and repeated sensors need spatial holdouts; arrival-time prediction needs forward-chaining evaluation with as-of feature availability and separate Westwood/other-area tests. OLS can predict outside [0,1]. Later use calibrated count/probability models or hierarchical temporal models if data supports them; complexity cannot replace labels.

`docs/cleaning_decisions.md` is largely headings without decisions. This project records operational decisions, contracts, limitations and continuation work explicitly.
