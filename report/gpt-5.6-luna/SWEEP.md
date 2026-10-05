# Sweep — `gpt-5.6-luna` — 2026-10-05 08:54

**NOT CLEAN** — 1 cell(s) marked ⚠ failed on infrastructure (timeouts / API) and were never really evaluated — see *Flagged cells* below. Re-run `python orchestrate_sweep.py` (it re-runs only these cells). Do not report these numbers.

- generated: 2026-10-05 08:54 · commit `192e59c` · benchmarks `v2.3-verified-2026-09-22` · artifacts set `31db179b1d24`
- run config: CYPHER_EMPTY_IS_WRONG=False · CYPHER_SEMANTIC_REPAIR=True · RETRIEVAL fuzzy/vector/lev=1/0/1 · SHARDS=1 (cyanchor always 1)

## Completeness (n / err per cell; n must equal the question count)

| dataset | graph | questions | No Val Link | FCAV | ReAct | GraphRAG | CyANCHOR |
|---|---|--:|---|---|---|---|---|
| CypherBench | company | 303 | ✓ 303/5 | ✓ 303/7 | ✓ 303/0 | ✓ 303/0 | ✓ 303/0 |
| CypherBench | fictional_character | 322 | ✓ 322/5 | ✓ 322/6 | ✓ 322/0 | ✓ 322/0 | ✓ 322/0 |
| CypherBench | flight_accident | 168 | ✓ 168/0 | ✓ 168/1 | ✓ 168/0 | ✓ 168/0 | ✓ 168/0 |
| CypherBench | geography | 331 | ⚠ 331/13 | ✓ 331/8 | ✓ 331/1 | ✓ 331/2 | ✓ 331/0 |
| CypherBench | movie | 359 | ✓ 359/10 | ✓ 359/3 | ✓ 359/3 | ✓ 359/0 | ✓ 359/0 |
| CypherBench | nba | 251 | ✓ 251/4 | ✓ 251/2 | ✓ 251/0 | ✓ 251/0 | ✓ 251/0 |
| CypherBench | politics | 356 | ✓ 356/9 | ✓ 356/9 | ✓ 356/0 | ✓ 356/0 | ✓ 356/0 |
| MindTheQuery | bloom | 24 | ✓ 24/0 | ✓ 24/1 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 |
| MindTheQuery | covid | 326 | ✓ 326/144 | ✓ 326/142 | ✓ 326/52 | ✓ 326/52 | ✓ 326/52 |
| MindTheQuery | er | 184 | ✓ 184/6 | ✓ 184/5 | ✓ 184/3 | ✓ 184/3 | ✓ 184/3 |
| MindTheQuery | healthcare | 418 | ✓ 418/9 | ✓ 418/10 | ✓ 418/4 | ✓ 418/4 | ✓ 418/4 |
| MindTheQuery | wwc | 265 | ✓ 265/23 | ✓ 265/15 | ✓ 265/12 | ✓ 265/12 | ✓ 265/12 |
| ZOGRASCOPE | pole | 1283 | ✓ 1283/3 | ✓ 1283/9 | ✓ 1283/0 | ✓ 1283/0 | ✓ 1283/0 |

## Flagged cells — infrastructure failures, not results

These cells hold one record per question but a large share of those records are timeouts or API failures: the model never answered them and they score 0 for the wrong reason. `python orchestrate_sweep.py` re-runs them automatically (up to 2 times); to re-run one by hand use the command shown.

- **CypherBench · geography · No Val Link** — 9 of 331 questions failed on infrastructure (timeout / API / rate limit) — never evaluated.
  errors: infra 9 · gold 0 · agent 4 · other 0
  most common: `example timeout: exceeded Ns`
  re-run: `python orchestrate_sweep.py --graphs geography --methods no_val_link`

## Errors by kind (pooled per dataset) — infra / gold / agent / other

