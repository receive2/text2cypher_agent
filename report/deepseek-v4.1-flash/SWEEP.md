# Sweep — `deepseek-v4.1-flash` — 2026-10-08 21:03

**COMPLETE** — every graph x method cell holds one record per question, and no cell is dominated by infrastructure failures.

- generated: 2026-10-08 21:03 · commit `c6411e5` · benchmarks `v2.3-verified-2026-09-22` · artifacts set `31db179b1d24`
- run config: CYPHER_EMPTY_IS_WRONG=False · CYPHER_SEMANTIC_REPAIR=True · RETRIEVAL fuzzy/vector/lev=1/0/1 · SHARDS=1 (cyanchor always 1)

## Completeness (n / err per cell; n must equal the question count)

| dataset | graph | questions | No Val Link | FCAV | ReAct | GraphRAG | CyANCHOR |
|---|---|--:|---|---|---|---|---|
| CypherBench | company | 303 | ✓ 303/3 | ✓ 303/3 | ✓ 303/0 | ✓ 303/0 | ✓ 303/0 |
| CypherBench | fictional_character | 322 | ✓ 322/2 | ✓ 322/3 | ✓ 322/0 | ✓ 322/1 | ✓ 322/0 |
| CypherBench | flight_accident | 168 | ✓ 168/2 | ✓ 168/1 | ✓ 168/0 | ✓ 168/0 | ✓ 168/0 |
| CypherBench | geography | 331 | ✓ 331/5 | ✓ 331/5 | ✓ 331/0 | ✓ 331/1 | ✓ 331/0 |
| CypherBench | movie | 359 | ✓ 359/1 | ✓ 359/3 | ✓ 359/0 | ✓ 359/0 | ✓ 359/0 |
| CypherBench | nba | 251 | ✓ 251/1 | ✓ 251/0 | ✓ 251/0 | ✓ 251/0 | ✓ 251/0 |
| CypherBench | politics | 356 | ✓ 356/4 | ✓ 356/5 | ✓ 356/0 | ✓ 356/0 | ✓ 356/0 |
| MindTheQuery | bloom | 24 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 |
| MindTheQuery | covid | 326 | ✓ 326/79 | ✓ 326/78 | ✓ 326/52 | ✓ 326/52 | ✓ 326/52 |
| MindTheQuery | er | 184 | ✓ 184/4 | ✓ 184/4 | ✓ 184/3 | ✓ 184/3 | ✓ 184/3 |
| MindTheQuery | healthcare | 418 | ✓ 418/4 | ✓ 418/5 | ✓ 418/4 | ✓ 418/4 | ✓ 418/4 |
| MindTheQuery | wwc | 265 | ✓ 265/20 | ✓ 265/20 | ✓ 265/12 | ✓ 265/12 | ✓ 265/12 |
| ZOGRASCOPE | pole | 1283 | ✓ 1283/2 | ✓ 1283/0 | ✓ 1283/0 | ✓ 1283/0 | ✓ 1283/0 |

## Errors by kind (pooled per dataset) — infra / gold / agent / other

