# Sweep — `claude-sonnet-5` — 2026-10-06 18:32

**COMPLETE** — every graph x method cell holds one record per question, and no cell is dominated by infrastructure failures.

- generated: 2026-10-06 18:32 · commit `192e59c` · benchmarks `v2.3-verified-2026-09-22` · artifacts set `31db179b1d24`
- run config: CYPHER_EMPTY_IS_WRONG=False · CYPHER_SEMANTIC_REPAIR=True · RETRIEVAL fuzzy/vector/lev=1/0/1 · SHARDS=1 (cyanchor always 1)

## Completeness (n / err per cell; n must equal the question count)

| dataset | graph | questions | No Val Link | FCAV | ReAct | GraphRAG | CyANCHOR |
|---|---|--:|---|---|---|---|---|
| CypherBench | company | 303 | ✓ 303/5 | ✓ 303/6 | ✓ 303/1 | ✓ 303/0 | ✓ 303/0 |
| CypherBench | fictional_character | 322 | ✓ 322/11 | ✓ 322/6 | ✓ 322/0 | ✓ 322/0 | ✓ 322/0 |
| CypherBench | flight_accident | 168 | ✓ 168/1 | ✓ 168/3 | ✓ 168/0 | ✓ 168/0 | ✓ 168/0 |
| CypherBench | geography | 331 | ✓ 331/4 | ✓ 331/6 | ✓ 331/0 | ✓ 331/2 | ✓ 331/0 |
| CypherBench | movie | 359 | ✓ 359/5 | ✓ 359/7 | ✓ 359/0 | ✓ 359/0 | ✓ 359/0 |
| CypherBench | nba | 251 | ✓ 251/5 | ✓ 251/3 | ✓ 251/0 | ✓ 251/0 | ✓ 251/0 |
| CypherBench | politics | 356 | ✓ 356/6 | ✓ 356/2 | ✓ 356/0 | ✓ 356/0 | ✓ 356/0 |
| MindTheQuery | bloom | 24 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 |
| MindTheQuery | covid | 326 | ✓ 326/84 | ✓ 326/84 | ✓ 326/52 | ✓ 326/52 | ✓ 326/52 |
| MindTheQuery | er | 184 | ✓ 184/6 | ✓ 184/4 | ✓ 184/3 | ✓ 184/3 | ✓ 184/3 |
| MindTheQuery | healthcare | 418 | ✓ 418/5 | ✓ 418/10 | ✓ 418/4 | ✓ 418/4 | ✓ 418/4 |
| MindTheQuery | wwc | 265 | ✓ 265/20 | ✓ 265/20 | ✓ 265/12 | ✓ 265/12 | ✓ 265/12 |
| ZOGRASCOPE | pole | 1283 | ✓ 1283/8 | ✓ 1283/7 | ✓ 1283/0 | ✓ 1283/0 | ✓ 1283/0 |

## Errors by kind (pooled per dataset) — infra / gold / agent / other

