# Job R pilot, second model and R2 (dev seed 3, 2026-10-25)

Day host on power, LM Studio, 16k context, one model loaded at a time, same 8 windows as `reports/review-pilot-q14-2026-10-24.md` (46 alerts, 19 artefacts). Runs: `r-pilot-g4e` (R3, R4), `r-pilot-r2` (gemma-4-e4b R2), `r-pilot-r2-q14` (Qwen3-14B R2).

| method | windows | macro-F1 [95% CI] | vs R1 [95% CI] | fault P / R | summary valid | invalid | p50 s/window | report bytes | overrides |
|---|---|---|---|---|---|---|---|---|---|
| r0 | 8 | 0.621 [0.427, 0.724] |  | 1.0 / 0.2 | 1.0 | 0.0 | 0.0 | 275 | 0 |
| r1 | 8 | 0.858 [0.747, 1.0] |  | 0.833 / 1.0 | 1.0 | 0.0 | 0.0 | 285 | 0 |
| g4e/r3 | 8 | 0.229 [0.125, 0.295] | -0.630 [-0.859, -0.514] | 0.263 / 1.0 | 1.0 | 0.0 | 7.37 | 441 | 0 |
| g4e/r4 | 8 | 0.858 [0.747, 1.0] | +0.000 [+0.000, +0.000] | 0.333 / 0.8 | 1.0 | 0.0 | 4.68 | 451 | 0 |
| q14/r2 | 8 | 0.621 [0.427, 0.724] | -0.238 [-0.516, -0.112] | 1.0 / 0.2 | 1.0 | 0.0 | 10.61 | 275 | 0 |
| g4e/r2 | 8 | 0.801 [0.583, 0.889] | -0.058 [-0.330, +0.055] | 0.667 / 0.8 | 1.0 | 0.0 | 3.9 | 289 | 0 |
| q14/r3 | 8 | 0.129 [0.043, 0.272] | -0.730 [-0.872, -0.643] | 0.294 / 1.0 | 1.0 | 0.0 | 16.54 | 431 | 0 |
| q14/r4 | 8 | 0.778 [0.648, 0.963] | -0.081 [-0.185, -0.013] | 0.417 / 1.0 | 1.0 | 0.0 | 15.5 | 413 | 3 |

Label counts: R1 25 real / 14 artefact / 7 fault; Qwen3-14B R2 16 / 29 / 1, identical to R0 (the triage rules without hindsight); gemma-4-e4b R2 15 / 25 / 6; gemma-4-e4b R4 made no override.
