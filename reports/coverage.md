# Measured data coverage

Generated: 2026-10-25T03:32:19.432143+00:00. Storage times are UTC; local schedules use America/Los_Angeles.

City inventory: **81,315 segments / 162,630 faces** after jurisdiction clipping and source-join duplicate handling.
Westwood/UCLA pilot: **981 segments / 1,962 faces / 1,584 meters**. 84 faces use associated authoritative physical curb footprints; the remainder use approximate offsets.

Pilot meter joins: {'matched': 1562, 'ambiguous': 22}. No ambiguous assignment becomes a training label.
Current feed: 3,878 city sensor states, 132 pilot states. 3,700 city states exceed the unvalidated 15-minute freshness policy. Latest transaction: 2026-10-25 03:15:44+00:00.

**Verified unmetered occupancy labels: 0. Physical and eligible capacity remain unknown.**

| Archive month | Raw city events | Pilot events | Pilot sensor IDs | Actual pilot UTC span |
|---|---:|---:|---:|---|
| 2025_09 | 3,586,854 | 245,830 | 337 | 2025-09-02 07:00:01+00:00 to 2025-10-01 02:59:38+00:00 |
| 2026_08 | 3,409,053 | 126,313 | 140 | 2026-08-01 07:02:12+00:00 to 2026-09-01 06:58:59+00:00 |

| Source | Persistence cap (min) | Known fraction of expected sensor-time |
|---|---:|---:|
| ladot_archive_2025_09 | 5 | 5.8% |
| ladot_archive_2025_09 | 15 | 13.3% |
| ladot_archive_2025_09 | 60 | 32.3% |
| ladot_archive_2026_08 | 5 | 7.1% |
| ladot_archive_2026_08 | 15 | 16.4% |
| ladot_archive_2026_08 | 60 | 39.2% |

This fraction measures inferred state persistence under a policy, not verified continuous ground truth. Missing hours are not vacant hours.

| Pilot layer | Features | Invalid |
|---|---:|---:|
| curbs | 20,877 | 3 |
| driveways | 5,965 | 0 |
| hydrants | 763 | 0 |
| regulatory_signs | 907 | 0 |
| bikeways | 167 | 0 |
| red_curb | 12 | 0 |
| buildings | 10,447 | 0 |
| zoning | 738 | 0 |
| construction | 3,502 | 0 |
| construction_streets | 18 | 0 |

[Interactive coverage map](coverage_map.html). Full missingness, age, joins and sensitivity: `coverage.json`. Source status/terms: `../config/source_registry.json`.

- No verified unmetered occupancy labels.
- Current inventory is not historical supply; historical ID matches do not prove unchanged location.
- 15-minute persistence is an unvalidated sensitivity policy, not continuous sensor coverage.
- Block-face offsets are approximate except footprints passing documented curb coverage threshold.
- Legal eligible capacity is unavailable until exclusions, permits and full-duration restrictions are verified.
- Live SODA feeds have no transaction isolation; ordered pages and count checks do not detect all concurrent replacements.
