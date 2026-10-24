# C3 recovery, dev-s3 (seed 3, 7 days, scored after the 2-day warm-up), `dev`

Generated with `python -m skylink.analysis --run dev-s3 --seed 3 --recovery --arm <arm>`. Best model per stream, horizon and event kind
(the minimum over all models of that arm). `river` = edge arm; at `outage_end` it is the control (the edge never sees the outage).

## river

| stream | model | h (s) | event | n | censored | median recovery (min) | C3 rule |
|---|---|---|---|---|---|---|---|
| pressure | seasonal_naive | 60 | drift_end | 5 | 0 | 0.3 | pass |
| pressure | seasonal_naive | 60 | front | 3 | 0 | 0.4 | pass |
| pressure | seasonal_naive | 60 | outage_end | 27 | 13 | 1.0 | pass |
| pressure | seasonal_naive | 600 | drift_end | 5 | 0 | 0.3 | pass |
| pressure | seasonal_naive | 600 | front | 3 | 0 | 0.4 | pass |
| pressure | seasonal_naive | 600 | outage_end | 27 | 13 | 1.0 | pass |
| pressure | seasonal_naive | 3600 | drift_end | 5 | 0 | 0.3 | pass |
| pressure | seasonal_naive | 3600 | front | 3 | 0 | 0.4 | pass |
| pressure | seasonal_naive | 3600 | outage_end | 27 | 13 | 1.0 | pass |
| solar | lin_lag_adwin | 5 | outage_end | 27 | 6 | 0.9 | pass |
| solar | seasonal_naive | 5 | step | 3 | 1 | 1.0 | pass |
| solar | holt | 30 | outage_end | 27 | 9 | 0.9 | pass |
| solar | seasonal_anchor | 30 | step | 3 | 0 | 0.4 | pass |
| solar | holt | 60 | outage_end | 27 | 9 | 0.9 | pass |
| solar | seasonal_anchor | 60 | step | 3 | 0 | 0.4 | pass |
| solar | hat | 300 | outage_end | 27 | 8 | 0.9 | pass |
| solar | seasonal_anchor | 300 | step | 3 | 0 | 0.4 | pass |
| temp | seasonal_naive | 10 | drift_end | 4 | 0 | 0.7 | pass |
| temp | hat | 10 | outage_end | 27 | 2 | 0.9 | pass |
| temp | seasonal_anchor | 10 | step | 1 | 0 | 5.5 | pass |
| temp | seasonal_naive | 60 | drift_end | 4 | 0 | 0.7 | pass |
| temp | persistence | 60 | outage_end | 27 | 4 | 40.1 | fail |
| temp | seasonal_anchor | 60 | step | 1 | 0 | 32.5 | fail |
| temp | seasonal_naive | 600 | drift_end | 4 | 0 | 0.7 | pass |
| temp | seasonal_anchor | 600 | outage_end | 27 | 6 | 44.4 | fail |
| temp | lin_lag_reset | 600 | step | 1 | 0 | 43.5 | fail |
| temp | seasonal_naive | 3600 | drift_end | 4 | 0 | 0.7 | pass |
| temp | persistence | 3600 | outage_end | 27 | 7 | 0.9 | pass |
| temp | hat | 3600 | step | 1 | 1 | never | fail |
| vibration | persistence | 1 | drift_end | 3 | 0 | 0.6 | pass |
| vibration | seasonal_anchor | 1 | outage_end | 27 | 1 | 0.9 | pass |
| vibration | snarimax | 1 | step | 2 | 0 | 42.7 | fail |
| vibration | holt | 5 | drift_end | 3 | 0 | 6.0 | pass |
| vibration | seasonal_naive | 5 | outage_end | 27 | 6 | 49.9 | fail |
| vibration | snarimax | 5 | step | 2 | 0 | 54.2 | fail |
| vibration | holt | 30 | drift_end | 3 | 0 | 7.0 | pass |
| vibration | holt | 30 | outage_end | 27 | 6 | 47.7 | fail |
| vibration | hat | 30 | step | 2 | 2 | never | fail |
| vibration | holt | 120 | drift_end | 3 | 0 | 8.0 | pass |
| vibration | seasonal_naive | 120 | outage_end | 27 | 6 | 49.9 | fail |
| vibration | hat | 120 | step | 2 | 1 | never | fail |
| wind | hat | 1 | drift_end | 4 | 0 | 0.6 | pass |
| wind | seasonal_anchor | 1 | outage_end | 27 | 4 | 0.9 | pass |
| wind | lin_lag | 1 | step | 3 | 0 | 0.7 | pass |
| wind | persistence | 5 | drift_end | 4 | 0 | 0.6 | pass |
| wind | persistence | 5 | outage_end | 27 | 6 | 5.1 | pass |
| wind | persistence | 5 | step | 3 | 0 | 1.0 | pass |
| wind | seasonal_naive | 30 | drift_end | 4 | 1 | 0.8 | pass |
| wind | seasonal_naive | 30 | outage_end | 27 | 9 | 19.1 | fail |
| wind | seasonal_anchor | 30 | step | 3 | 0 | 5.0 | pass |
| wind | seasonal_naive | 120 | drift_end | 4 | 1 | 0.8 | pass |
| wind | seasonal_naive | 120 | outage_end | 27 | 9 | 19.1 | fail |
| wind | persistence | 120 | step | 3 | 0 | 6.5 | pass |

