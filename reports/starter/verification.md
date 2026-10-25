# Starter continuation verification

Story: preserve existing data/models, import the supplied pilot, follow a planned face into phone counts, and review historic imagery without fabricating occupancy evidence.

| Boundary | Result | Evidence |
|---|---|---|
| Starter bytes → source tables | Passed | 96 response hashes/lengths; complete independent ID/page reconciliation; `quality.json` records schemas, bounds and exact-box exceptions. |
| Source raster → imagery tasks | Passed | Primary raster 17317 `/info` confirms 0.6 m pixels; 12 bounded tiles/24 faces retain hashes, returned extents and date-only 2022 capture. |
| Field route → collector UI | Passed | 390 px Chrome checks confirmed stable face/session/assignment prefilling and no horizontal overflow. |
| Counts → local export → Python intake | Passed | Observed zero, explicit no-gap measurement and metadata persisted; browser record accepted into an isolated temporary intake. Real observation store untouched. |
| Image → masks/boxes → backup | Passed | Actual image rendered; visible mask/vehicle box persisted; exact image hash/date-only status preserved in JSON export. No independent reference or model detections asserted. |
| Destination UI → API → actual model/data → map | Passed | Current local Chrome test verified street search, nearby forecasts, overlays, slider and 15/30/60 display, full-stay unknown rules, stale live evidence and no invented observations. |
| API schemas and static links | Passed | Full Python suite includes `/field-route`, `/collector.html`, `/imagery`, failure examples and new optional raw-gap fields in OpenAPI. |

Completed: **76 Python tests, seven JavaScript tests, 16 starter browser assertions, 13 service/browser assertions**. Module compilation passed. Python emitted existing pandas/NumPy and Starlette deprecation warnings; no tests failed. Browser reports: `browser_validation.json` and `../service/browser_validation.json`. The owned loopback server was stopped.

Synthetic count/annotation fixtures exercise logic only and stay in test profiles/temporary directories. Their scores are not model performance evidence. The 105 removed spare files were individually hash-matched to retained source content; audit: `duplicate_cleanup.json`.

Limits: actual phone/browser handling still needs a field trial. No detector, configured weights/runtime or independent image references are available. Full current curb restrictions and contemporary direct unmetered observations are absent. `../imagery/evaluation.json` and `../unmetered/comparison.json` keep unavailable metrics null. Historical imagery and mixed zone aggregates cannot validate time-specific or citywide suitable-space forecasts. No fixed R² benchmark applies.
