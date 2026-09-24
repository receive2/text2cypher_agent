# Sweep — `llama-3.3-70b` — 2026-09-24 08:55

**NOT CLEAN** — 58 cell(s) marked ✗ are missing, truncated or scored on an older copy of the benchmark (≠release). Re-run `python orchestrate_sweep.py` (it re-runs only these cells). Do not report these numbers.

- generated: 2026-09-24 08:55 · commit `e9c32e65` · benchmarks `v2.3-verified-2026-09-22` · artifacts set `31db179b1d24`
- run config: CYPHER_EMPTY_IS_WRONG=False · CYPHER_SEMANTIC_REPAIR=True · RETRIEVAL fuzzy/vector/lev=1/0/1 · SHARDS=1 (cyanchor always 1)

## Completeness (n / err per cell; n must equal the question count)

| dataset | graph | questions | No Val Link | FCAV | ReAct | GraphRAG | CyANCHOR |
|---|---|--:|---|---|---|---|---|
| CypherBench | company | 303 | ✓ 303/35 | ✗ missing | ✓ 303/1 | ✓ 303/5 | ✗ 296/75 |
| CypherBench | fictional_character | 322 | ✓ 322/42 | ✓ 322/57 | ✓ 322/1 | ✓ 322/1 | ✗ 193/0 |
| CypherBench | flight_accident | 168 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| CypherBench | geography | 331 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| CypherBench | movie | 359 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| CypherBench | nba | 251 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| CypherBench | politics | 356 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| MindTheQuery | bloom | 24 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| MindTheQuery | covid | 326 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| MindTheQuery | er | 184 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| MindTheQuery | healthcare | 418 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| MindTheQuery | wwc | 265 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |
| ZOGRASCOPE | pole | 1283 | ✗ missing | ✗ missing | ✗ missing | ✗ missing | ✗ missing |

## Errors by kind (pooled per dataset) — infra / gold / agent / other

