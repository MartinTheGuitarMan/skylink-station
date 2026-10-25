# Triage on dev cases, first night with local models (2026-10-16/17)

Same 300 balanced dev cases (100 per class, seed 7) on both machines. Rules baseline: macro-F1 0.630. C5a needs
macro-F1 >= 0.80 and >= +0.15 over the rules (so about 0.78 against this baseline). Not a verdict: dev seeds, zero-shot.

| machine | model | size | macro-F1 | vs rules | accuracy | invalid | p50 s |
|---|---|---|---|---|---|---|---|
| day host (LM Studio) | gemma-3-1b | 1B | 0.167 | -0.46 | 0.33 | 0 | 0.13 |
| day host (LM Studio) | gemma-4-e4b | 4B | 0.527 | -0.10 | 0.55 | 0 | 0.50 |
| day host (LM Studio) | gemma-4-12b | 12B | 0.491 | -0.14 | 0.49 | 0 | 1.07 |
| day host (jev-style) | Jev 0.8B v3 (decision model) | 0.8B | 0.599 | -0.03 | 0.63 | 0 | 0.16 |
| night host (Ollama) | gemma3:1b | 1B | 0.167 | -0.46 | 0.33 | 0 | 0.70 |
| night host (Ollama) | gemma3:4b | 4B | 0.250 | -0.38 | 0.34 | 0 | 2.41 |
| night host (Ollama) | qwen3:4b (reasoning) | 4B | stopped at 188/300 | n/a | 0.47 | 0 | 97 |
| day host | gpt-oss-20b | 20B | not run: memory 34 % free < 45 % guard | | | | |

Reading: no model beats the plain rules zero-shot. The 1B models answer one class for everything. Bigger is not better
here (12B below 4B below Jev 0.8B). Invalid output was 0 for every model: schema-constrained decoding plus code checks
work, the models are just not discriminating faults from real events. qwen3:4b spends about 97 s per case thinking, which is
far outside any useful latency for an alert and ran past the night window; stopped by hand.
Next: better case descriptions or few-shot examples (still dev only), gpt-oss-20b with memory freed, judge-on-disagreement
roster, Jev adaptation on dev cases.
