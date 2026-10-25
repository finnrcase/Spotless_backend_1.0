# Sensor label validity audit



No persistence cutoff is selected by prediction scores. No independent observations currently certify the reconstructed intervals.



| Month | Policy | Post-discovery sensor-time | Full-month retrospective roster | Supported rate bins | Common-bin label MAE versus 15m |

|---|---|---:|---:|---:|---:|

| 2025_09 | ttl_5m | 5.958% | 5.905% | 6922 | 0.0793 |

| 2025_09 | ttl_15m | 13.622% | 13.483% | 28368 | 0.0000 |

| 2025_09 | ttl_60m | 33.519% | 32.970% | 68359 | 0.0696 |

| 2025_09 | ttl_180m | 58.580% | 57.322% | 98596 | 0.1021 |

| 2025_09 | next_event_state_change_hypothesis | 100.000% | 96.253% | 121440 | 0.1358 |

| 2026_08 | ttl_5m | 7.380% | 7.351% | 6702 | 0.0847 |

| 2026_08 | ttl_15m | 16.926% | 16.874% | 21999 | 0.0000 |

| 2026_08 | ttl_60m | 40.130% | 40.128% | 47301 | 0.0723 |

| 2026_08 | ttl_180m | 64.208% | 64.254% | 62033 | 0.1087 |

| 2026_08 | next_event_state_change_hypothesis | 100.000% | 99.093% | 73728 | 0.1409 |



The field is an occupancy transaction timestamp, not a documented reporting heartbeat.

Every UNKNOWN or same-timestamp conflict terminates a known interval; no forward/back-fill through it.

Long unchanged periods cannot be certified from sparse events alone. State-change semantics are plausible, but no policy is independently validated.

Coverage depends on denominator: full-month retrospective roster and causal post-discovery roster are reported separately.

Changing the cap changes the target and missingness population. Label disagreement and primary-target selection effects are reported; R2 is not used to choose a cap.

All subsequent model-version comparisons retain identical v1 15-minute targets and frozen test identities.



The unbounded next-event row is a diagnostic state-change hypothesis. It is not promoted to ground truth. Silent sensor-days are reporting gaps, not proof of outages or vacancy. Current mapping is later-vintage and event delivery time remains unverified.