## base-arrival

| stream | model | h (s) | event | n | censored | median recovery (min) | C3 rule |
|---|---|---|---|---|---|---|---|
| pressure | lin_lag | 60 | drift_end | 3 | 1 | 47.3 | fail |
| pressure | holt | 60 | front | 3 | 0 | 53.4 | fail |
| pressure | lin_lag | 60 | outage_end | 25 | 4 | 50.5 | fail |
| pressure | persistence | 600 | drift_end | 3 | 1 | 15.3 | fail |
| pressure | lin_lag | 600 | front | 3 | 1 | 33.1 | fail |
| pressure | lin_lag | 600 | outage_end | 25 | 11 | 55.9 | fail |
| pressure | holt | 3600 | drift_end | 3 | 3 | never | fail |
| pressure | holt | 3600 | front | 3 | 1 | 36.4 | fail |
| pressure | lin_lag | 3600 | outage_end | 25 | 5 | 0.9 | pass |
| solar | persistence | 5 | outage_end | 25 | 6 | 8.3 | pass |
| solar | persistence | 5 | step | 3 | 0 | 6.0 | pass |
| solar | persistence | 30 | outage_end | 25 | 6 | 19.4 | fail |
| solar | persistence | 30 | step | 3 | 0 | 6.0 | pass |
| solar | persistence | 60 | outage_end | 25 | 6 | 26.9 | fail |
| solar | holt | 60 | step | 3 | 0 | 7.0 | pass |
| solar | persistence | 300 | outage_end | 25 | 7 | 29.9 | fail |
| solar | holt | 300 | step | 3 | 1 | 9.0 | pass |
| temp | persistence | 10 | drift_end | 4 | 0 | 39.9 | fail |
| temp | persistence | 10 | outage_end | 25 | 3 | 19.0 | fail |
| temp | holt | 60 | drift_end | 3 | 2 | never | fail |
| temp | persistence | 60 | outage_end | 25 | 4 | 36.0 | fail |
| temp | lin_lag | 600 | drift_end | 3 | 1 | 56.9 | fail |
| temp | persistence | 600 | outage_end | 25 | 4 | 47.9 | fail |
| temp | holt | 3600 | drift_end | 3 | 1 | 51.4 | fail |
| temp | persistence | 3600 | outage_end | 25 | 5 | 0.9 | pass |
| vibration | persistence | 1 | drift_end | 3 | 0 | 0.6 | pass |
| vibration | persistence | 1 | outage_end | 25 | 1 | 2.1 | pass |
| vibration | holt | 1 | step | 2 | 2 | never | fail |
| vibration | holt | 5 | drift_end | 3 | 0 | 6.0 | pass |
| vibration | persistence | 5 | outage_end | 25 | 5 | 46.1 | fail |
| vibration | holt | 5 | step | 2 | 2 | never | fail |
| vibration | holt | 30 | drift_end | 3 | 0 | 7.0 | pass |
| vibration | holt | 30 | outage_end | 25 | 5 | 46.4 | fail |
| vibration | holt | 30 | step | 2 | 2 | never | fail |
| vibration | holt | 120 | drift_end | 3 | 0 | 8.0 | pass |
| vibration | holt | 120 | outage_end | 25 | 5 | 47.7 | fail |
| vibration | holt | 120 | step | 2 | 2 | never | fail |
| wind | persistence | 1 | drift_end | 2 | 0 | 27.8 | fail |
| wind | persistence | 1 | outage_end | 25 | 6 | 3.6 | pass |
| wind | lin_lag | 1 | step | 3 | 0 | 0.7 | pass |
| wind | persistence | 5 | drift_end | 2 | 0 | 27.8 | fail |
| wind | persistence | 5 | outage_end | 25 | 6 | 15.4 | fail |
| wind | persistence | 5 | step | 3 | 0 | 1.0 | pass |
| wind | persistence | 30 | drift_end | 2 | 0 | 29.8 | fail |
| wind | holt | 30 | outage_end | 25 | 5 | 39.1 | fail |
| wind | holt | 30 | step | 3 | 0 | 6.0 | pass |
| wind | persistence | 120 | drift_end | 2 | 0 | 31.8 | fail |
| wind | persistence | 120 | outage_end | 27 | 8 | 30.4 | fail |
| wind | persistence | 120 | step | 3 | 0 | 6.5 | pass |

