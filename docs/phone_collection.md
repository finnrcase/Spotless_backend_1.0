# Phone collection workflow

For the smallest useful first batch, open `reports/field_route.html` and tap **Start smallest batch: 8 counts over 1 hour**. It fills two sides of one development block at 0/15/30/60 minutes. Verify actual unmetered status; no linked meter is not proof. Record actual times and skip reasons, export JSONL, then import/review before training. This checks collection quality and changes only, and cannot validate prediction accuracy. See [the temporal experiment and prospective holdout](temporal_v2.md).

The collector is a self-contained local HTML file built from the existing real Westwood/UCLA inventory. It loads 1,962 pilot faces, source-side diagrams and snapshot evidence support. It has no external scripts, analytics, account, fetch calls or automatic uploads. No website has been published.

## Prepare on the computer

```powershell
.\.venv\Scripts\la-parking.exe collector
```

Open `reports/collector.html`, or transfer **that single file** to the phone using your normal file transfer method. It contains the form, styling, logic and pilot inventory. Open it in a full browser that executes local HTML. Some mobile Files/Quick Look viewers show a preview without JavaScript: if the street list does not load, use a browser or the local-network option below. Opening the same file under another path/browser can create a separate device-storage area; export after every walk.

For an optional private local-network visit, serve **only the reports directory**, not the repository:

```powershell
.\.venv\Scripts\python.exe -m http.server 8765 --bind 0.0.0.0 --directory reports
```

On the phone, while connected to the same local network, open `http://<computer-LAN-IP>:8765/collector.html`. Stop the server after transferring/using the file; do not configure port forwarding. This is not public deployment. This page still saves observations only on the phone, not to the server. On plain LAN HTTP, phone GPS will generally be unavailable; use the explicit confirmed-face pin workflow. Browsers restrict GPS to secure contexts such as HTTPS/localhost, and the phone's `localhost` is the phone itself. [Browser location requirements](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition), [secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts).

This release deliberately supports local-file/manual-pin collection without relying on a hosted HTTPS origin. It is not an installed PWA or background synchronization system. Actual phone/browser behavior has to be checked on your device; desktop Chrome mobile-sized QA does not substitute for an iPhone/Android field trial. If your phone cannot open local HTML, the LAN option works while connected; remote standalone GPS-enabled use would require a later authorized HTTPS hosting choice or native packaging.

## Record a visit

1. Search for a street or use a fresh GPS fix when available. Choose the street side; confirm its source diagram, coordinates and physical endpoints on foot. The approximate compass label does not replace side verification. Campus/private roads require separate public-parking review.
2. Confirm metered/unmetered/mixed status in person. Absence of linked meters is not proof of unmetered parking. Enter an observer nickname. Use GPS (30 m accuracy or better) or explicitly confirm the selected face's pin. Pins are recorded as assumed coordinates with no GPS accuracy and require location review.
3. Start a snapshot and inspect the whole face within 15 minutes. Count occupied vehicle-sized positions, empty suitable positions and empty unsuitable positions; independently check their total. Unknown counts remain blank. Zero means a checked count of zero. A partial view can be saved with nullable counts, but is not a full-face label.
4. Record intended stay, vehicle/permit class, capacity method, sampling stratum and notes. Check the rules box only after reviewing posted/temporary restrictions for that interval and eligibility. Estimated unmarked positions remain capacity assumptions, not verified marked-space counts.
5. Save. Drafts and observations persist in browser storage when available; storage failures are shown and records can still be exported while the page remains open. Starting another observation does not overwrite a saved one.
6. Export JSONL after every walk; verify the file exists in Downloads/Files. Share is available when the browser supports file sharing. Export does not delete the device copy. A backup can be restored without duplicating identical IDs; conflicting IDs are rejected.

## Import and review

Transfer the JSONL file back to this project and run:

```powershell
.\.venv\Scripts\la-parking.exe observations path\to\spotless-observations-YYYY-MM-DD.jsonl
```

Python validates the contract, counts, timestamps, known face, spatial distance and duplicates. Accepted records go to `data/observations/manual_observations.parquet`; reasons for rejections go to `last_intake_report.json`. A confirmed map pin sets `location_review_required`; uncertain rules, estimated/unknown capacity or partial coverage set `label_review_required`. Successful import is not automatic approval as model ground truth. Previously imported older records default to unknown parking type and unchecked rules.

Use the new [concrete field route](../reports/field_route.md) and `reports/field_route.html` for the first small batch: route links fill the face, session and assignment automatically. The form now also preserves raw gap lengths (blank=unmeasured, 0=checked and none), counting convention, obstructed curb length and exclusion notes. Gap lengths do not become stalls automatically. Confirm physical endpoints and sides before counting. See [the continuation guide](starter_continuation.md).

Plan repeated visits across weekday/weekend, morning/midday/evening and residential/commercial/campus-edge settings. Keep missed visits/reasons and a subset of complete physical blocks and later dates untouched for final evaluation. Use independent repeat counts to estimate observer disagreement. Do not choose only easy/high-availability streets or tune the test set toward a desired score. No fixed R² target applies.

The form now also records sampling method, observer-rated confidence, observed restriction text and optional measured usable curb length/method. `la-parking survey-plan` generates **planned assignments, not observations**: 24 randomly sampled physical blocks, 12 randomized visits each over 14 days (288 visits), with six blocks reserved for geographic holdout. Inspect public access and field parking type before executing the plan; do not infer unmetered status from missing meter inventory. Add independent duplicate counts to about 10% of visits.

Treat that as a variability pilot. Repeats on 24 blocks do not yield 288 independent blocks. For a binary availability proportion, a worst-case independent-sample approximation needs roughly 97 independent units for a 95% margin of ±10 percentage points; inflate using measured block/day correlation and nonresponse. Expand distinct blocks, neighborhoods and time strata according to observed variance, desired precision, class imbalance and uncertainty in held-out metrics. R² requires empirical learning curves and independent test blocks rather than a fixed sample-size promise. There is no fixed R2 target; earlier rough ranges are not measured benchmarks.