`infra` = timeout, API or rate-limit failure (recoverable by re-running; flags ⚠ when large). `gold` = the benchmark's own gold query failed (a data defect, the same for every model). `agent` = the model's generated Cypher failed (the model's result). `other` = unclassified.

| method | CypherBench | MindTheQuery | ZOGRASCOPE | All |
|---|---|---|---|---|
| No Val Link | 0 / 0 / 77 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 77 / 0 |
| FCAV | 0 / 0 / 57 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 57 / 0 |
| ReAct | 1 / 0 / 1 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 1 / 0 / 1 / 0 |
| GraphRAG | 6 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 6 / 0 / 0 / 0 |
| CyANCHOR | 75 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 75 / 0 / 0 / 0 |

## Headline — EA / PSJS pooled over all questions (errored questions score 0)

| method | CypherBench EA | CypherBench PSJS | MindTheQuery EA | MindTheQuery PSJS | ZOGRASCOPE EA | ZOGRASCOPE PSJS | All EA | All PSJS | n | err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.040* | 0.063* | —* | —* | —* | —* | 0.040 | 0.063 | 625 | 77 |
| FCAV | 0.112* | 0.160* | —* | —* | —* | —* | 0.112 | 0.160 | 322 | 57 |
| ReAct | 0.128* | 0.173* | —* | —* | —* | —* | 0.128 | 0.173 | 625 | 2 |
| GraphRAG | 0.328* | 0.365* | —* | —* | —* | —* | 0.328 | 0.365 | 625 | 6 |
| CyANCHOR | 0.311* | 0.369* | —* | —* | —* | —* | 0.311 | 0.369 | 489 | 75 |

`*` = one or more cells of that dataset are incomplete; the number is over the records present.

## CypherBench — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.152 | 0.050 | 0.028 | 0.000 | 0.027 | 0.040 |
| FCAV | 0.171 | 0.171 | 0.096 | 0.033 | 0.082 | 0.112 |
| ReAct | 0.136 | 0.160 | 0.139 | 0.109 | 0.108 | 0.128 |
| GraphRAG | 0.439 | 0.521 | 0.382 | 0.173 | 0.215 | 0.328 |
| CyANCHOR | 0.346 | 0.432 | 0.420 | 0.184 | 0.233 | 0.311 |
| n | 66 | 119 | 144 | 110 | 186 | 625 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.191 | 0.051 | 0.056 | 0.024 | 0.054 | 0.063 |
| FCAV | 0.208 | 0.198 | 0.164 | 0.085 | 0.132 | 0.160 |
| ReAct | 0.239 | 0.154 | 0.186 | 0.157 | 0.161 | 0.173 |
| GraphRAG | 0.566 | 0.496 | 0.413 | 0.213 | 0.262 | 0.365 |
| CyANCHOR | 0.454 | 0.495 | 0.479 | 0.225 | 0.281 | 0.369 |
| n | 66 | 119 | 144 | 110 | 186 | 625 |

## CypherBench — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.011 | 0.026 | 0.082 | 0.040 |
| FCAV | 0.245 | 0.066 | 0.126 | 0.112 |
| ReAct | 0.066 | 0.102 | 0.209 | 0.128 |
| GraphRAG | 0.473 | 0.270 | 0.368 | 0.328 |
| CyANCHOR | 0.448 | 0.248 | 0.368 | 0.311 |
| n | 91 | 352 | 182 | 625 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.037 | 0.028 | 0.145 | 0.063 |
| FCAV | 0.236 | 0.101 | 0.236 | 0.160 |
| ReAct | 0.069 | 0.142 | 0.285 | 0.173 |
| GraphRAG | 0.491 | 0.315 | 0.399 | 0.365 |
| CyANCHOR | 0.465 | 0.319 | 0.420 | 0.369 |
| n | 91 | 352 | 182 | 625 |

## All datasets — by perturbation strategy

EA

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.152 | 0.050 | 0.028 | 0.000 | 0.027 | 0.040 |
| FCAV | 0.171 | 0.171 | 0.096 | 0.033 | 0.082 | 0.112 |
| ReAct | 0.136 | 0.160 | 0.139 | 0.109 | 0.108 | 0.128 |
| GraphRAG | 0.439 | 0.521 | 0.382 | 0.173 | 0.215 | 0.328 |
| CyANCHOR | 0.346 | 0.432 | 0.420 | 0.184 | 0.233 | 0.311 |
| n | 66 | 119 | 144 | 110 | 186 | 625 |

PSJS

| method | casing | typo | partial | abbrev | alias | all |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.191 | 0.051 | 0.056 | 0.024 | 0.054 | 0.063 |
| FCAV | 0.208 | 0.198 | 0.164 | 0.085 | 0.132 | 0.160 |
| ReAct | 0.239 | 0.154 | 0.186 | 0.157 | 0.161 | 0.173 |
| GraphRAG | 0.566 | 0.496 | 0.413 | 0.213 | 0.262 | 0.365 |
| CyANCHOR | 0.454 | 0.495 | 0.479 | 0.225 | 0.281 | 0.369 |
| n | 66 | 119 | 144 | 110 | 186 | 625 |

## All datasets — by query difficulty

EA

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.011 | 0.026 | 0.082 | 0.040 |
| FCAV | 0.245 | 0.066 | 0.126 | 0.112 |
| ReAct | 0.066 | 0.102 | 0.209 | 0.128 |
| GraphRAG | 0.473 | 0.270 | 0.368 | 0.328 |
| CyANCHOR | 0.448 | 0.248 | 0.368 | 0.311 |
| n | 91 | 352 | 182 | 625 |

PSJS

| method | easy | medium | hard | all |
|---|---:|---:|---:|---:|
| No Val Link | 0.037 | 0.028 | 0.145 | 0.063 |
| FCAV | 0.236 | 0.101 | 0.236 | 0.160 |
| ReAct | 0.069 | 0.142 | 0.285 | 0.173 |
| GraphRAG | 0.491 | 0.315 | 0.399 | 0.365 |
| CyANCHOR | 0.465 | 0.319 | 0.420 | 0.369 |
| n | 91 | 352 | 182 | 625 |

Per-graph tables: `report/llama-3.3-70b/<Dataset>/<graph>.md`; per-dataset pooled tables: `report/llama-3.3-70b/<Dataset>/_summary.md`.