## base-sorted

| stream | model | h (s) | event | n | censored | median recovery (min) | C3 rule |
|---|---|---|---|---|---|---|---|
| pressure | lin_lag | 60 | drift_end | 3 | 1 | 47.3 | fail |
| pressure | persistence | 60 | front | 3 | 0 | 25.1 | fail |
| pressure | lin_lag | 60 | outage_end | 25 | 4 | 47.5 | fail |
| pressure | persistence | 600 | drift_end | 4 | 1 | 15.3 | fail |
| pressure | holt | 600 | front | 3 | 0 | 34.1 | fail |
| pressure | lin_lag | 600 | outage_end | 25 | 11 | 55.9 | fail |
| pressure | holt | 3600 | drift_end | 5 | 4 | never | fail |
| pressure | holt | 3600 | front | 3 | 2 | never | fail |
| pressure | lin_lag | 3600 | outage_end | 26 | 2 | 0.9 | pass |
| solar | persistence | 5 | outage_end | 25 | 6 | 8.3 | pass |
| solar | persistence | 5 | step | 3 | 0 | 6.0 | pass |
| solar | persistence | 30 | outage_end | 25 | 6 | 19.4 | fail |
| solar | persistence | 30 | step | 3 | 0 | 6.0 | pass |
| solar | persistence | 60 | outage_end | 25 | 6 | 26.9 | fail |
| solar | holt | 60 | step | 3 | 0 | 7.0 | pass |
| solar | persistence | 300 | outage_end | 25 | 7 | 29.9 | fail |
| solar | holt | 300 | step | 3 | 1 | 9.0 | pass |
| temp | persistence | 10 | drift_end | 4 | 0 | 5.7 | pass |
| temp | persistence | 10 | outage_end | 25 | 2 | 19.0 | fail |
| temp | holt | 60 | drift_end | 3 | 2 | never | fail |
| temp | persistence | 60 | outage_end | 25 | 4 | 36.0 | fail |
| temp | lin_lag | 600 | drift_end | 3 | 1 | 56.9 | fail |
| temp | persistence | 600 | outage_end | 25 | 4 | 47.9 | fail |
| temp | holt | 3600 | drift_end | 3 | 2 | never | fail |
| temp | persistence | 3600 | outage_end | 26 | 2 | 0.9 | pass |
| temp | holt | 3600 | step | 1 | 1 | never | fail |
| vibration | persistence | 1 | drift_end | 3 | 0 | 0.6 | pass |
| vibration | persistence | 1 | outage_end | 25 | 0 | 0.9 | pass |
| vibration | holt | 1 | step | 2 | 2 | never | fail |
| vibration | holt | 5 | drift_end | 3 | 0 | 6.0 | pass |
| vibration | persistence | 5 | outage_end | 25 | 5 | 46.1 | fail |
| vibration | holt | 5 | step | 2 | 2 | never | fail |
| vibration | holt | 30 | drift_end | 3 | 0 | 7.0 | pass |
| vibration | holt | 30 | outage_end | 25 | 5 | 46.4 | fail |
| vibration | holt | 30 | step | 2 | 2 | never | fail |
| vibration | holt | 120 | drift_end | 3 | 0 | 8.0 | pass |
| vibration | holt | 120 | outage_end | 25 | 5 | 47.7 | fail |
| vibration | holt | 120 | step | 2 | 2 | never | fail |
| wind | persistence | 1 | drift_end | 2 | 0 | 27.8 | fail |
| wind | persistence | 1 | outage_end | 25 | 5 | 2.9 | pass |
| wind | lin_lag | 1 | step | 3 | 0 | 0.7 | pass |
| wind | persistence | 5 | drift_end | 2 | 0 | 27.8 | fail |
| wind | persistence | 5 | outage_end | 25 | 5 | 15.4 | fail |
| wind | persistence | 5 | step | 3 | 0 | 1.0 | pass |
| wind | persistence | 30 | drift_end | 2 | 0 | 29.8 | fail |
| wind | holt | 30 | outage_end | 25 | 5 | 39.1 | fail |
| wind | holt | 30 | step | 3 | 0 | 6.0 | pass |
| wind | persistence | 120 | drift_end | 2 | 0 | 31.8 | fail |
| wind | persistence | 120 | outage_end | 25 | 8 | 30.4 | fail |
| wind | persistence | 120 | step | 3 | 0 | 6.5 | pass |

