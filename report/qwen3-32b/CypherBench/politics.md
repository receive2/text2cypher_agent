# Report — politics (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `politics`, 356 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-08T05:52:45-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.067 | 0.080 | 356 |  42 |        0 |
| FCAV        | vector    | 0.143 | 0.181 | 356 |  53 |        0 |
| ReAct       | fuzzy     | 0.169 | 0.219 | 356 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.287 | 0.355 | 356 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.340 | 0.428 | 356 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.111 | 0.238 |   0.044 |  0.052 | 0.061 |
| FCAV        |  0.167 | 0.333 |   0.178 |  0.133 | 0.101 |
| ReAct       |  0.278 | 0.429 |   0.311 |  0.110 | 0.131 |
| GraphRAG    |  0.444 | 0.714 |   0.244 |  0.225 | 0.293 |
| CyANCHOR    |  0.556 | 0.762 |   0.533 |  0.260 | 0.263 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.018 |  0.026 | 0.162 |
| FCAV        | 0.286 |  0.095 | 0.153 |
| ReAct       | 0.179 |  0.116 | 0.252 |
| GraphRAG    | 0.429 |  0.233 | 0.306 |
| CyANCHOR    | 0.482 |  0.286 | 0.360 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.182 | 0.199 |   0.039 |  0.068 | 0.075 |
| FCAV        |  0.196 | 0.328 |   0.201 |  0.169 | 0.159 |
| ReAct       |  0.345 | 0.473 |   0.344 |  0.163 | 0.183 |
| GraphRAG    |  0.458 | 0.746 |   0.248 |  0.337 | 0.334 |
| CyANCHOR    |  0.648 | 0.811 |   0.635 |  0.339 | 0.369 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.018 |  0.036 | 0.186 |
| FCAV        | 0.273 |  0.127 | 0.228 |
| ReAct       | 0.223 |  0.167 | 0.304 |
| GraphRAG    | 0.460 |  0.328 | 0.349 |
| CyANCHOR    | 0.518 |  0.402 | 0.427 |