`infra` = timeout, API or rate-limit failure (recoverable by re-running; flags ⚠ when large). `gold` = the benchmark's own gold query failed (a data defect, the same for every model). `agent` = the model's generated Cypher failed (the model's result). `other` = unclassified.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---|---|---|---|
| No Val Link | 2 / 0 / 35 / 0 | 0 / 61 / 54 / 0 | 0 / 0 / 8 / 0 | 2 / 61 / 97 / 0 |
| FCAV | 0 / 0 / 33 / 0 | 0 / 61 / 57 / 0 | 0 / 0 / 7 / 0 | 0 / 61 / 97 / 0 |
| ReAct | 1 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 1 / 71 / 0 / 0 |
| GraphRAG | 1 / 1 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 1 / 72 / 0 / 0 |
| CyANCHOR | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 |

## Headline — EA / PSJS pooled over all questions (errored questions score 0)

| method | CypherBench EA | CypherBench PSJS | MindTheQuery EA | MindTheQuery PSJS | ZOGRASCOPE EA | ZOGRASCOPE PSJS | All EA | All PSJS | n | err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.156 | 0.187 | 0.261 | 0.275 | 0.112 | 0.082 | 0.172 | 0.181 | 4590 | 160 |
| FCAV | 0.541 | 0.615 | 0.393 | 0.473 | 0.239 | 0.199 | 0.417 | 0.461 | 4590 | 158 |
| ReAct | 0.470 | 0.541 | 0.481 | 0.611 | 0.392 | 0.304 | 0.451 | 0.493 | 4590 | 72 |
| GraphRAG | 0.523 | 0.598 | 0.560 | 0.687 | 0.460 | 0.384 | 0.515 | 0.562 | 4590 | 73 |
| CyANCHOR | 0.699 | 0.781 | 0.578 | 0.727 | 0.557 | 0.447 | 0.627 | 0.673 | 4590 | 71 |

`*` = one or more cells of that dataset are incomplete; the number is over the records present.

## EA under the value comparison alone

The headline EA accepts a prediction that selects exactly the gold nodes when the gold query returns a whole node (`eval/node_set_match.py`). This table leaves that rule out: a property is never equal to a node, so those questions count as wrong for every method.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---:|---:|---:|---:|
| No Val Link | 0.156 | 0.261 | 0.062 | 0.158 |
| FCAV | 0.541 | 0.392 | 0.136 | 0.388 |
| ReAct | 0.470 | 0.481 | 0.234 | 0.407 |
| GraphRAG | 0.523 | 0.558 | 0.239 | 0.453 |
| CyANCHOR | 0.699 | 0.575 | 0.336 | 0.564 |

## CypherBench — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.474 | 0.238 | 0.124 | 0.118 | 0.083 | 0.156 |
| FCAV | 0.755 | 0.551 | 0.623 | 0.381 | 0.577 | 0.541 |
| ReAct | 0.729 | 0.577 | 0.579 | 0.381 | 0.367 | 0.470 |
| GraphRAG | 0.812 | 0.774 | 0.589 | 0.415 | 0.394 | 0.523 |
| CyANCHOR | 0.891 | 0.838 | 0.837 | 0.613 | 0.580 | 0.699 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.523 | 0.243 | 0.157 | 0.164 | 0.102 | 0.187 |
| FCAV | 0.841 | 0.596 | 0.657 | 0.471 | 0.671 | 0.615 |
| ReAct | 0.794 | 0.621 | 0.609 | 0.483 | 0.446 | 0.541 |
| GraphRAG | 0.882 | 0.810 | 0.636 | 0.519 | 0.478 | 0.598 |
| CyANCHOR | 0.954 | 0.882 | 0.879 | 0.729 | 0.677 | 0.781 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

## CypherBench — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.139 | 0.128 | 0.214 | 0.156 |
| FCAV | 0.718 | 0.497 | 0.523 | 0.541 |
| ReAct | 0.540 | 0.445 | 0.478 | 0.470 |
| GraphRAG | 0.653 | 0.508 | 0.481 | 0.523 |
| CyANCHOR | 0.786 | 0.679 | 0.686 | 0.699 |
| n | 337 | 1109 | 644 | 2090 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.150 | 0.147 | 0.277 | 0.187 |
| FCAV | 0.751 | 0.582 | 0.602 | 0.615 |
| ReAct | 0.562 | 0.518 | 0.571 | 0.541 |
| GraphRAG | 0.678 | 0.592 | 0.568 | 0.598 |
| CyANCHOR | 0.811 | 0.783 | 0.762 | 0.781 |
| n | 337 | 1109 | 644 | 2090 |

## MindTheQuery — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.352 | 0.184 | 0.278 | 0.257 | 0.336 | 0.261 |
| FCAV | 0.445 | 0.360 | 0.459 | 0.393 | 0.360 | 0.393 |
| ReAct | 0.523 | 0.507 | 0.536 | 0.399 | 0.474 | 0.481 |
| GraphRAG | 0.609 | 0.580 | 0.598 | 0.541 | 0.488 | 0.560 |
| CyANCHOR | 0.625 | 0.546 | 0.639 | 0.578 | 0.550 | 0.578 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.365 | 0.212 | 0.261 | 0.255 | 0.375 | 0.275 |
| FCAV | 0.592 | 0.444 | 0.566 | 0.439 | 0.416 | 0.473 |
| ReAct | 0.707 | 0.663 | 0.711 | 0.486 | 0.547 | 0.611 |
| GraphRAG | 0.756 | 0.702 | 0.736 | 0.690 | 0.569 | 0.687 |
| CyANCHOR | 0.775 | 0.711 | 0.811 | 0.733 | 0.640 | 0.727 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

## MindTheQuery — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.182 | 0.320 | 0.162 | 0.261 |
| FCAV | 0.494 | 0.468 | 0.227 | 0.393 |
| ReAct | 0.506 | 0.532 | 0.376 | 0.481 |
| GraphRAG | 0.532 | 0.601 | 0.487 | 0.560 |
| CyANCHOR | 0.558 | 0.633 | 0.474 | 0.578 |
| n | 77 | 752 | 388 | 1217 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.169 | 0.318 | 0.212 | 0.275 |
| FCAV | 0.756 | 0.524 | 0.318 | 0.473 |
| ReAct | 0.763 | 0.638 | 0.529 | 0.611 |
| GraphRAG | 0.810 | 0.726 | 0.587 | 0.687 |
| CyANCHOR | 0.801 | 0.765 | 0.638 | 0.727 |
| n | 77 | 752 | 388 | 1217 |

## ZOGRASCOPE — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.245 | 0.069 | 0.218 | 0.027 | 0.112 |
| FCAV | 0.392 | 0.253 | 0.197 | 0.035 | 0.239 |
| ReAct | 0.441 | 0.354 | 0.504 | 0.363 | 0.392 |
| GraphRAG | 0.476 | 0.401 | 0.641 | 0.478 | 0.460 |
| CyANCHOR | 0.580 | 0.494 | 0.697 | 0.681 | 0.557 |
| n | 143 | 793 | 234 | 113 | 1283 |

PSJS

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.210 | 0.037 | 0.191 | 0.015 | 0.082 |
| FCAV | 0.359 | 0.203 | 0.173 | 0.018 | 0.199 |
| ReAct | 0.398 | 0.280 | 0.397 | 0.161 | 0.304 |
| GraphRAG | 0.443 | 0.327 | 0.562 | 0.340 | 0.384 |
| CyANCHOR | 0.498 | 0.411 | 0.562 | 0.401 | 0.447 |
| n | 143 | 793 | 234 | 113 | 1283 |

## ZOGRASCOPE — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.296 | 0.091 | 0.133 | 0.112 |
| FCAV | 0.556 | 0.205 | 0.266 | 0.239 |
| ReAct | 0.642 | 0.375 | 0.375 | 0.392 |
| GraphRAG | 0.741 | 0.425 | 0.504 | 0.460 |
| CyANCHOR | 0.630 | 0.532 | 0.629 | 0.557 |
| n | 81 | 954 | 248 | 1283 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.225 | 0.057 | 0.134 | 0.082 |
| FCAV | 0.371 | 0.163 | 0.281 | 0.199 |
| ReAct | 0.429 | 0.281 | 0.353 | 0.304 |
| GraphRAG | 0.509 | 0.337 | 0.522 | 0.384 |
| CyANCHOR | 0.476 | 0.403 | 0.608 | 0.447 |
| n | 81 | 954 | 248 | 1283 |

## All datasets — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.369 | 0.131 | 0.188 | 0.149 | 0.146 | 0.172 |
| FCAV | 0.557 | 0.336 | 0.461 | 0.347 | 0.523 | 0.417 |
| ReAct | 0.583 | 0.436 | 0.547 | 0.384 | 0.394 | 0.451 |
| GraphRAG | 0.652 | 0.517 | 0.606 | 0.459 | 0.418 | 0.515 |
| CyANCHOR | 0.721 | 0.571 | 0.750 | 0.610 | 0.573 | 0.627 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.383 | 0.121 | 0.192 | 0.174 | 0.171 | 0.181 |
| FCAV | 0.623 | 0.339 | 0.496 | 0.412 | 0.607 | 0.461 |
| ReAct | 0.648 | 0.444 | 0.572 | 0.449 | 0.471 | 0.493 |
| GraphRAG | 0.711 | 0.515 | 0.639 | 0.549 | 0.501 | 0.562 |
| CyANCHOR | 0.763 | 0.577 | 0.772 | 0.694 | 0.668 | 0.673 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

## All datasets — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.172 | 0.167 | 0.183 | 0.172 |
| FCAV | 0.657 | 0.390 | 0.384 | 0.417 |
| ReAct | 0.552 | 0.444 | 0.427 | 0.451 |
| GraphRAG | 0.648 | 0.504 | 0.487 | 0.515 |
| CyANCHOR | 0.725 | 0.617 | 0.611 | 0.627 |
| n | 495 | 2815 | 1280 | 4590 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.165 | 0.162 | 0.230 | 0.181 |
| FCAV | 0.690 | 0.424 | 0.454 | 0.461 |
| ReAct | 0.571 | 0.469 | 0.516 | 0.493 |
| GraphRAG | 0.671 | 0.541 | 0.565 | 0.562 |
| CyANCHOR | 0.755 | 0.650 | 0.695 | 0.673 |
| n | 495 | 2815 | 1280 | 4590 |

Per-graph tables: `report/claude-sonnet-5/<Dataset>/<graph>.md`; per-dataset pooled tables: `report/claude-sonnet-5/<Dataset>/_summary.md`.
