# Report — covid (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `covid`, 326 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T05:42:57-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.031 | 0.058 | 326 |  31 |       48 |
| FCAV        | vector    | 0.037 | 0.097 | 326 |  30 |       48 |
| ReAct       | fuzzy     | 0.092 | 0.182 | 326 |   0 |       52 |
| GraphRAG    | norm-Lev  | 0.328 | 0.375 | 326 |   0 |       52 |
| CyANCHOR    | fuzzy+lev | 0.331 | 0.470 | 326 |   0 |       52 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 52 of the 326 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.029 | 0.017 |   0.083 |  0.069 | 0.020 |
| FCAV        |  0.029 | 0.023 |   0.111 |  0.069 | 0.020 |
| ReAct       |  0.114 | 0.079 |   0.167 |  0.103 | 0.061 |
| GraphRAG    |  0.371 | 0.299 |   0.500 |  0.310 | 0.286 |
| CyANCHOR    |  0.486 | 0.311 |   0.417 |  0.207 | 0.306 |

## By query-difficulty — EA

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.060 | 0.010 |
| FCAV        |  0.067 | 0.016 |
| ReAct       |  0.119 | 0.073 |
| GraphRAG    |  0.313 | 0.339 |
| CyANCHOR    |  0.313 | 0.344 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.087 | 0.044 |   0.083 |  0.069 | 0.066 |
| FCAV        |  0.107 | 0.069 |   0.167 |  0.195 | 0.086 |
| ReAct       |  0.260 | 0.169 |   0.210 |  0.113 | 0.194 |
| GraphRAG    |  0.470 | 0.289 |   0.562 |  0.556 | 0.369 |
| CyANCHOR    |  0.585 | 0.383 |   0.620 |  0.615 | 0.507 |

## By query-difficulty — PSJS

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.083 | 0.041 |
| FCAV        |  0.128 | 0.076 |
| ReAct       |  0.233 | 0.146 |
| GraphRAG    |  0.372 | 0.376 |
| CyANCHOR    |  0.468 | 0.471 |
