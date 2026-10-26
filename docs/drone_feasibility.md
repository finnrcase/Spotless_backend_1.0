# Offline drone collection feasibility

The mechanism being tested is whether repeated overhead views could provide enough **reviewed, visible curb observations per operator hour** to improve arrival forecasts. The evidence gap is modern timestamped, geolocated, independently reviewed imagery. The smallest experiment is offline route arithmetic plus a matched capture study; the app has no autonomous collection service or aircraft control path.

`la-parking drone-feasibility` reads the existing 16-face development plan and inventory geometry. It does not change reservations, collect labels, retrain models or modify serving. Results in [simulation.md](../reports/drone_feasibility/simulation.md), [simulation.json](../reports/drone_feasibility/simulation.json) and [sensitivity.json](../reports/drone_feasibility/sensitivity.json) are **simulated**, not observed productivity or detector performance.

## Reproduce

```powershell
.\.venv\Scripts\la-parking.exe drone-feasibility
.\.venv\Scripts\python.exe -m pytest -q tests/test_drone_feasibility.py
```

Change `config/drone_feasibility.json` or pass `--config <file> --output <directory>`. Camera sensor/focal geometry, image dimensions, altitude, speed, capture interval, battery duration/reserve, turnaround, overhead, occlusion and operator/review time are configurable. The geometric footprint is altitude × sensor dimension / focal length. Nominal GSD is footprint / pixels; this is a camera assumption, not source raster metadata or evidence of resolvable vehicles. Different pixel pitches/crops must be corrected for real hardware.

The fixed launch point is the first face's start. An order-preserving greedy allocator permits multiple sorties and requires return-to-home within the usable battery budget. Straight transits and curb polylines ignore obstacles, turning/acceleration, VLOS, wind, radio, people, vehicles and airspace; their travel times can be optimistic. A polygon uses a documented approximate street offset. No route is a flight-safe corridor. Repositioning the launch point is not modeled. Camera footprints intersect a one-dimensional curb; lateral positioning error is not modeled. Capture-time coverage uses the trigger clock, rather than assuming every traveled meter is photographed.

Raw service frames and unique face visits are reported separately. Mean visible area applies configured tree/shadow losses **only to the visited faces**; an additional all-requested-faces statistic assigns zero coverage to infeasible faces. Hidden curb remains unknown. Full-face usable-count probability is a separate unmeasured input: it cannot be inferred from mean visible area. The sensitivity report varies it separately. No CV results, legal vacancy counts or downstream forecast gain are fabricated.

At the recorded default settings, 10/16 requested faces fit three simulated sorties; six are out of reach from the fixed home. The covered subset's cycle is about 45.94 minutes (49.94 including the next turnaround), but none of the 15/30/60-minute **full-route** revisit criteria pass because six faces are missing. The assumed 0.30 full-face visibility probability yields about 2.22 usable counts/operator hour. This is an assumption-driven estimate, not a reason to prefer a drone over walking. Narrow paired routes or multiple launch sites would be a separate experiment.

## Pinned mission prototype and actual execution limit

