# NER Ablation — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; reported over successfully-scored rows.

**Setup.** CypherBench `flight_accident`, 170 entity-perturbed test questions,
Cypher LLM = `gpt-4.1`. Grounding configs: `no_ner` (grounding bypassed —
perturbed surface form used as-is); `node_only` (NER agent, node-property tools);
`full` (NER agent, node + relation tools). `node_only`/`full` are each run with two
value-retrieval modes: **fuzzy** (Lucene fulltext) and **cascade** (fuzzy-first,
vector fills the tail). `no_ner` uses no retrieval, so it has a single column.

Column legend: `node·fz` = node_only+fuzzy, `node·cas` = node_only+cascade,
`full·fz` = full+fuzzy, `full·cas` = full+cascade.

## Overall

| mode      | retrieval | EA    | PSJS  | n   | err |
|-----------|-----------|-------|-------|-----|-----|
| no_ner    | —         | 0.095 | 0.126 | 169 |   1 |
| node_only | fuzzy     | 0.314 | 0.346 | 169 |   1 |
| node_only | cascade   | 0.290 | 0.320 | 169 |   1 |
| full      | fuzzy     | 0.373 | 0.410 | 169 |   1 |
| full      | cascade   | 0.373 | 0.403 | 169 |   1 |

## By perturbation strategy — EA

|           |   no_ner |  node·fz | node·cas |  full·fz | full·cas |
|-----------|----------|----------|----------|----------|----------|
| casing    |    0.118 |    0.353 |    0.353 |    0.471 |    0.471 |
| typo      |    0.000 |    0.324 |    0.270 |    0.486 |    0.486 |
| partial   |    0.105 |    0.289 |    0.289 |    0.368 |    0.395 |
| abbrev    |    0.184 |    0.342 |    0.211 |    0.263 |    0.237 |
| alias     |    0.077 |    0.282 |    0.359 |    0.333 |    0.333 |

## By query-difficulty — EA

|           |   no_ner |  node·fz | node·cas |  full·fz | full·cas |
|-----------|----------|----------|----------|----------|----------|
| easy      |    0.115 |    0.346 |    0.385 |    0.481 |    0.462 |
| medium    |    0.056 |    0.264 |    0.222 |    0.319 |    0.333 |
| hard      |    0.133 |    0.356 |    0.289 |    0.333 |    0.333 |

## By perturbation strategy — PSJS

|           |   no_ner |  node·fz | node·cas |  full·fz | full·cas |
|-----------|----------|----------|----------|----------|----------|
| casing    |    0.254 |    0.471 |    0.395 |    0.588 |    0.588 |
| typo      |    0.027 |    0.383 |    0.335 |    0.528 |    0.503 |
| partial   |    0.077 |    0.263 |    0.279 |    0.355 |    0.372 |
| abbrev    |    0.269 |    0.399 |    0.271 |    0.337 |    0.303 |
| alias     |    0.071 |    0.285 |    0.363 |    0.347 |    0.355 |

*Notes: metrics over successfully-scored rows (1 errored row excluded per mode).
Single run per cell.*
