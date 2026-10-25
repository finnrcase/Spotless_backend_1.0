# Contracts and provenance

`src/la_parking/contracts.py` is the source of truth; `la-parking schemas` exports ten JSON Schema files. Every interchange record carries source ID, source-record ID, version, UTC retrieval timestamp, confidence and a field-to-provenance mapping. Provenance is one of observed, derived, assumed, imputed or unavailable. No imputation is applied in the initial build.

| Entity | Identity / key fields | Required distinctions |
|---|---|---|
| StreetSegment | segment_id, source IDs/version, WGS84 geometry | City jurisdiction, applicability/exclusion, geometry lineage |
| BlockFace | block_face_id, segment_id, left/right | canonical orientation, physical curb vs approximate offset, source curb IDs |
| CurbInventory | face + effective [from,to) | physical vs eligible capacity, bounds, exclusions completeness, null unavailable counts |
| Restriction | rule ID, face, effective interval | raw text, local schedule, timezone, permit eligibility, interpretation status |
| OccupancyObservation | observation ID, space/face, observed UTC | OCCUPIED, VACANT, UNKNOWN, NO_OBSERVATION; freshness and direct evidence type |
| Coverage | entity + window | expected/observed/unknown seconds and max gap, bounded denominators |
| Feature | entity + feature + validity | static/dynamic, availability timestamp, missing value provenance |
| Event | event/venue IDs + interval | announcement time, revision/status, location, nullable estimated attendance |
| ManualObservation | survey ID, face, observer pseudonym | snapshot start/end, complete/partial coverage, legal vacant vs unsuitable counts, GPS accuracy |
| Forecast | issue, arrival, duration, face | permit class, supported/experimental/unsupported, uncertainty and model version |

All aware timestamps normalize to UTC. Naive timestamps, reversed intervals, impossible capacity/count combinations, unknown-state space counts and unsupported nonnull forecasts are rejected. Geography functions separately validate CRS, coordinates, City inclusion, geometry validity, source ID completeness, nearest-street distance and ambiguity. Intake additionally checks known face ID, duplicate survey ID, physical proximity and survey duration.

The phone-collection extension adds field-observed `parking_type`, `location_method`, nullable measured GPS accuracy, `rules_checked`, intended duration, vehicle/permit class, capacity basis and sampling stratum. Legacy records remain valid with unknown type/unchecked rules. A confirmed map pin must not carry measured GPS accuracy. Intake adds independent location/label review flags; successful storage is not verified training-label status.

Wide Parquet inspection tables are analytical projections: their row-level provenance string does not replace a complete per-field mapping for interchange. Raw source evidence and manifest hashes retain observed fields; geometry hashes, offsets, spatial matches and state-persistence intervals are derived. The 8 m offset, association tolerances and freshness policies are assumptions. Unverified capacity/rules/availability are unavailable. No failed-source values become zeros.

The build reports invalid/missing coordinates, meter-ID conflicts, exact duplicates, source geometry invalidity, join success/ambiguity, per-meter observation age and sensitivity of inferred coverage. `pilot_face_coverage.parquet` has zero **observations** where unsupported but nullable **available spaces** everywhere: zero evidence is not zero available parking. A fresh meter subset is still partial evidence for a face, never its total eligible-space count.

Restriction schedules and forecast outputs are contracted but not produced as verified application records in this release. Do not use an old sweeping table, sign-count polygon or construction permit as a completed legal rule without interpretation and date validation. Raw calendar events are normalized only for the verified all-day one-day format; other formats are quarantined rather than guessed.