`infra` = timeout, API or rate-limit failure (recoverable by re-running; flags ⚠ when large). `gold` = the benchmark's own gold query failed (a data defect, the same for every model). `agent` = the model's generated Cypher failed (the model's result). `other` = unclassified.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---|---|---|---|
| No Val Link | 4 / 0 / 14 / 0 | 0 / 67 / 40 / 0 | 0 / 0 / 2 / 0 | 4 / 67 / 56 / 0 |
| FCAV | 1 / 0 / 19 / 0 | 0 / 67 / 40 / 0 | 0 / 0 / 0 / 0 | 1 / 67 / 59 / 0 |
| ReAct | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 |
| GraphRAG | 1 / 1 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 1 / 72 / 0 / 0 |
| CyANCHOR | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 |

## Headline — EA / PSJS pooled over all questions (errored questions score 0)

| method | CypherBench EA | CypherBench PSJS | MindTheQuery EA | MindTheQuery PSJS | ZOGRASCOPE EA | ZOGRASCOPE PSJS | All EA | All PSJS | n | err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.121 | 0.149 | 0.250 | 0.253 | 0.062 | 0.040 | 0.138 | 0.146 | 4590 | 127 |
| FCAV | 0.389 | 0.457 | 0.342 | 0.423 | 0.154 | 0.129 | 0.311 | 0.356 | 4590 | 127 |
| ReAct | 0.344 | 0.390 | 0.358 | 0.444 | 0.268 | 0.217 | 0.327 | 0.356 | 4590 | 71 |
| GraphRAG | 0.509 | 0.569 | 0.518 | 0.625 | 0.383 | 0.294 | 0.476 | 0.507 | 4590 | 73 |
| CyANCHOR | 0.697 | 0.759 | 0.542 | 0.679 | 0.537 | 0.410 | 0.611 | 0.640 | 4590 | 71 |

`*` = one or more cells of that dataset are incomplete; the number is over the records present.

## EA under the value comparison alone

The headline EA accepts a prediction that selects exactly the gold nodes when the gold query returns a whole node (`eval/node_set_match.py`). This table leaves that rule out: a property is never equal to a node, so those questions count as wrong for every method.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---:|---:|---:|---:|
| No Val Link | 0.121 | 0.250 | 0.034 | 0.131 |
| FCAV | 0.389 | 0.341 | 0.089 | 0.292 |
| ReAct | 0.344 | 0.358 | 0.140 | 0.291 |
| GraphRAG | 0.509 | 0.516 | 0.195 | 0.423 |
| CyANCHOR | 0.697 | 0.539 | 0.324 | 0.551 |

## CypherBench — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.359 | 0.158 | 0.106 | 0.092 | 0.068 | 0.121 |
| FCAV | 0.615 | 0.396 | 0.416 | 0.288 | 0.397 | 0.389 |
| ReAct | 0.589 | 0.555 | 0.413 | 0.194 | 0.285 | 0.344 |
| GraphRAG | 0.771 | 0.687 | 0.525 | 0.449 | 0.404 | 0.509 |
| CyANCHOR | 0.839 | 0.792 | 0.796 | 0.632 | 0.617 | 0.697 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.407 | 0.154 | 0.137 | 0.135 | 0.091 | 0.149 |
| FCAV | 0.689 | 0.423 | 0.488 | 0.375 | 0.462 | 0.457 |
| ReAct | 0.633 | 0.577 | 0.462 | 0.243 | 0.336 | 0.390 |
| GraphRAG | 0.823 | 0.706 | 0.568 | 0.546 | 0.457 | 0.569 |
| CyANCHOR | 0.892 | 0.830 | 0.840 | 0.714 | 0.683 | 0.759 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

## CypherBench — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.110 | 0.076 | 0.203 | 0.121 |
| FCAV | 0.466 | 0.351 | 0.413 | 0.389 |
| ReAct | 0.418 | 0.303 | 0.376 | 0.344 |
| GraphRAG | 0.614 | 0.509 | 0.455 | 0.509 |
| CyANCHOR | 0.763 | 0.688 | 0.679 | 0.697 |
| n | 337 | 1109 | 644 | 2090 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.124 | 0.093 | 0.260 | 0.149 |
| FCAV | 0.514 | 0.420 | 0.491 | 0.457 |
| ReAct | 0.436 | 0.339 | 0.452 | 0.390 |
| GraphRAG | 0.627 | 0.568 | 0.541 | 0.569 |
| CyANCHOR | 0.787 | 0.756 | 0.751 | 0.759 |
| n | 337 | 1109 | 644 | 2090 |

## MindTheQuery — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.289 | 0.181 | 0.284 | 0.241 | 0.332 | 0.250 |
| FCAV | 0.359 | 0.315 | 0.387 | 0.327 | 0.360 | 0.342 |
| ReAct | 0.352 | 0.402 | 0.418 | 0.281 | 0.341 | 0.358 |
| GraphRAG | 0.570 | 0.514 | 0.588 | 0.521 | 0.427 | 0.518 |
| CyANCHOR | 0.617 | 0.496 | 0.567 | 0.591 | 0.488 | 0.542 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.296 | 0.188 | 0.264 | 0.239 | 0.353 | 0.253 |
| FCAV | 0.468 | 0.386 | 0.541 | 0.385 | 0.407 | 0.423 |
| ReAct | 0.480 | 0.521 | 0.520 | 0.324 | 0.386 | 0.444 |
| GraphRAG | 0.695 | 0.595 | 0.702 | 0.677 | 0.492 | 0.625 |
| CyANCHOR | 0.741 | 0.628 | 0.725 | 0.758 | 0.576 | 0.679 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

## MindTheQuery — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.169 | 0.307 | 0.155 | 0.250 |
| FCAV | 0.312 | 0.414 | 0.209 | 0.342 |
| ReAct | 0.325 | 0.432 | 0.222 | 0.358 |
| GraphRAG | 0.506 | 0.582 | 0.397 | 0.518 |
| CyANCHOR | 0.442 | 0.614 | 0.423 | 0.542 |
| n | 77 | 752 | 388 | 1217 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.156 | 0.309 | 0.163 | 0.253 |
| FCAV | 0.692 | 0.476 | 0.266 | 0.423 |
| ReAct | 0.673 | 0.505 | 0.279 | 0.444 |
| GraphRAG | 0.802 | 0.685 | 0.473 | 0.625 |
| CyANCHOR | 0.835 | 0.733 | 0.543 | 0.679 |
| n | 77 | 752 | 388 | 1217 |

## ZOGRASCOPE — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.112 | 0.058 | 0.073 | 0.000 | 0.062 |
| FCAV | 0.308 | 0.175 | 0.064 | 0.000 | 0.154 |
| ReAct | 0.301 | 0.245 | 0.419 | 0.080 | 0.268 |
| GraphRAG | 0.427 | 0.317 | 0.568 | 0.416 | 0.383 |
| CyANCHOR | 0.573 | 0.479 | 0.735 | 0.487 | 0.537 |
| n | 143 | 793 | 234 | 113 | 1283 |

PSJS

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.110 | 0.034 | 0.036 | 0.004 | 0.040 |
| FCAV | 0.287 | 0.145 | 0.039 | 0.003 | 0.129 |
| ReAct | 0.255 | 0.206 | 0.324 | 0.030 | 0.217 |
| GraphRAG | 0.345 | 0.240 | 0.450 | 0.281 | 0.294 |
| CyANCHOR | 0.459 | 0.367 | 0.591 | 0.276 | 0.410 |
| n | 143 | 793 | 234 | 113 | 1283 |

## ZOGRASCOPE — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.148 | 0.062 | 0.032 | 0.062 |
| FCAV | 0.296 | 0.142 | 0.157 | 0.154 |
| ReAct | 0.333 | 0.260 | 0.278 | 0.268 |
| GraphRAG | 0.605 | 0.353 | 0.427 | 0.383 |
| CyANCHOR | 0.568 | 0.512 | 0.625 | 0.537 |
| n | 81 | 954 | 248 | 1283 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.109 | 0.036 | 0.033 | 0.040 |
| FCAV | 0.223 | 0.116 | 0.151 | 0.129 |
| ReAct | 0.270 | 0.197 | 0.278 | 0.217 |
| GraphRAG | 0.431 | 0.248 | 0.423 | 0.294 |
| CyANCHOR | 0.438 | 0.371 | 0.552 | 0.410 |
| n | 81 | 954 | 248 | 1283 |

## All datasets — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.263 | 0.109 | 0.139 | 0.126 | 0.135 | 0.138 |
| FCAV | 0.449 | 0.253 | 0.308 | 0.268 | 0.388 | 0.311 |
| ReAct | 0.434 | 0.343 | 0.416 | 0.207 | 0.299 | 0.327 |
| GraphRAG | 0.609 | 0.437 | 0.552 | 0.467 | 0.410 | 0.476 |
| CyANCHOR | 0.695 | 0.541 | 0.724 | 0.604 | 0.585 | 0.611 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.284 | 0.097 | 0.138 | 0.151 | 0.157 | 0.146 |
| FCAV | 0.504 | 0.260 | 0.372 | 0.337 | 0.448 | 0.356 |
| ReAct | 0.474 | 0.357 | 0.436 | 0.243 | 0.349 | 0.356 |
| GraphRAG | 0.640 | 0.420 | 0.566 | 0.555 | 0.466 | 0.507 |
| CyANCHOR | 0.717 | 0.521 | 0.741 | 0.679 | 0.656 | 0.640 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

## All datasets — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.125 | 0.133 | 0.155 | 0.138 |
| FCAV | 0.414 | 0.297 | 0.302 | 0.311 |
| ReAct | 0.390 | 0.323 | 0.310 | 0.327 |
| GraphRAG | 0.596 | 0.476 | 0.432 | 0.476 |
| CyANCHOR | 0.681 | 0.609 | 0.591 | 0.611 |
| n | 495 | 2815 | 1280 | 4590 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.126 | 0.131 | 0.187 | 0.146 |
| FCAV | 0.494 | 0.332 | 0.357 | 0.356 |
| ReAct | 0.446 | 0.336 | 0.366 | 0.356 |
| GraphRAG | 0.622 | 0.491 | 0.498 | 0.507 |
| CyANCHOR | 0.738 | 0.619 | 0.649 | 0.640 |
| n | 495 | 2815 | 1280 | 4590 |

Per-graph tables: `report/deepseek-v4.1-flash/<Dataset>/<graph>.md`; per-dataset pooled tables: `report/deepseek-v4.1-flash/<Dataset>/_summary.md`.
