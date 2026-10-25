# Local service verification

Story: destination/stay/profile in the browser → FastAPI nearby discovery and full-stay eligibility → local source/model artifacts → forecast contract → map overlays/details.

| Boundary | Result | Evidence |
|---|---|---|
| UI render and streets | Passed | Chrome loaded the map shell and actual local street geometry |
| Destination → API | Passed | Chrome street search, arrival resolver and prediction POST; server returned HTTP 200 |
| API → geometry/model data | Passed | Real-data smoke returned 58 network-reachable faces; actual trained panel estimates and recent/experimental/insufficient states |
| Response → map | Passed | Chrome asserted block-face overlays, panel scope label, unknown rules, slider request, changes display and click details |
| Stale/live degradation | Passed | Real short-lead live example contains zero learned panel estimates; tests also remove feed data and simulate polling failure without destroying the prior snapshot |
| Full-stay rules | Passed | Isolated fixtures cover mid-stay prohibition, conflict, missing/malformed/stale coverage, permits, vehicle class, upcoming rules and DST |
| Observation import | Passed | Temporary-store tests validate imported reports, duplicate rejection, cache invalidation and reviewable evidence; no automatic training/sign verification |
| Cache/timestamps | Passed | Identical replay requests retain computation/issue timestamps on hit; rule revisions invalidate; profile/arrival/walk inputs are keyed |
| API contract | Passed | OpenAPI exports nine API paths and fifteen component schemas, including manual observations and rule coverage |
| Browser errors | None observed | `browser_validation.json`: twelve UI assertions, no uncaught errors; server logs identify API boundaries |

Validation totals: **51 Python tests passed; 5 JavaScript tests passed**. Existing pandas/NumPy/Starlette compatibility deprecation warnings were emitted, without failed checks. The temporary QA server was stopped after verification. No synthetic observations or restrictions were inserted into the real data store.

Limits: this is a desktop Chrome local-browser check, not an on-device accessibility/navigation field test. The app does not establish unmetered/citywide accuracy or complete current restrictions. Panel proxy values remain separate from unsupported eligible-space values, which remain null. Actual current evidence is old; successful computation does not refresh observations.
