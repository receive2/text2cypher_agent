# Sweep — `gpt-5.6-terra` — 2026-10-02 21:03

**COMPLETE** — every graph x method cell holds one record per question, and no cell is dominated by infrastructure failures.

- generated: 2026-10-02 21:03 · commit `108f499` · benchmarks `v2.3-verified-2026-09-22` · artifacts set `31db179b1d24`
- run config: CYPHER_EMPTY_IS_WRONG=False · CYPHER_SEMANTIC_REPAIR=True · RETRIEVAL fuzzy/vector/lev=1/0/1 · SHARDS=1 (cyanchor always 1)

## Completeness (n / err per cell; n must equal the question count)

| dataset | graph | questions | No Val Link | FCAV | ReAct | GraphRAG | CyANCHOR |
|---|---|--:|---|---|---|---|---|
| CypherBench | company | 303 | ✓ 303/8 | ✓ 303/15 | ✓ 303/0 | ✓ 303/0 | ✓ 303/0 |
| CypherBench | fictional_character | 322 | ✓ 322/0 | ✓ 322/0 | ✓ 322/0 | ✓ 322/0 | ✓ 322/0 |
| CypherBench | flight_accident | 168 | ✓ 168/2 | ✓ 168/2 | ✓ 168/0 | ✓ 168/0 | ✓ 168/0 |
| CypherBench | geography | 331 | ✓ 331/6 | ✓ 331/6 | ✓ 331/1 | ✓ 331/2 | ✓ 331/0 |
| CypherBench | movie | 359 | ✓ 359/11 | ✓ 359/18 | ✓ 359/0 | ✓ 359/0 | ✓ 359/0 |
| CypherBench | nba | 251 | ✓ 251/4 | ✓ 251/5 | ✓ 251/0 | ✓ 251/0 | ✓ 251/0 |
| CypherBench | politics | 356 | ✓ 356/4 | ✓ 356/5 | ✓ 356/0 | ✓ 356/0 | ✓ 356/0 |
| MindTheQuery | bloom | 24 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 |
| MindTheQuery | covid | 326 | ✓ 326/147 | ✓ 326/151 | ✓ 326/52 | ✓ 326/52 | ✓ 326/52 |
| MindTheQuery | er | 184 | ✓ 184/6 | ✓ 184/4 | ✓ 184/3 | ✓ 184/3 | ✓ 184/3 |
| MindTheQuery | healthcare | 418 | ✓ 418/10 | ✓ 418/18 | ✓ 418/4 | ✓ 418/4 | ✓ 418/4 |
| MindTheQuery | wwc | 265 | ✓ 265/16 | ✓ 265/15 | ✓ 265/12 | ✓ 265/12 | ✓ 265/12 |
| ZOGRASCOPE | pole | 1283 | ✓ 1283/2 | ✓ 1283/0 | ✓ 1283/0 | ✓ 1283/0 | ✓ 1283/0 |

## Errors by kind (pooled per dataset) — infra / gold / agent / other

