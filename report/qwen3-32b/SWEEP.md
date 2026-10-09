# Sweep — `qwen3-32b` — 2026-10-08 20:49

**COMPLETE** — every graph x method cell holds one record per question, and no cell is dominated by infrastructure failures.

- generated: 2026-10-08 20:49 · commit `c6411e5` · benchmarks `v2.3-verified-2026-09-22` · artifacts set `31db179b1d24`
- run config: CYPHER_EMPTY_IS_WRONG=False · CYPHER_SEMANTIC_REPAIR=True · RETRIEVAL fuzzy/vector/lev=1/0/1 · SHARDS=1 (cyanchor always 1)

## Completeness (n / err per cell; n must equal the question count)

| dataset | graph | questions | No Val Link | FCAV | ReAct | GraphRAG | CyANCHOR |
|---|---|--:|---|---|---|---|---|
| CypherBench | company | 303 | ✓ 303/20 | ✓ 303/31 | ✓ 303/2 | ✓ 303/1 | ✓ 303/0 |
| CypherBench | fictional_character | 322 | ✓ 322/28 | ✓ 322/36 | ✓ 322/1 | ✓ 322/1 | ✓ 322/0 |
| CypherBench | flight_accident | 168 | ✓ 168/3 | ✓ 168/9 | ✓ 168/0 | ✓ 168/0 | ✓ 168/0 |
| CypherBench | geography | 331 | ✓ 331/31 | ✓ 331/35 | ✓ 331/1 | ✓ 331/6 | ✓ 331/0 |
| CypherBench | movie | 359 | ✓ 359/35 | ✓ 359/46 | ✓ 359/0 | ✓ 359/0 | ✓ 359/0 |
| CypherBench | nba | 251 | ✓ 251/28 | ✓ 251/35 | ✓ 251/1 | ✓ 251/0 | ✓ 251/0 |
| CypherBench | politics | 356 | ✓ 356/42 | ✓ 356/53 | ✓ 356/1 | ✓ 356/0 | ✓ 356/0 |
| MindTheQuery | bloom | 24 | ✓ 24/0 | ✓ 24/1 | ✓ 24/0 | ✓ 24/0 | ✓ 24/0 |
| MindTheQuery | covid | 326 | ✓ 326/169 | ✓ 326/166 | ✓ 326/52 | ✓ 326/52 | ✓ 326/52 |
| MindTheQuery | er | 184 | ✓ 184/23 | ✓ 184/24 | ✓ 184/3 | ✓ 184/3 | ✓ 184/3 |
| MindTheQuery | healthcare | 418 | ✓ 418/74 | ✓ 418/75 | ✓ 418/5 | ✓ 418/5 | ✓ 418/4 |
| MindTheQuery | wwc | 265 | ✓ 265/44 | ✓ 265/61 | ✓ 265/13 | ✓ 265/12 | ✓ 265/14 |
| ZOGRASCOPE | pole | 1283 | ✓ 1283/94 | ✓ 1283/117 | ✓ 1283/5 | ✓ 1283/3 | ✓ 1283/0 |

## Errors by kind (pooled per dataset) — infra / gold / agent / other

