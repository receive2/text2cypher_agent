# Report — covid (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `covid`, 326 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-05T12:08:18-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.043 | 0.116 | 326 |  42 |       42 |
| FCAV        | vector    | 0.061 | 0.165 | 326 |  42 |       42 |
| ReAct       | fuzzy     | 0.301 | 0.532 | 326 |   0 |       52 |
| GraphRAG    | norm-Lev  | 0.387 | 0.558 | 326 |   0 |       52 |
| CyANCHOR    | fuzzy+lev | 0.353 | 0.596 | 326 |   0 |       52 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 52 of the 326 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.143 | 0.023 |   0.056 |  0.069 | 0.020 |
| FCAV        |  0.086 | 0.051 |   0.111 |  0.103 | 0.020 |
| ReAct       |  0.429 | 0.299 |   0.361 |  0.207 | 0.224 |
| GraphRAG    |  0.400 | 0.412 |   0.417 |  0.207 | 0.367 |
| CyANCHOR    |  0.457 | 0.339 |   0.472 |  0.207 | 0.327 |

## By query-difficulty — EA

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.075 | 0.021 |
| FCAV        |  0.104 | 0.031 |
| ReAct       |  0.261 | 0.328 |
| GraphRAG    |  0.306 | 0.443 |
| CyANCHOR    |  0.306 | 0.385 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.287 | 0.094 |   0.056 |  0.073 | 0.144 |
| FCAV        |  0.323 | 0.134 |   0.167 |  0.173 | 0.156 |
| ReAct       |  0.738 | 0.495 |   0.727 |  0.527 | 0.380 |
| GraphRAG    |  0.661 | 0.527 |   0.726 |  0.458 | 0.528 |
| CyANCHOR    |  0.704 | 0.531 |   0.881 |  0.476 | 0.616 |

## By query-difficulty — PSJS

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.092 | 0.133 |
| FCAV        |  0.172 | 0.159 |
| ReAct       |  0.519 | 0.542 |
| GraphRAG    |  0.577 | 0.544 |
| CyANCHOR    |  0.566 | 0.617 |
