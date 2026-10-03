# Clean vs perturbed — gpt-5.6-terra, CypherBench, three methods

Generated 2026-10-03 from the clean runs under `logs/clean_paired/` (see its README) and the perturbed cells under `logs/runs/`; No Val Link's clean run is the 2026-09-19 reference run on branch `reference/gpt-5.6-terra-2026-09`. Paired by question id; every question weighs one, an errored question scores 0. The test compares CyANCHOR's per-question drop (clean minus perturbed) with the baseline's by a two-sided Wilcoxon signed-rank test.

## Pooled over the 2,090 pairs

| method | clean EA | perturbed EA | Δ (points) | retained | lost (clean ✓ → perturbed ✗) | gained | clean PSJS | perturbed PSJS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 60.8 | 9.7 | -51.1 | 15.9% | 1084 | 15 | 81.5 | 14.1 |
| MA GraphRAG | 83.5 | 48.5 | -35.0 | 58.1% | 768 | 36 | 92.5 | 57.0 |
| CyANCHOR | 85.4 | 70.6 | -14.8 | 82.7% | 367 | 58 | 94.1 | 78.8 |

CyANCHOR's drop vs MA GraphRAG's: MA GraphRAG loses +20.2 points more per question on average (questions where the two drops differ: 713); Wilcoxon signed-rank p = 5.7e-51

CyANCHOR's drop vs No Val Link's: No Val Link loses +36.4 points more per question on average (questions where the two drops differ: 1118); Wilcoxon signed-rank p = 4e-109

| graph | n | No Val Link clean / pert. / Δ | MA GraphRAG clean / pert. / Δ | CyANCHOR clean / pert. / Δ |
|---|---:|---:|---:|---:|
| company | 303 | 61.7 / 11.2 / -50.5 | 85.8 / 51.8 / -34.0 | 87.5 / 72.3 / -15.2 |
| fictional_character | 322 | 57.1 / 8.4 / -48.8 | 83.5 / 42.5 / -41.0 | 86.6 / 68.3 / -18.3 |
| flight_accident | 168 | 84.5 / 17.9 / -66.7 | 94.6 / 63.7 / -31.0 | 94.0 / 88.7 / -5.4 |
| geography | 331 | 59.5 / 9.7 / -49.8 | 75.2 / 43.5 / -31.7 | 84.3 / 71.0 / -13.3 |
| movie | 359 | 48.5 / 4.7 / -43.7 | 79.9 / 41.5 / -38.4 | 83.0 / 64.6 / -18.4 |
| nba | 251 | 66.9 / 9.2 / -57.8 | 82.1 / 61.8 / -20.3 | 80.9 / 77.7 / -3.2 |
| politics | 356 | 61.5 / 11.0 / -50.6 | 88.5 / 46.1 / -42.4 | 85.1 / 63.5 / -21.6 |

