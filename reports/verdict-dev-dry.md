# Verdict pipeline: dev-dry

Runs: dev-s1-drift, dev-s2-drift, dev-s3. Void (C8): dev-s2-drift.

## Verdict lines (section 2)

- **Edge forecasting is valuable**: no
- **Online learning is justified**: no
- **The agent layer is justified**: no

## C1 accuracy
C1 holds: 3 of 5 streams pass.

| stream | pass | best River model | h (s) | pooled skill [95% CI] | per-seed mean ± sd |
|---|---|---|---|---|---|
| pressure | no | lin_lag | 60 | +0.011 [+0.006, +0.015] | +0.010 ± 0.008 |
| solar | no | snarimax | 5 | +0.018 [+0.015, +0.022] | +0.018 ± 0.002 |
| temp | yes | lin_lag | 3600 | +0.462 [+0.417, +0.507] | +0.462 ± 0.071 |
| vibration | yes | lin_lag_reset | 1 | +0.278 [+0.265, +0.292] | +0.278 ± 0.002 |
| wind | yes | holt | 30 | +0.263 [+0.260, +0.266] | +0.260 ± 0.014 |

## C2 resource budget
C2 not measured (no 1x run given); compression >= 60x: yes. C2 does not hold.

## C3 recovery
C3 does not hold. Backfill strategy taken for link-ups: base-ignore.

| stream / event | pooled events (max) | best median (min) | pass |
|---|---|---|---|
| pressure/drift_end | 5 | 15.3 | no |
| pressure/front | 4 | 14.6 | yes |
| pressure/outage_end | 56 | 0.9 | yes |
| pressure/step | 6 | 22.0 | no |
| solar/drift_end | 5 | 1.3 | yes |
| solar/outage_end | 56 | 30.0 | no |
| solar/step | 4 | 2.0 | yes |
| temp/drift_end | 7 | 5.9 | yes |
| temp/outage_end | 56 | 12.3 | yes |
| temp/step | 2 | 30.1 | no (too few, not judged) |
| vibration/drift_end | 4 | 6.2 | yes |
| vibration/outage_end | 56 | 31.4 | no |
| vibration/step | 4 | 21.3 | no |
| wind/drift_end | 4 | 0.6 | yes |
| wind/outage_end | 56 | 11.1 | yes |
| wind/step | 9 | 1.0 | yes |

Edge control at the same link-ups: 3 of 19 (stream, horizon) rows pass.

## C4 online vs static
C4 does not hold: lin_lag passes on no stream.

## C5 agent lift
- C5A: not run
- C5B: not run
- C5C: not run

## C6 outage degradation (median MAE ratio base / edge)

| arm / phase | ratio |
|---|---|
| base-arrival/normal | 1.0 |
| base-arrival/outage | 0.921 |
| base-arrival/post | 1.012 |
| base-ignore/normal | 1.001 |
| base-ignore/outage | 0.905 |
| base-ignore/post | 1.021 |
| base-sorted/normal | 1.0 |
| base-sorted/outage | 1.005 |
| base-sorted/post | 0.983 |

Soft target (best strategy within 10 % after the first 10 min): met (base-sorted).

## C7 reproducibility
not run (no replicate pairs)

## C8 integrity
- dev-s1-drift: ok
- dev-s2-drift: VOID {"temp": -1090600, "pressure": -1085446, "wind": -2176906, "vibration": -10890240, "solar": -545300}
- dev-s3: ok
