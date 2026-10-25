# Refresh and monitoring plan

Configuration lives in `config/service.json`. Local polling and client refresh do not claim that the underlying parking evidence is fresh.

| Operation | Current implementation / cadence | What changes |
|---|---|---|
| Official source polling | Opt-in; every 120 seconds when enabled, or explicit UI/API poll | Bounded current SODA export, raw Store snapshots/manifests, validated current-state Parquet and poll status |
| New observations | Explicit POST or JSONL import | Validated reviewable manual records; no automatic rules or training |
| Snapshot/feature check | Every 10 seconds and on requests/import/explicit refresh | File/model revisions detected; caches and loaded inference snapshots invalidated |
| Feature updates | Historical design is offline; live current-state polling is **not** a complete recent feature pipeline | Future work must accumulate actual event history/latency and build causal recent windows before activating live learned estimates |
| Forecast issuance | On meaningful input/revision changes or cache expiry | Fresh computation carries an explicit issue time, feature origin and evidence observation time |
| Forecast cache | 60-second TTL; 128 entries | Exact location, arrival/stay, walking limit, eligibility, preferences, mode, data revision and model version; no rounding of destination/profile |
| Client refresh | Optional every 60 seconds while visible | Requests new/cached results; never changes source timestamps |
| Offline training | Explicit training command | New trusted model artifacts and evaluation; never runs inside the API |

Live request cache origins share a one-minute bucket; cache hits retain the original computation/issue timestamps and update only response time. Replay uses an explicit fixed historical issue time. Model/geometry/observation/rule snapshot changes are separate from wall-clock cache expiry. A failed poll retains the last valid snapshot, records its error, and degrades health; fresh HTTP success may still contain old meter transactions. Missing feeds/models/feature windows yield insufficient data rather than fabricated values.

`GET /api/health` reports the latest source observation, retrieval, poll attempt/success/error, source age, rule-load failures, data revision and model version. Monitor stale age (>15 minutes under the current unvalidated policy), growing rule conflicts/unknown coverage, observation rejections, slow inference and candidate truncation. Source snapshots, manual records and rule edits have distinct provenance. `POST /api/refresh` only checks local files; `?poll_source=true` explicitly requests a network poll. Default automatic source polling is off to preserve the reproducible local replay and avoid implying a production live pipeline.

Keep one local Uvicorn worker for the current in-memory cache and serialized local Parquet observation writes. Multiple processes would need transactional storage/shared invalidation and are not supported by this initial server. Long source polls run in a worker thread; inference/rule snapshots are protected by a lock so a response does not mix data revisions. Manual import revisions invalidate queries but do not certify capacity, update eligibility from free text or retrain forecasts.

## Expansion requirements

No external credential is required to run the local API, street diagram, replay or observation intake. Optional `SOCRATA_APP_TOKEN` can improve official polling quotas. Existing `CENSUS_API_KEY` is relevant to the blocked ACS connector, not local serving.

Further numerical parking service requires independently verified full-stay restrictions/signs and permit eligibility, physical/eligible capacity, unmetered ground truth, historical/current sensor mapping and delivery/quality validation. These are data/partnership gaps; no credential alone resolves them. Full postal geocoding, validated pedestrian routing, accessible routing, a public basemap, historical issued weather, transit disruption archives or private occupancy partnerships may require provider terms, quotas and/or credentials to be investigated later. No provider or paid plan is purchased or assumed available.

HTTPS/authentication, transactional observation storage and operational monitoring would be required before sharing a deployed multiuser app. This work binds to 127.0.0.1 and does not publicly deploy or open ports. The browser uses same-origin APIs and no third-party map scripts/tiles; cross-origin writes are rejected. Source credentials never belong in frontend code.