## base-ignore

| stream | model | h (s) | event | n | censored | median recovery (min) | C3 rule |
|---|---|---|---|---|---|---|---|
| pressure | lin_lag | 60 | drift_end | 3 | 1 | 48.3 | fail |
| pressure | holt | 60 | front | 3 | 0 | 53.4 | fail |
| pressure | lin_lag | 60 | outage_end | 25 | 4 | 47.5 | fail |
| pressure | persistence | 600 | drift_end | 3 | 1 | 15.3 | fail |
| pressure | lin_lag | 600 | front | 3 | 1 | 33.1 | fail |
| pressure | holt | 600 | outage_end | 25 | 11 | 54.5 | fail |
| pressure | holt | 3600 | drift_end | 3 | 3 | never | fail |
| pressure | holt | 3600 | front | 3 | 1 | 36.4 | fail |
| pressure | lin_lag | 3600 | outage_end | 25 | 6 | 0.9 | pass |
| solar | persistence | 5 | outage_end | 25 | 6 | 8.3 | pass |
| solar | persistence | 5 | step | 3 | 0 | 6.0 | pass |
| solar | persistence | 30 | outage_end | 25 | 6 | 19.4 | fail |
| solar | persistence | 30 | step | 3 | 0 | 6.0 | pass |
| solar | persistence | 60 | outage_end | 25 | 6 | 26.9 | fail |
| solar | persistence | 60 | step | 3 | 0 | 7.0 | pass |
| solar | persistence | 300 | outage_end | 25 | 7 | 29.9 | fail |
| solar | holt | 300 | step | 3 | 1 | 10.0 | pass |
| temp | persistence | 10 | drift_end | 4 | 0 | 19.9 | fail |
| temp | persistence | 10 | outage_end | 25 | 3 | 19.0 | fail |
| temp | holt | 60 | drift_end | 4 | 2 | never | fail |
| temp | persistence | 60 | outage_end | 25 | 4 | 36.0 | fail |
| temp | lin_lag | 600 | drift_end | 3 | 1 | 56.9 | fail |
| temp | lin_lag | 600 | outage_end | 25 | 5 | 49.5 | fail |
| temp | holt | 3600 | drift_end | 3 | 1 | 51.4 | fail |
| temp | persistence | 3600 | outage_end | 25 | 6 | 0.9 | pass |
| vibration | persistence | 1 | drift_end | 3 | 0 | 0.6 | pass |
| vibration | persistence | 1 | outage_end | 25 | 1 | 2.1 | pass |
| vibration | holt | 1 | step | 2 | 2 | never | fail |
| vibration | holt | 5 | drift_end | 3 | 0 | 6.0 | pass |
| vibration | persistence | 5 | outage_end | 25 | 5 | 46.1 | fail |
| vibration | holt | 5 | step | 2 | 2 | never | fail |
| vibration | holt | 30 | drift_end | 3 | 0 | 7.0 | pass |
| vibration | holt | 30 | outage_end | 25 | 6 | 47.7 | fail |
| vibration | holt | 30 | step | 2 | 2 | never | fail |
| vibration | holt | 120 | drift_end | 3 | 0 | 8.0 | pass |
| vibration | holt | 120 | outage_end | 25 | 5 | 47.7 | fail |
| vibration | holt | 120 | step | 2 | 2 | never | fail |
| wind | persistence | 1 | drift_end | 2 | 0 | 27.8 | fail |
| wind | persistence | 1 | outage_end | 25 | 6 | 3.6 | pass |
| wind | lin_lag | 1 | step | 3 | 0 | 0.7 | pass |
| wind | persistence | 5 | drift_end | 2 | 0 | 27.8 | fail |
| wind | persistence | 5 | outage_end | 25 | 6 | 15.4 | fail |
| wind | persistence | 5 | step | 3 | 0 | 1.0 | pass |
| wind | persistence | 30 | drift_end | 2 | 0 | 29.8 | fail |
| wind | holt | 30 | outage_end | 25 | 6 | 49.5 | fail |
| wind | holt | 30 | step | 3 | 0 | 6.0 | pass |
| wind | persistence | 120 | drift_end | 2 | 0 | 31.8 | fail |
| wind | persistence | 120 | outage_end | 25 | 7 | 30.4 | fail |
| wind | persistence | 120 | step | 3 | 0 | 6.5 | pass |