`infra` = timeout, API or rate-limit failure (recoverable by re-running; flags ⚠ when large). `gold` = the benchmark's own gold query failed (a data defect, the same for every model). `agent` = the model's generated Cypher failed (the model's result). `other` = unclassified.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---|---|---|---|
| No Val Link | 4 / 0 / 31 / 0 | 0 / 32 / 147 / 0 | 0 / 0 / 2 / 0 | 4 / 32 / 180 / 0 |
| FCAV | 3 / 0 / 48 / 0 | 0 / 34 / 154 / 0 | 0 / 0 / 0 / 0 | 3 / 34 / 202 / 0 |
| ReAct | 1 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 1 / 71 / 0 / 0 |
| GraphRAG | 2 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 2 / 71 / 0 / 0 |
| CyANCHOR | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 71 / 0 / 0 |

## Headline — EA / PSJS pooled over all questions (errored questions score 0)

| method | CypherBench EA | CypherBench PSJS | MindTheQuery EA | MindTheQuery PSJS | ZOGRASCOPE EA | ZOGRASCOPE PSJS | All EA | All PSJS | n | err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.097 | 0.141 | 0.248 | 0.268 | 0.048 | 0.027 | 0.123 | 0.143 | 4590 | 216 |
| FCAV | 0.426 | 0.577 | 0.282 | 0.443 | 0.175 | 0.147 | 0.318 | 0.421 | 4590 | 239 |
| ReAct | 0.366 | 0.414 | 0.501 | 0.567 | 0.373 | 0.283 | 0.404 | 0.418 | 4590 | 72 |
| GraphRAG | 0.485 | 0.570 | 0.600 | 0.700 | 0.436 | 0.338 | 0.502 | 0.540 | 4590 | 73 |
| CyANCHOR | 0.706 | 0.788 | 0.615 | 0.713 | 0.568 | 0.436 | 0.644 | 0.670 | 4590 | 71 |

`*` = one or more cells of that dataset are incomplete; the number is over the records present.

## EA under the value comparison alone

The headline EA accepts a prediction that selects exactly the gold nodes when the gold query returns a whole node (`eval/node_set_match.py`). This table leaves that rule out: a property is never equal to a node, so those questions count as wrong for every method.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---:|---:|---:|---:|
| No Val Link | 0.097 | 0.248 | 0.033 | 0.119 |
| FCAV | 0.426 | 0.282 | 0.107 | 0.298 |
| ReAct | 0.366 | 0.501 | 0.215 | 0.360 |
| GraphRAG | 0.485 | 0.597 | 0.193 | 0.433 |
| CyANCHOR | 0.706 | 0.612 | 0.341 | 0.579 |

## CypherBench — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.297 | 0.087 | 0.096 | 0.091 | 0.046 | 0.097 |
| FCAV | 0.609 | 0.449 | 0.488 | 0.282 | 0.463 | 0.426 |
| ReAct | 0.625 | 0.525 | 0.506 | 0.225 | 0.272 | 0.366 |
| GraphRAG | 0.740 | 0.694 | 0.566 | 0.381 | 0.370 | 0.485 |
| CyANCHOR | 0.880 | 0.864 | 0.811 | 0.571 | 0.655 | 0.706 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.376 | 0.104 | 0.133 | 0.156 | 0.077 | 0.141 |
| FCAV | 0.763 | 0.550 | 0.585 | 0.458 | 0.644 | 0.577 |
| ReAct | 0.693 | 0.576 | 0.541 | 0.274 | 0.320 | 0.414 |
| GraphRAG | 0.828 | 0.766 | 0.612 | 0.496 | 0.455 | 0.570 |
| CyANCHOR | 0.934 | 0.914 | 0.849 | 0.684 | 0.755 | 0.788 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

## CypherBench — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.089 | 0.057 | 0.169 | 0.097 |
| FCAV | 0.626 | 0.373 | 0.411 | 0.426 |
| ReAct | 0.448 | 0.320 | 0.402 | 0.366 |
| GraphRAG | 0.605 | 0.469 | 0.449 | 0.485 |
| CyANCHOR | 0.786 | 0.683 | 0.705 | 0.706 |
| n | 337 | 1109 | 644 | 2090 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.123 | 0.081 | 0.254 | 0.141 |
| FCAV | 0.682 | 0.527 | 0.609 | 0.577 |
| ReAct | 0.462 | 0.361 | 0.480 | 0.414 |
| GraphRAG | 0.622 | 0.563 | 0.555 | 0.570 |
| CyANCHOR | 0.817 | 0.774 | 0.798 | 0.788 |
| n | 337 | 1109 | 644 | 2090 |

## MindTheQuery — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.273 | 0.176 | 0.278 | 0.244 | 0.341 | 0.248 |
| FCAV | 0.266 | 0.236 | 0.320 | 0.284 | 0.336 | 0.282 |
| ReAct | 0.602 | 0.598 | 0.613 | 0.333 | 0.403 | 0.501 |
| GraphRAG | 0.656 | 0.596 | 0.696 | 0.587 | 0.502 | 0.600 |
| CyANCHOR | 0.648 | 0.617 | 0.706 | 0.617 | 0.507 | 0.615 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.318 | 0.197 | 0.261 | 0.263 | 0.377 | 0.268 |
| FCAV | 0.516 | 0.410 | 0.554 | 0.421 | 0.388 | 0.443 |
| ReAct | 0.707 | 0.687 | 0.717 | 0.345 | 0.449 | 0.567 |
| GraphRAG | 0.754 | 0.692 | 0.796 | 0.698 | 0.593 | 0.700 |
| CyANCHOR | 0.754 | 0.713 | 0.811 | 0.737 | 0.563 | 0.713 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

## MindTheQuery — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.169 | 0.307 | 0.149 | 0.248 |
| FCAV | 0.221 | 0.348 | 0.165 | 0.282 |
| ReAct | 0.571 | 0.535 | 0.423 | 0.501 |
| GraphRAG | 0.727 | 0.660 | 0.459 | 0.600 |
| CyANCHOR | 0.727 | 0.661 | 0.505 | 0.615 |
| n | 77 | 752 | 388 | 1217 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.182 | 0.314 | 0.195 | 0.268 |
| FCAV | 0.752 | 0.491 | 0.289 | 0.443 |
| ReAct | 0.662 | 0.581 | 0.522 | 0.567 |
| GraphRAG | 0.837 | 0.741 | 0.592 | 0.700 |
| CyANCHOR | 0.838 | 0.751 | 0.613 | 0.713 |
| n | 77 | 752 | 388 | 1217 |

## ZOGRASCOPE — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.147 | 0.043 | 0.021 | 0.018 | 0.048 |
| FCAV | 0.357 | 0.208 | 0.026 | 0.027 | 0.175 |
| ReAct | 0.490 | 0.366 | 0.449 | 0.115 | 0.373 |
| GraphRAG | 0.462 | 0.396 | 0.577 | 0.398 | 0.436 |
| CyANCHOR | 0.531 | 0.512 | 0.748 | 0.637 | 0.568 |
| n | 143 | 793 | 234 | 113 | 1283 |

PSJS

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.120 | 0.019 | 0.007 | 0.007 | 0.027 |
| FCAV | 0.315 | 0.178 | 0.003 | 0.024 | 0.147 |
| ReAct | 0.389 | 0.279 | 0.341 | 0.056 | 0.283 |
| GraphRAG | 0.360 | 0.312 | 0.450 | 0.263 | 0.338 |
| CyANCHOR | 0.462 | 0.393 | 0.596 | 0.378 | 0.436 |
| n | 143 | 793 | 234 | 113 | 1283 |

## ZOGRASCOPE — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.086 | 0.046 | 0.044 | 0.048 |
| FCAV | 0.296 | 0.170 | 0.157 | 0.175 |
| ReAct | 0.605 | 0.358 | 0.351 | 0.373 |
| GraphRAG | 0.753 | 0.391 | 0.508 | 0.436 |
| CyANCHOR | 0.691 | 0.539 | 0.641 | 0.568 |
| n | 81 | 954 | 248 | 1283 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.080 | 0.023 | 0.026 | 0.027 |
| FCAV | 0.192 | 0.136 | 0.178 | 0.147 |
| ReAct | 0.405 | 0.260 | 0.331 | 0.283 |
| GraphRAG | 0.474 | 0.276 | 0.533 | 0.338 |
| CyANCHOR | 0.442 | 0.392 | 0.604 | 0.436 |
| n | 81 | 954 | 248 | 1283 |

## All datasets — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.244 | 0.086 | 0.118 | 0.128 | 0.120 | 0.123 |
| FCAV | 0.436 | 0.260 | 0.315 | 0.255 | 0.431 | 0.318 |
| ReAct | 0.577 | 0.457 | 0.515 | 0.245 | 0.305 | 0.404 |
| GraphRAG | 0.631 | 0.504 | 0.600 | 0.443 | 0.404 | 0.502 |
| CyANCHOR | 0.708 | 0.605 | 0.768 | 0.591 | 0.618 | 0.644 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.281 | 0.082 | 0.127 | 0.171 | 0.152 | 0.143 |
| FCAV | 0.556 | 0.308 | 0.410 | 0.400 | 0.580 | 0.421 |
| ReAct | 0.603 | 0.442 | 0.525 | 0.271 | 0.352 | 0.418 |
| GraphRAG | 0.663 | 0.496 | 0.609 | 0.530 | 0.490 | 0.540 |
| CyANCHOR | 0.739 | 0.574 | 0.767 | 0.666 | 0.707 | 0.670 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

## All datasets — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.101 | 0.120 | 0.139 | 0.123 |
| FCAV | 0.509 | 0.298 | 0.287 | 0.318 |
| ReAct | 0.493 | 0.390 | 0.398 | 0.404 |
| GraphRAG | 0.648 | 0.493 | 0.463 | 0.502 |
| CyANCHOR | 0.762 | 0.628 | 0.632 | 0.644 |
| n | 495 | 2815 | 1280 | 4590 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.125 | 0.124 | 0.192 | 0.143 |
| FCAV | 0.613 | 0.385 | 0.428 | 0.421 |
| ReAct | 0.484 | 0.385 | 0.464 | 0.418 |
| GraphRAG | 0.631 | 0.513 | 0.562 | 0.540 |
| CyANCHOR | 0.759 | 0.639 | 0.704 | 0.670 |
| n | 495 | 2815 | 1280 | 4590 |

Per-graph tables: `report/gpt-5.6-terra/<Dataset>/<graph>.md`; per-dataset pooled tables: `report/gpt-5.6-terra/<Dataset>/_summary.md`.
