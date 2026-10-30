# Verdict pipeline: dev-r

Runs: dev-s1-r, dev-s2-r. Void (C8): none.

## Verdict lines (section 2)

- **Edge forecasting is valuable**: no
- **Online learning is justified**: no
- **The agent layer is justified**: no

## C1 accuracy
C1 holds: 3 of 5 streams pass.

| stream | pass | best River model | h (s) | pooled skill [95% CI] | per-seed mean ± sd |
|---|---|---|---|---|---|
| pressure | no | lin_lag | 60 | +0.015 [+0.010, +0.021] | +0.015 ± 0.013 |
| solar | no | clearsky_adapt | 300 | +0.027 [+0.020, +0.036] | +0.026 ± 0.006 |
| temp | yes | lin_rls_slow | 3600 | +0.482 [+0.424, +0.541] | +0.482 ± 0.001 |
| vibration | yes | lin_lag_reset | 1 | +0.301 [+0.286, +0.316] | +0.300 ± 0.029 |
| wind | yes | holt | 30 | +0.254 [+0.250, +0.257] | +0.253 ± 0.005 |

## C2 resource budget
C2 holds: mean 0.024 core, max RSS 256.7 MB, p99 step 21.82 ms, compression >= 60x: yes.

## C3 recovery
C3 does not hold. Backfill strategy taken for link-ups: base-sorted.

| stream / event | pooled events (max) | best median (min) | pass |
|---|---|---|---|
| pressure/drift_end | 3 | 6.3 | yes |
| pressure/front | 6 | 24.9 | no |
| pressure/outage_end | 58 | 0.9 | yes |
| pressure/step | 8 | 47.0 | no |
| solar/drift_end | 11 | 24.5 | no |
| solar/outage_end | 58 | 21.0 | no |
| solar/step | 3 | 48.6 | no |
| temp/drift_end | 4 | 5.6 | yes |
| temp/outage_end | 58 | 1.0 | yes |
| temp/step | 4 | 6.0 | yes |
| vibration/drift_end | 6 | 0.4 | yes |
| vibration/outage_end | 58 | 22.9 | no |
| vibration/step | 3 | 3.8 | yes |
| wind/drift_end | 4 | 3.8 | yes |
| wind/outage_end | 58 | 5.8 | yes |
| wind/step | 10 | 0.7 | yes |

Edge control at the same link-ups: 6 of 19 (stream, horizon) rows pass.

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
| base-arrival/outage | 0.956 |
| base-arrival/post | 1.007 |
| base-ignore/normal | 1.001 |
| base-ignore/outage | 0.882 |
| base-ignore/post | 1.021 |
| base-sorted/normal | 1.0 |
| base-sorted/outage | 0.949 |
| base-sorted/post | 0.992 |

Soft target (best strategy within 10 % after the first 10 min): met (base-sorted).

## C7 reproducibility
not run (no replicate pairs)

## C8 integrity
- dev-s1-r: ok
- dev-s2-r: ok
