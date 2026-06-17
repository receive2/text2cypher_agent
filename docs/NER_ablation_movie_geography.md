# NER Ablation — movie · geography (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; reported over successfully-scored rows.

**Setup.** First 200 entity-perturbed test questions per graph, Cypher LLM = `gpt-4.1`,
value retrieval = Lucene fulltext (`fuzzy`). Grounding configs: `no_ner` (bypassed —
perturbed surface form used as-is); `node_only` (NER agent, node-property tools);
`full` (NER agent, node + relation tools). Column legend: `node·fz` = node_only+fuzzy,
`full·fz` = full+fuzzy. Same format as `NER_ablation_flight_accident.md`.

## movie

| mode      | retrieval |   EA  |  PSJS | n   | err |
|-----------|-----------|-------|-------|-----|-----|
| no_ner    | —         | 0.031 | 0.117 | 196 |   4 |
| node_only | fuzzy     | 0.195 | 0.307 | 195 |   5 |
| full      | fuzzy     | 0.219 | 0.446 | 196 |   4 |

**By perturbation strategy — EA**

|          |   no_ner |  node·fz |  full·fz |
|-----------|----------|----------|----------|
| casing    |    0.300 |    0.550 |    0.550 |
| typo      |    0.000 |    0.386 |    0.356 |
| partial   |    0.000 |    0.156 |    0.178 |
| abbrev    |    0.000 |    0.024 |    0.119 |
| alias     |    0.000 |    0.045 |    0.068 |

**By query-difficulty — EA**

|          |   no_ner |  node·fz |  full·fz |
|-----------|----------|----------|----------|
| easy      |    0.000 |    0.360 |    0.200 |
| medium    |    0.049 |    0.218 |    0.314 |
| hard      |    0.014 |    0.101 |    0.087 |

**By perturbation strategy — PSJS**

|          |   no_ner |  node·fz |  full·fz |
|-----------|----------|----------|----------|
| casing    |    0.442 |    0.695 |    0.850 |
| typo      |    0.045 |    0.473 |    0.493 |
| partial   |    0.142 |    0.357 |    0.497 |
| abbrev    |    0.067 |    0.116 |    0.371 |
| alias     |    0.063 |    0.096 |    0.236 |

## geography

| mode      | retrieval |   EA  |  PSJS | n   | err |
|-----------|-----------|-------|-------|-----|-----|
| no_ner    | —         | 0.046 | 0.108 | 197 |   3 |
| node_only | fuzzy     | 0.250 | 0.425 | 196 |   4 |
| full      | fuzzy     | 0.291 | 0.503 | 196 |   4 |

**By perturbation strategy — EA**

|          |   no_ner |  node·fz |  full·fz |
|-----------|----------|----------|----------|
| casing    |    0.150 |    0.650 |    0.500 |
| typo      |    0.000 |    0.341 |    0.356 |
| partial   |    0.043 |    0.348 |    0.378 |
| abbrev    |    0.026 |    0.000 |    0.205 |
| alias     |    0.064 |    0.106 |    0.128 |

**By query-difficulty — EA**

|          |   no_ner |  node·fz |  full·fz |
|-----------|----------|----------|----------|
| easy      |    0.032 |    0.387 |    0.323 |
| medium    |    0.040 |    0.238 |    0.304 |
| hard      |    0.062 |    0.203 |    0.254 |

**By perturbation strategy — PSJS**

|          |   no_ner |  node·fz |  full·fz |
|-----------|----------|----------|----------|
| casing    |    0.230 |    0.850 |    0.725 |
| typo      |    0.071 |    0.606 |    0.649 |
| partial   |    0.115 |    0.545 |    0.596 |
| abbrev    |    0.092 |    0.151 |    0.487 |
| alias     |    0.099 |    0.186 |    0.191 |

*Notes: metrics over successfully-scored rows (errored rows excluded). Single run per cell.*
