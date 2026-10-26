# Prospective signal acquisition verification

Checked October 25, 2026 (Los Angeles). No new occupancy labels or R² measurements.

| Source | Status | Rows |
|---|---|---:|
| nws_hourly | downloaded | 156 |
| ladot_sensor_assets | downloaded | 463 |
| ticketmaster | missing_credentials | — |
| curbiq_zones | access_request_required | — |

The sensor export covers the configured Westwood pilot bounding box, not all LA. Source IDs were independently reconciled by the existing ArcGIS connector. Asset status meanings and historical positions still require verification. Weather is one NWS grid, not citywide weather coverage.

Real CLI smoke checks: a prospective request received its valid grid/hour forecast; an August 2026 request received null instead of later weather; missing Ticketmaster data stayed null. Downloaded snapshot hashes verified.

Checks: 97 tests passed, 16 existing data-dependent tests skipped. Twelve new signal tests cover future receipt/issue leakage, stale and geographically unsupported forecasts, event cancellation/distance, incomplete time windows, duplicate IDs, invalid timestamps, target-column exclusion, optional credentials and event page budgets. Optional credentialed APIs were fixture-tested, not accessed live.

Raw snapshots stay ignored by Git. Run `la-parking acquire-signals` on the project machine to obtain its local copies. Use `--refresh` explicitly for a new forecast snapshot. No long-running poller or deployment was started.

Feature builder and acquisition are integrated into the CLI. Existing training/production models are unchanged. Evaluate additions only against matched outcomes with snapshots actually available at issue time. See [source research and access steps](../docs/data_access_research.md).