Official release metadata checked on 2026-10-26 identifies [PX4 v1.17.0](https://github.com/PX4/PX4-Autopilot/releases/tag/v1.17.0) and [MAVSDK 4.0.6](https://pypi.org/project/mavsdk/4.0.6/). The PX4 annotated-tag object SHA and MAVSDK Windows wheel SHA-256 are pinned in the config. The tag-object SHA is not presented as a source commit SHA. The optional dependency is isolated in `requirements-drone.txt`; it is not part of the app environment or serving imports. MAVSDK v4 uses its current C++ bindings; old `mavsdk_grpc` examples are not interchangeable. See the [official Python QuickStart](https://mavsdk.mavlink.io/main/en/python/quickstart.html).

`mission_preview()` relocates one sortie's relative shape to an explicitly synthetic test-field home. `build_sdk_plan()` constructs pinned `MissionItem`/`MissionPlan` objects and serializes their C structs, including takeoff/land and interval-camera actions. It never creates an SDK vehicle, socket, connection, upload or arm command. Real Westwood coordinates are not emitted as a flyable mission. Both `real_aircraft_enabled=true` and any transport other than `disabled` are rejected. There is no real-flight override.

For the recorded local check, the official 6,553,825-byte Windows wheel was hash-verified and unpacked under ignored `data/drone_feasibility/runtime`; `--validate-sdk` successfully constructed 153 mission items. On a fresh machine an optional isolated environment can install `requirements-drone.txt` before running the same check. Core `uv sync --frozen` does not install it.

**PX4/Gazebo SITL execution is blocked here:** Docker/PX4/Gazebo are not configured, and the installed WSL launcher reports that WSL is not installed. No MAVLink flight or physics simulation ran. Use a dedicated simulation-only Linux lab following the [PX4 v1.17 Gazebo instructions](https://docs.px4.io/v1.17/en/sim_gazebo_gz/), check out the pinned release recursively, and build `make px4_sitl gz_x500`. Before any future upload runner is implemented, require a simulation vehicle identity check and an isolated loopback endpoint; a loopback address alone cannot prove the other end is SITL. Verify camera-command support and actual triggers, mission acceptance, geofence, battery failsafe/return and logs there. Constructing SDK objects proves API compatibility only, not PX4 mission acceptance or camera/hardware compatibility.

## Matched collection comparison

Use the existing [development schedule](../reports/collection/development_plan.json), not held-out blocks/sessions. Start with two nearby development faces at 0/15/30/60 minutes. Expand only after review feasibility is demonstrated. Compare three modalities on the same face, visible curb scope, timestamps (target within 30 seconds), lighting and restriction profile: manual count, walking/passenger-operated ground camera, and an overhead capture **only if an independently approved operation becomes available**. Until then drone outcomes remain unavailable; simulator values must never enter the measured table.

Have two independent reviewers count the same visible scope, blind to each other and detector proposals; adjudicate disagreement without averaging detections. A separate contemporaneous full-face walk establishes the reference count, verified capacity and sign evidence. Do not use a modality's own count as its reference. Log movements between asynchronous captures; exclude noncomparable pairs with a reason and report their coverage. Match by physical face/session/repeat offset, deduplicate adjacent frames into one sample unit, and retain hidden areas as unknown. Record all operator time, including travel/setup, flight supervision, review and failed captures. Use [the import/review workflow](capture_collection.md) for each modality; no plates or personal identifiers are needed.

| Decision criterion | Measured comparison after capture | Current result |
|---|---|---|
| Count error | MAE/bias on common visible scope vs independent reference; block/day intervals | Unavailable |
| Visible curb coverage | Reviewed visible meters / physical curb meters; full-face completion and missingness by occlusion/type | Unavailable |
| Operator cost | Unique reviewed usable face-visits / all operator hours, acquisition bytes, review latency and failures | Unavailable; simulator separate |
| Forecast value | Frozen A/B/C/D recent-observation comparison on identical direct targets, 15/30/60 minutes; RMSE, MAE, legal-vacancy Brier/calibration | Unavailable |

Use validation for decisions and leave reserved outcomes closed. Predeclare a review budget and minimum usable paired observations before capture; the first eight paired face-visits establish workflow feasibility, not reliable accuracy or statistical power. Prefer manual/ground capture unless overhead collection adds measured useful coverage or forecast value after its operational and review costs. No new model architecture is justified by route simulation alone.

## Hardware and route-specific decisions for a qualified pilot

This repository supplies no operational approval. A qualified pilot must resolve the actual aircraft/autopilot firmware (PX4 support is not universal across consumer drones), payload/camera trigger and EXIF clock/GNSS accuracy, rolling shutter/motion blur, gimbal/nadir calibration, focal crop/GSD, radio link/mission limits, geofence, safe launch/recovery, tested endurance/reserve and lost-link behavior. Camera missions must be verified against actual hardware, not merely SDK enum availability.

Before any specific Westwood operation, the pilot must check the exact route/date/altitude against current airspace, LAANC/FAA authorization requirements, NOTAMs/TFRs, VLOS and weather, and determine applicable registration/Remote ID, pilot qualifications and waivers. FAA [LAANC authorization](https://www.faa.gov/uas/getting_started/laanc) does not replace other requirements; operations around pedestrians and moving traffic need their own assessment under the [operations-over-people/vehicles rules](https://www.faa.gov/uas/commercial_operators/operations_over_people). Check [Remote ID requirements](https://www.faa.gov/uas/getting_started/remote_id) for the actual aircraft and operation.

Resolve landowner launch/recovery permission, any City right-of-way or filming requirements for the actual activity, privacy/data retention, insurance and UCLA's designated local authority if campus property or activity is involved. [UC UAS policy](https://policy.ucop.edu/doc/3500671/Drone) and [UC program guidance](https://www.ucop.edu/safety-and-loss-prevention/environmental/program-resources/unmanned-aircraft-systems-safety.html) are starting points, not approval of this route. No permissions have been obtained and no request has been sent.
