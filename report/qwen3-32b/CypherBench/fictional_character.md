# Report — fictional_character (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `fictional_character`, 322 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06T17:42:15-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node` · escalate `on` (≤3) · semantic_repair `on` (≤4) · empty_is_wrong `off` · value_snap `on`.

**Methods.**
- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).
- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve
  candidate values from a self-built value index, an LLM generates the entity JSON.
- **ReAct** — ReAct NER agent (fuzzy/BM25 retrieval) over node + relation tools.
- **GraphRAG** — Multi-Agent GraphRAG baseline: generate→execute→evaluate→repair; on
  error/empty it extracts the query's labels/values/rels, validates them, and proposes
  normalized-Levenshtein replacements, iterating the generator.
- **CyANCHOR** — our plan-and-execute grounder (node + relation tools): decompose the question into
  entity mentions, route each to a database field, retrieve candidates with an LLM-judge
  corrective loop, then the Cypher LLM value-links. Retrieval is the union of independently
  toggleable arms — **fuzzy** (BM25) · **lev** (APOC normalized Levenshtein) · **vector**
  (in-graph embeddings).

---

## Overall

| method      | retrieval |    EA |  PSJS |   n | err | gold err |
| ----------- | --------- | ----: | ----: | --: | --: | -------: |
| No Val Link | —         | 0.068 | 0.086 | 322 |  28 |        0 |
| FCAV        | vector    | 0.177 | 0.220 | 322 |  36 |        0 |
| ReAct       | fuzzy     | 0.208 | 0.238 | 322 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.295 | 0.373 | 322 |   1 |        0 |
| CyANCHOR    | fuzzy+lev | 0.432 | 0.516 | 322 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.029 | 0.118 |   0.072 |  0.000 | 0.061 |
| FCAV        |  0.314 | 0.250 |   0.169 |  0.067 | 0.112 |
| ReAct       |  0.171 | 0.303 |   0.289 |  0.100 | 0.112 |
| GraphRAG    |  0.600 | 0.461 |   0.265 |  0.033 | 0.163 |
| CyANCHOR    |  0.514 | 0.500 |   0.566 |  0.200 | 0.306 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.016 | 0.218 |
| FCAV        | 0.170 |  0.132 | 0.276 |
| ReAct       | 0.170 |  0.165 | 0.322 |
| GraphRAG    | 0.340 |  0.258 | 0.345 |
| CyANCHOR    | 0.623 |  0.346 | 0.494 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.038 | 0.113 |   0.101 |  0.042 | 0.084 |
| FCAV        |  0.390 | 0.281 |   0.230 |  0.127 | 0.131 |
| ReAct       |  0.225 | 0.325 |   0.324 |  0.127 | 0.134 |
| GraphRAG    |  0.672 | 0.601 |   0.326 |  0.109 | 0.209 |
| CyANCHOR    |  0.631 | 0.661 |   0.649 |  0.227 | 0.337 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.026 |  0.023 | 0.255 |
| FCAV        | 0.205 |  0.186 | 0.299 |
| ReAct       | 0.198 |  0.187 | 0.368 |
| GraphRAG    | 0.378 |  0.342 | 0.433 |
| CyANCHOR    | 0.649 |  0.454 | 0.563 |
