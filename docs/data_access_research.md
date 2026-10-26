# Higher-value parking data: source research and additions

Researched October 25, 2026 (Los Angeles). No purchases, subscriptions, access requests, emails or public deployment were performed. No new R² has been measured. Existing holdouts and sensor-label policies are unchanged.

## What is most likely to matter

The largest missing input is independent, time-located unmetered occupancy evidence. Weather, events and neighborhood context are explanatory features, not substitutes for those outcomes. Licensing another vendor's probability output could help the product, but evaluating against that same output would measure imitation, not real parking accuracy.

| Priority | Source | Verified evidence | Access and role |
|---|---|---|---|
| 1 | Automotus / INRIX Real-Time Occupancy | January 2026 provider announcement explicitly includes Los Angeles in camera-observed curb occupancy coverage. LADOT describes 56 cameras in its DTLA project. | Request exact block coverage, history, observed versus modeled fields and research/training rights. Westwood and residential coverage NOT verified. No public download obtained. |
| 2 | CurbIQ LA Curbs and Events APIs | LA-specific access page states LADOT partnership; public API docs describe zones, policies, events and metrics. | Request LA token and coverage. Potential supply/rules and curb activity; rule inventory alone is not occupancy. Bounded first-page zones probe implemented; no token here. |
| 3 | Parknav LA | Provider explicitly advertises free, permit and metered availability in LA and lists Westwood. API plans and a trial exist. | Likely benchmark/product feed; underlying independent observations and model-training rights unverified. Business pricing requires a quote. Personal app subscription is not an API license. |
| 4 | Public NWS hourly forecast | Working /points lookup and grid hourly forecast verified. | Downloaded; prospective temperature/precipitation features, no key required. Does not reconstruct issued historical forecasts. |
| 5 | Ticketmaster Discovery | Official event/venue API, documented dates and coordinates. | Connector implemented; key missing in this workspace. Listings are incomplete demand proxies, with unknown attendance/end time. |
| 6 | LADOT sensor asset inventory | Queried official GIS layer, including status and position attributes. | Downloaded 463 pilot assets. Cross-check mapping/roster; not independent occupancy or verified health. |
| 7 | Parking citations | Public current dataset and spatial query verified. | Enforcement-biased proxy. Not added as a model feature by default because measured predictive value is unknown and tickets are not occupancy labels. |
| 8 | TomTom on-street parking | Official current docs describe probability and geometry APIs. | Access is sales-gated and labeled automotive-only; not in free evaluation/PAYG. Confirm our app's eligibility before adding. Off-street availability is a different product. |

## Access pages and documentation

- Automotus/INRIX observed occupancy announcement: https://inrix.com/press-releases/inrix-expands-real-time-parking-and-loading-occupancy-coverage-to-13-new-cities-through-strategic-integration-with-automotus/
- LADOT deployment description: https://ladot.lacity.gov/projects/livable-streets/strategic-planning
- Automotus contact/access: https://www.automotus.ai/curb-management
- CurbIQ LA request: https://www.curbiq.io/curb-api-la
- CurbIQ docs: https://curbiq.gitbook.io/curbiq-api-documentation
- CurbIQ zones query: https://curbiq.gitbook.io/curbiq-api-documentation/curbs/curbs_zones
- Parknav LA: https://parknav.com/city/los-angeles
- Parknav pricing/trial: https://parknav.com/pricing and https://my.parknav.com/frequently-asked-questions
- NWS docs: https://www.weather.gov/documentation/services-web-api
- Ticketmaster docs/key setup: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
- Sensor assets: https://maps.lacity.org/lahub/rest/services/LADOT/MapServer/16
- Citations: https://data.lacity.org/Transportation/Parking-Citations/4f5p-udkv
- TomTom on-street access: https://docs.tomtom.com/parking-api/documentation/on-street-parking/product-information/introduction

## What to request from a direct-data provider

Ask for a coverage map and a small de-identified timestamped sample before purchasing. Specify City of LA, Westwood if available, passenger-vehicle curb parking, both metered and unmetered, 5–15-minute resolution, historic samples plus live refresh if offered. Ask whether availability covers a complete block face, selected spaces, loading-only zones, or an inferred area. Request observed counts/capacity, arrivals/departures/dwell times where available, event and receipt times, outages, uncertainty, and effective restrictions.

Ask separately about academic-pilot pricing, retained history, forecasting-model training, storage, commercial app display, redistribution, and benchmark rights. A provider's observation fields and model probabilities must remain distinct. Do not assume that 400 blocks across 13 cities means 400 LA blocks, or that LA coverage means Westwood coverage. Do not ingest license plates or personal trip traces; aggregate counts suffice.

## Verified dead/limited leads

- The referenced LA City Events ID `rx9t-fp7k` returned HTTP 404 for both metadata and JSON on this check. Search-index snippets claiming a daily feed did not establish a working source. It was not replaced with invented rows.
- An earlier Code the Curb ArcGIS sandbox probe failed server-side. The CurbIQ LA page is a better access lead; it is not proof of access already granted.
- Citations sample query returned dated Westwood tickets, but that does not establish vehicle counts or a reporting-rate denominator.
- Consumer satellite imagery and old aerial mosaics do not provide current arrival-time outcomes.

## Added code and run instructions

Use the existing locked environment. On Windows:

```powershell
.\.venv\Scripts\la-parking.exe acquire-signals
# Deliberately fetch a new snapshot; default otherwise reuses cached requests:
.\.venv\Scripts\la-parking.exe acquire-signals --refresh
```

On Linux/macOS use `.venv/bin/la-parking`. Raw data stay outside Git; a new clone must run acquisition. Optional keys must be set in the process environment: this change does not add automatic .env loading. Never paste keys into tracked files or command arguments. Only TICKETMASTER_API_KEY and CURBIQ_TOKEN enable the optional connectors; the public sources need no new key. The user's Census key on another computer is not present in this workspace.

Sensor exports reconcile all source IDs against paginated geometry. CurbIQ capture is deliberately first-page-only, at most 100 rows, for schema and coverage review; it never auto-applies legal rules. Provider access was not tested without credentials.

`acquire-signals` records original request time and completed receipt time. Forecasts are normalized into immutable hashed snapshots. `signal-features` reads JSONL requests containing request_id, issued_at_utc, arrival_time_utc, latitude and longitude. Supply verified block-face representative points; this command does not geocode or establish city jurisdiction. Example:

```powershell
.\.venv\Scripts\la-parking.exe signal-features --requests data\signals\requests.jsonl --output data\signals\features.jsonl
```

The join uses only snapshots received by issue time, respects forecast issue/validity times, grid coverage and snapshot age, and limits event counts to a fully covered time window and stated radius. Event zeros mean no usable listed starts in that feed/window, not no activity. Unknown attendance, end times and missing inputs stay unknown. These features are not automatically added to or promoted by existing model runs: collect matched future outcomes, then compare a declared feature ablation against the locked baseline.

New outcome labels must remain outside reserved development holdouts. Predictor snapshots alone do not authorize opening those outcomes. No legacy R² can legitimately improve just because a current forecast or future event listing was downloaded.