`infra` = timeout, API or rate-limit failure (recoverable by re-running; flags ⚠ when large). `gold` = the benchmark's own gold query failed (a data defect, the same for every model). `agent` = the model's generated Cypher failed (the model's result). `other` = unclassified.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---|---|---|---|
| No Val Link | 3 / 0 / 184 / 0 | 0 / 17 / 293 / 0 | 0 / 0 / 94 / 0 | 3 / 17 / 571 / 0 |
| FCAV | 10 / 0 / 235 / 0 | 5 / 23 / 299 / 0 | 0 / 0 / 117 / 0 | 15 / 23 / 651 / 0 |
| ReAct | 6 / 0 / 0 / 0 | 2 / 71 / 0 / 0 | 5 / 0 / 0 / 0 | 13 / 71 / 0 / 0 |
| GraphRAG | 7 / 1 / 0 / 0 | 2 / 70 / 0 / 0 | 3 / 0 / 0 / 0 | 12 / 71 / 0 / 0 |
| CyANCHOR | 0 / 0 / 0 / 0 | 1 / 71 / 0 / 1 | 0 / 0 / 0 / 0 | 1 / 71 / 0 / 1 |

## Headline — EA / PSJS pooled over all questions (errored questions score 0)

| method | CypherBench EA | CypherBench PSJS | MindTheQuery EA | MindTheQuery PSJS | ZOGRASCOPE EA | ZOGRASCOPE PSJS | All EA | All PSJS | n | err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.061 | 0.083 | 0.218 | 0.215 | 0.025 | 0.020 | 0.092 | 0.101 | 4590 | 591 |
| FCAV | 0.219 | 0.271 | 0.289 | 0.331 | 0.072 | 0.075 | 0.197 | 0.232 | 4590 | 689 |
| ReAct | 0.201 | 0.247 | 0.311 | 0.359 | 0.143 | 0.129 | 0.214 | 0.244 | 4590 | 84 |
| GraphRAG | 0.354 | 0.441 | 0.451 | 0.566 | 0.236 | 0.206 | 0.347 | 0.408 | 4590 | 83 |
| CyANCHOR | 0.473 | 0.557 | 0.450 | 0.541 | 0.320 | 0.268 | 0.424 | 0.472 | 4590 | 73 |

`*` = one or more cells of that dataset are incomplete; the number is over the records present.

## EA under the value comparison alone

The headline EA accepts a prediction that selects exactly the gold nodes when the gold query returns a whole node (`eval/node_set_match.py`). This table leaves that rule out: a property is never equal to a node, so those questions count as wrong for every method.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---:|---:|---:|---:|
| No Val Link | 0.061 | 0.218 | 0.019 | 0.091 |
| FCAV | 0.219 | 0.288 | 0.044 | 0.188 |
| ReAct | 0.201 | 0.311 | 0.076 | 0.195 |
| GraphRAG | 0.354 | 0.449 | 0.111 | 0.312 |
| CyANCHOR | 0.473 | 0.447 | 0.195 | 0.388 |

## CypherBench — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.120 | 0.091 | 0.067 | 0.045 | 0.041 | 0.061 |
| FCAV | 0.406 | 0.268 | 0.248 | 0.165 | 0.175 | 0.219 |
| ReAct | 0.375 | 0.309 | 0.284 | 0.110 | 0.141 | 0.201 |
| GraphRAG | 0.609 | 0.551 | 0.401 | 0.251 | 0.266 | 0.354 |
| CyANCHOR | 0.646 | 0.596 | 0.623 | 0.357 | 0.390 | 0.473 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.143 | 0.099 | 0.093 | 0.075 | 0.060 | 0.083 |
| FCAV | 0.479 | 0.291 | 0.299 | 0.211 | 0.240 | 0.271 |
| ReAct | 0.458 | 0.348 | 0.323 | 0.157 | 0.180 | 0.247 |
| GraphRAG | 0.702 | 0.636 | 0.470 | 0.370 | 0.330 | 0.441 |
| CyANCHOR | 0.737 | 0.688 | 0.702 | 0.447 | 0.465 | 0.557 |
| n | 192 | 265 | 387 | 617 | 629 | 2090 |

## CypherBench — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.024 | 0.019 | 0.152 | 0.061 |
| FCAV | 0.270 | 0.181 | 0.256 | 0.219 |
| ReAct | 0.237 | 0.159 | 0.256 | 0.201 |
| GraphRAG | 0.513 | 0.310 | 0.346 | 0.354 |
| CyANCHOR | 0.617 | 0.404 | 0.516 | 0.473 |
| n | 337 | 1109 | 644 | 2090 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.037 | 0.029 | 0.201 | 0.083 |
| FCAV | 0.284 | 0.236 | 0.325 | 0.271 |
| ReAct | 0.262 | 0.194 | 0.329 | 0.247 |
| GraphRAG | 0.543 | 0.400 | 0.456 | 0.441 |
| CyANCHOR | 0.645 | 0.507 | 0.596 | 0.557 |
| n | 337 | 1109 | 644 | 2090 |

## MindTheQuery — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.227 | 0.165 | 0.263 | 0.201 | 0.289 | 0.218 |
| FCAV | 0.258 | 0.244 | 0.371 | 0.300 | 0.299 | 0.289 |
| ReAct | 0.305 | 0.302 | 0.376 | 0.264 | 0.336 | 0.311 |
| GraphRAG | 0.469 | 0.425 | 0.500 | 0.485 | 0.393 | 0.451 |
| CyANCHOR | 0.523 | 0.444 | 0.541 | 0.396 | 0.412 | 0.450 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.223 | 0.159 | 0.242 | 0.207 | 0.298 | 0.215 |
| FCAV | 0.353 | 0.290 | 0.408 | 0.337 | 0.314 | 0.331 |
| ReAct | 0.379 | 0.370 | 0.432 | 0.298 | 0.347 | 0.359 |
| GraphRAG | 0.604 | 0.526 | 0.645 | 0.633 | 0.448 | 0.566 |
| CyANCHOR | 0.664 | 0.522 | 0.676 | 0.482 | 0.463 | 0.541 |
| n | 128 | 381 | 194 | 303 | 211 | 1217 |

## MindTheQuery — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.143 | 0.277 | 0.119 | 0.218 |
| FCAV | 0.286 | 0.364 | 0.144 | 0.289 |
| ReAct | 0.299 | 0.390 | 0.160 | 0.311 |
| GraphRAG | 0.364 | 0.549 | 0.278 | 0.451 |
| CyANCHOR | 0.429 | 0.532 | 0.296 | 0.450 |
| n | 77 | 752 | 388 | 1217 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.143 | 0.275 | 0.114 | 0.215 |
| FCAV | 0.530 | 0.392 | 0.175 | 0.331 |
| ReAct | 0.592 | 0.423 | 0.189 | 0.359 |
| GraphRAG | 0.641 | 0.640 | 0.408 | 0.566 |
| CyANCHOR | 0.712 | 0.613 | 0.368 | 0.541 |
| n | 77 | 752 | 388 | 1217 |

## ZOGRASCOPE — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.035 | 0.025 | 0.026 | 0.009 | 0.025 |
| FCAV | 0.133 | 0.084 | 0.026 | 0.009 | 0.072 |
| ReAct | 0.189 | 0.139 | 0.188 | 0.027 | 0.143 |
| GraphRAG | 0.238 | 0.207 | 0.346 | 0.212 | 0.236 |
| CyANCHOR | 0.329 | 0.267 | 0.534 | 0.230 | 0.320 |
| n | 143 | 793 | 234 | 113 | 1283 |

PSJS

| method | casing | typo | partial | abbrev | all |
|---|---:|---:|---:|---:|---:|
| No Val Link | 0.051 | 0.020 | 0.001 | 0.020 | 0.020 |
| FCAV | 0.168 | 0.089 | 0.002 | 0.009 | 0.075 |
| ReAct | 0.188 | 0.127 | 0.152 | 0.018 | 0.129 |
| GraphRAG | 0.248 | 0.185 | 0.277 | 0.147 | 0.206 |
| CyANCHOR | 0.312 | 0.225 | 0.453 | 0.128 | 0.268 |
| n | 143 | 793 | 234 | 113 | 1283 |

## ZOGRASCOPE — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.012 | 0.025 | 0.028 | 0.025 |
| FCAV | 0.148 | 0.064 | 0.081 | 0.072 |
| ReAct | 0.346 | 0.128 | 0.137 | 0.143 |
| GraphRAG | 0.444 | 0.217 | 0.242 | 0.236 |
| CyANCHOR | 0.444 | 0.310 | 0.315 | 0.320 |
| n | 81 | 954 | 248 | 1283 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.015 | 0.021 | 0.017 | 0.020 |
| FCAV | 0.193 | 0.065 | 0.074 | 0.075 |
| ReAct | 0.361 | 0.109 | 0.132 | 0.129 |
| GraphRAG | 0.430 | 0.178 | 0.240 | 0.206 |
| CyANCHOR | 0.425 | 0.251 | 0.280 | 0.268 |
| n | 81 | 954 | 248 | 1283 |

## All datasets — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.123 | 0.074 | 0.102 | 0.087 | 0.104 | 0.092 |
| FCAV | 0.281 | 0.161 | 0.213 | 0.188 | 0.206 | 0.197 |
| ReAct | 0.298 | 0.213 | 0.279 | 0.146 | 0.190 | 0.214 |
| GraphRAG | 0.456 | 0.328 | 0.409 | 0.316 | 0.298 | 0.347 |
| CyANCHOR | 0.514 | 0.375 | 0.578 | 0.354 | 0.395 | 0.424 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.137 | 0.072 | 0.102 | 0.108 | 0.120 | 0.101 |
| FCAV | 0.348 | 0.179 | 0.240 | 0.226 | 0.258 | 0.232 |
| ReAct | 0.353 | 0.232 | 0.300 | 0.183 | 0.222 | 0.244 |
| GraphRAG | 0.535 | 0.359 | 0.456 | 0.423 | 0.359 | 0.408 |
| CyANCHOR | 0.585 | 0.389 | 0.624 | 0.422 | 0.464 | 0.472 |
| n | 463 | 1439 | 815 | 1033 | 840 | 4590 |

## All datasets — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.040 | 0.090 | 0.118 | 0.092 |
| FCAV | 0.253 | 0.190 | 0.188 | 0.197 |
| ReAct | 0.265 | 0.210 | 0.204 | 0.214 |
| GraphRAG | 0.479 | 0.342 | 0.305 | 0.347 |
| CyANCHOR | 0.560 | 0.406 | 0.410 | 0.424 |
| n | 495 | 2815 | 1280 | 4590 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.050 | 0.092 | 0.139 | 0.101 |
| FCAV | 0.307 | 0.219 | 0.231 | 0.232 |
| ReAct | 0.330 | 0.226 | 0.248 | 0.244 |
| GraphRAG | 0.540 | 0.389 | 0.400 | 0.408 |
| CyANCHOR | 0.619 | 0.449 | 0.466 | 0.472 |
| n | 495 | 2815 | 1280 | 4590 |

Per-graph tables: `report/qwen3-32b/<Dataset>/<graph>.md`; per-dataset pooled tables: `report/qwen3-32b/<Dataset>/_summary.md`.
