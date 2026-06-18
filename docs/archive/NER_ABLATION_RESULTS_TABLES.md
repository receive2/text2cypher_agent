# NER Ablation — Results Tables (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both reported over successfully-scored rows.

**Setup.** 3 graphs (movie, geography, politics) x 200 perturbed test questions
each (600 total). Three NER configurations:
`full` = node + relation value-lookup tools; `node_only` = node tools only;
`no_ner` = grounding bypassed (the perturbed surface form is used as-is).

---

## Table 1 — Overall (per graph + pooled)

| graph     | metric |  full | node_only | no_ner |
|:----------|:-------|------:|----------:|-------:|
| movie     | EA     | 0.192 |     0.183 |  0.041 |
| movie     | PSJS   | 0.393 |     0.317 |  0.123 |
| geography | EA     | 0.141 |     0.172 |  0.041 |
| geography | PSJS   | 0.309 |     0.325 |  0.093 |
| politics  | EA     | 0.159 |     0.186 |  0.073 |
| politics  | PSJS   | 0.310 |     0.358 |  0.131 |
| pooled    | EA     | 0.164 |     0.180 |  0.051 |
| pooled    | PSJS   | 0.337 |     0.333 |  0.116 |

---

## Table 2 — By perturbation strategy (pooled across 3 graphs)

EA:

| strategy |   n |  full | node_only | no_ner |
|:---------|----:|------:|----------:|-------:|
| casing   |  60 | 0.390 |     0.458 |  0.254 |
| typo     | 138 | 0.163 |     0.272 |  0.022 |
| partial  | 137 | 0.179 |     0.185 |  0.022 |
| abbrev   | 126 | 0.130 |     0.040 |  0.016 |
| alias    | 139 | 0.081 |     0.089 |  0.052 |

PSJS:

| strategy |   n |  full | node_only | no_ner |
|:---------|----:|------:|----------:|-------:|
| casing   |  60 | 0.550 |     0.638 |  0.354 |
| typo     | 138 | 0.335 |     0.435 |  0.066 |
| partial  | 137 | 0.381 |     0.393 |  0.109 |
| abbrev   | 126 | 0.332 |     0.170 |  0.089 |
| alias    | 139 | 0.207 |     0.187 |  0.091 |

### Per-graph x strategy (EA)

| graph     | strategy |  n |  full | node_only | no_ner |
|:----------|:---------|---:|------:|----------:|-------:|
| movie     | casing   | 20 | 0.550 |     0.600 |  0.300 |
| movie     | typo     | 46 | 0.222 |     0.378 |  0.044 |
| movie     | partial  | 46 | 0.205 |     0.111 |  0.000 |
| movie     | abbrev   | 42 | 0.125 |     0.024 |  0.000 |
| movie     | alias    | 46 | 0.045 |     0.022 |  0.000 |
| geography | casing   | 20 | 0.250 |     0.450 |  0.150 |
| geography | typo     | 47 | 0.109 |     0.174 |  0.000 |
| geography | partial  | 46 | 0.217 |     0.261 |  0.044 |
| geography | abbrev   | 39 | 0.128 |     0.000 |  0.000 |
| geography | alias    | 48 | 0.064 |     0.106 |  0.064 |
| politics  | casing   | 20 | 0.368 |     0.316 |  0.316 |
| politics  | typo     | 45 | 0.159 |     0.267 |  0.023 |
| politics  | partial  | 45 | 0.114 |     0.182 |  0.023 |
| politics  | abbrev   | 45 | 0.136 |     0.093 |  0.047 |
| politics  | alias    | 45 | 0.136 |     0.140 |  0.093 |

---

## Appendix — By query-difficulty (pooled across 3 graphs)

| bucket |   n | EA full | EA node_only | EA no_ner | PSJS full | PSJS node_only | PSJS no_ner |
|:-------|----:|--------:|-------------:|----------:|----------:|---------------:|------------:|
| easy   |  89 |   0.169 |        0.225 |     0.079 |     0.249 |          0.264 |       0.081 |
| medium | 309 |   0.197 |        0.216 |     0.052 |     0.289 |          0.297 |       0.063 |
| hard   | 188 |   0.106 |        0.100 |     0.037 |     0.458 |          0.423 |       0.218 |

---

*Notes: metrics over successfully-scored rows (per-cell errored rows <= 7/200,
excluded from the mean). Single run per cell.*