`infra` = timeout, API or rate-limit failure (recoverable by re-running; flags ⚠ when large). `gold` = the benchmark's own gold query failed (a data defect, the same for every model). `agent` = the model's generated Cypher failed (the model's result). `other` = unclassified.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---|---|---|---|
| No Val Link | 20 / 0 / 26 / 0 | 0 / 49 / 133 / 0 | 0 / 0 / 3 / 0 | 20 / 49 / 162 / 0 |
| FCAV | 5 / 0 / 31 / 0 | 0 / 52 / 121 / 0 | 0 / 0 / 9 / 0 | 5 / 52 / 161 / 0 |
| ReAct | 4 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 4 / 71 / 0 / 0 |
| GraphRAG | 2 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 2 / 71 / 0 / 0 |
| CyANCHOR | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 |

## Headline — EA / PSJS pooled over all questions (errored questions score 0)

| method | CypherBench EA | CypherBench PSJS | MindTheQuery EA | MindTheQuery PSJS | ZOGRASCOPE EA | ZOGRASCOPE PSJS | All EA | All PSJS | n | err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.087 | 0.113 | 0.247 | 0.260 | 0.043 | 0.028 | 0.117 | 0.128 | 4590 | 231 |
| FCAV | 0.388 | 0.451 | 0.348 | 0.406 | 0.115 | 0.103 | 0.301 | 0.342 | 4590 | 218 |
| ReAct | 0.292 | 0.341 | 0.403 | 0.486 | 0.281 | 0.216 | 0.318 | 0.345 | 4590 | 75 |
| GraphRAG | 0.455 | 0.516 | 0.513 | 0.643 | 0.301 | 0.240 | 0.427 | 0.473 | 4590 | 73 |
| CyANCHOR | 0.667 | 0.727 | 0.537 | 0.658 | 0.472 | 0.367 | 0.578 | 0.608 | 4590 | 71 |

`*` = one or more cells of that dataset are incomplete; the number is over the records present.

## EA under the value comparison alone

The headline EA accepts a prediction that selects exactly the gold nodes when the gold query returns a whole node (`eval/node_set_match.py`). This table leaves that rule out: a property is never equal to a node, so those questions count as wrong for every method.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---:|---:|---:|---:|
| No Val Link | 0.087 | 0.247 | 0.028 | 0.113 |
| FCAV | 0.388 | 0.347 | 0.073 | 0.289 |
| ReAct | 0.292 | 0.403 | 0.166 | 0.286 |
| GraphRAG | 0.455 | 0.510 | 0.133 | 0.380 |
| CyANCHOR | 0.667 | 0.533 | 0.284 | 0.524 |

## CypherBench — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.266 | 0.075 | 0.075 | 0.083 | 0.048 | 0.087 |
| FCAV | 0.573 | 0.370 | 0.388 | 0.316 | 0.410 | 0.388 |
| ReAct | 0.500 | 0.374 | 0.393 | 0.175 | 0.246 | 0.292 |
| GraphRAG | 0.693 | 0.679 | 0.509 | 0.374 | 0.334 | 0.455 |
| CyANCHOR | 0.823 | 0.777 | 0.757 | 0.580 | 0.601 | 0.667 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.288 | 0.089 | 0.100 | 0.128 | 0.064 | 0.113 |
| FCAV | 0.603 | 0.398 | 0.426 | 0.398 | 0.494 | 0.451 |
| ReAct | 0.533 | 0.434 | 0.431 | 0.240 | 0.288 | 0.341 |
| GraphRAG | 0.745 | 0.690 | 0.548 | 0.472 | 0.396 | 0.516 |
| CyANCHOR | 0.842 | 0.827 | 0.783 | 0.659 | 0.683 | 0.727 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

## CypherBench — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.062 | 0.041 | 0.179 | 0.087 |
| FCAV | 0.421 | 0.337 | 0.458 | 0.388 |
| ReAct | 0.285 | 0.250 | 0.368 | 0.292 |
| GraphRAG | 0.549 | 0.435 | 0.441 | 0.455 |
| CyANCHOR | 0.733 | 0.634 | 0.688 | 0.667 |
| n | 337 | 1109 | 644 | 2090 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.072 | 0.058 | 0.230 | 0.113 |
| FCAV | 0.436 | 0.409 | 0.530 | 0.451 |
| ReAct | 0.299 | 0.292 | 0.450 | 0.341 |
| GraphRAG | 0.574 | 0.490 | 0.530 | 0.516 |
| CyANCHOR | 0.760 | 0.700 | 0.757 | 0.727 |
| n | 337 | 1109 | 644 | 2090 |

## MindTheQuery — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.273 | 0.178 | 0.268 | 0.248 | 0.332 | 0.247 |
| FCAV | 0.336 | 0.310 | 0.423 | 0.360 | 0.336 | 0.348 |
| ReAct | 0.406 | 0.446 | 0.485 | 0.330 | 0.355 | 0.403 |
| GraphRAG | 0.555 | 0.507 | 0.593 | 0.515 | 0.422 | 0.513 |
| CyANCHOR | 0.531 | 0.525 | 0.644 | 0.525 | 0.479 | 0.537 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.293 | 0.203 | 0.254 | 0.250 | 0.364 | 0.260 |
| FCAV | 0.469 | 0.366 | 0.514 | 0.370 | 0.394 | 0.406 |
| ReAct | 0.571 | 0.544 | 0.558 | 0.392 | 0.401 | 0.486 |
| GraphRAG | 0.690 | 0.656 | 0.722 | 0.657 | 0.501 | 0.643 |
| CyANCHOR | 0.706 | 0.629 | 0.772 | 0.673 | 0.553 | 0.658 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

## MindTheQuery — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.156 | 0.307 | 0.147 | 0.247 |
| FCAV | 0.403 | 0.422 | 0.193 | 0.348 |
| ReAct | 0.455 | 0.467 | 0.271 | 0.403 |
| GraphRAG | 0.519 | 0.572 | 0.397 | 0.513 |
| CyANCHOR | 0.545 | 0.588 | 0.436 | 0.537 |
| n | 77 | 752 | 388 | 1217 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.143 | 0.309 | 0.188 | 0.260 |
| FCAV | 0.582 | 0.466 | 0.256 | 0.406 |
| ReAct | 0.667 | 0.531 | 0.363 | 0.486 |
| GraphRAG | 0.788 | 0.695 | 0.515 | 0.643 |
| CyANCHOR | 0.747 | 0.709 | 0.541 | 0.658 |
| n | 77 | 752 | 388 | 1217 |

## ZOGRASCOPE — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.112 | 0.038 | 0.026 | 0.027 | 0.043 |
| FCAV | 0.224 | 0.136 | 0.026 | 0.018 | 0.115 |
| ReAct | 0.350 | 0.259 | 0.338 | 0.230 | 0.281 |
| GraphRAG | 0.301 | 0.250 | 0.483 | 0.283 | 0.301 |
| CyANCHOR | 0.476 | 0.410 | 0.692 | 0.451 | 0.472 |
| n | 143 | 793 | 234 | 113 | 1283 |

PSJS

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.109 | 0.021 | 0.005 | 0.015 | 0.028 |
| FCAV | 0.198 | 0.125 | 0.011 | 0.015 | 0.103 |
| ReAct | 0.281 | 0.202 | 0.265 | 0.137 | 0.216 |
| GraphRAG | 0.269 | 0.200 | 0.375 | 0.203 | 0.240 |
| CyANCHOR | 0.381 | 0.330 | 0.522 | 0.285 | 0.367 |
| n | 143 | 793 | 234 | 113 | 1283 |

## ZOGRASCOPE — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.062 | 0.044 | 0.032 | 0.043 |
| FCAV | 0.185 | 0.108 | 0.121 | 0.115 |
| ReAct | 0.506 | 0.266 | 0.262 | 0.281 |
| GraphRAG | 0.580 | 0.274 | 0.315 | 0.301 |
| CyANCHOR | 0.605 | 0.444 | 0.536 | 0.472 |
| n | 81 | 954 | 248 | 1283 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.056 | 0.026 | 0.025 | 0.028 |
| FCAV | 0.136 | 0.093 | 0.129 | 0.103 |
| ReAct | 0.358 | 0.197 | 0.245 | 0.216 |
| GraphRAG | 0.405 | 0.199 | 0.346 | 0.240 |
| CyANCHOR | 0.425 | 0.328 | 0.496 | 0.367 |
| n | 81 | 954 | 248 | 1283 |

## All datasets — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.220 | 0.082 | 0.107 | 0.125 | 0.119 | 0.117 |
| FCAV | 0.400 | 0.225 | 0.292 | 0.296 | 0.392 | 0.301 |
| ReAct | 0.428 | 0.329 | 0.399 | 0.227 | 0.274 | 0.318 |
| GraphRAG | 0.533 | 0.397 | 0.521 | 0.406 | 0.356 | 0.427 |
| CyANCHOR | 0.635 | 0.508 | 0.712 | 0.550 | 0.570 | 0.578 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.234 | 0.082 | 0.109 | 0.151 | 0.140 | 0.128 |
| FCAV | 0.441 | 0.239 | 0.327 | 0.348 | 0.469 | 0.342 |
| ReAct | 0.466 | 0.335 | 0.413 | 0.273 | 0.316 | 0.345 |
| GraphRAG | 0.583 | 0.411 | 0.540 | 0.497 | 0.423 | 0.473 |
| CyANCHOR | 0.662 | 0.500 | 0.706 | 0.622 | 0.650 | 0.608 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

## All datasets — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.077 | 0.113 | 0.141 | 0.117 |
| FCAV | 0.380 | 0.282 | 0.312 | 0.301 |
| ReAct | 0.347 | 0.313 | 0.318 | 0.318 |
| GraphRAG | 0.549 | 0.417 | 0.403 | 0.427 |
| CyANCHOR | 0.683 | 0.557 | 0.582 | 0.578 |
| n | 495 | 2815 | 1280 | 4590 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.081 | 0.114 | 0.177 | 0.128 |
| FCAV | 0.410 | 0.317 | 0.369 | 0.342 |
| ReAct | 0.366 | 0.324 | 0.384 | 0.345 |
| GraphRAG | 0.580 | 0.446 | 0.490 | 0.473 |
| CyANCHOR | 0.703 | 0.576 | 0.641 | 0.608 |
| n | 495 | 2815 | 1280 | 4590 |

Per-graph tables: `report/gpt-5.6-luna/<Dataset>/<graph>.md`; per-dataset pooled tables: `report/gpt-5.6-luna/<Dataset>/_summary.md`.
