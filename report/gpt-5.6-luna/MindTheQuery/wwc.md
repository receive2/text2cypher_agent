# Report — wwc (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `wwc`, 267 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-03T21:59:45-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.116 | 0.117 | 267 |  12 |       11 |
| FCAV        | vector    | 0.356 | 0.547 | 267 |   3 |       12 |
| ReAct       | fuzzy     | 0.390 | 0.611 | 267 |   0 |       12 |
| GraphRAG    | norm-Lev  | 0.419 | 0.648 | 267 |   0 |       12 |
| CyANCHOR    | fuzzy+lev | 0.445 | 0.645 | 265 |   0 |       12 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 12 of the 267 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.071 | 0.082 |   0.024 |  0.121 | 0.395 |
| FCAV        |  0.357 | 0.410 |   0.329 |  0.310 | 0.395 |
| ReAct       |  0.286 | 0.525 |   0.354 |  0.362 | 0.368 |
| GraphRAG    |  0.357 | 0.459 |   0.390 |  0.448 | 0.421 |
| CyANCHOR    |  0.357 | 0.508 |   0.438 |  0.397 | 0.500 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.135 |  0.148 | 0.031 |
| FCAV        | 0.405 |  0.430 | 0.154 |
| ReAct       | 0.459 |  0.453 | 0.185 |
| GraphRAG    | 0.500 |  0.477 | 0.215 |
| CyANCHOR    | 0.528 |  0.523 | 0.200 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.079 | 0.082 |   0.024 |  0.121 | 0.396 |
| FCAV        |  0.684 | 0.637 |   0.594 |  0.399 | 0.425 |
| ReAct       |  0.697 | 0.785 |   0.602 |  0.571 | 0.348 |
| GraphRAG    |  0.654 | 0.778 |   0.651 |  0.653 | 0.421 |
| CyANCHOR    |  0.696 | 0.711 |   0.675 |  0.586 | 0.530 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.136 |  0.150 | 0.031 |
| FCAV        | 0.619 |  0.629 | 0.302 |
| ReAct       | 0.708 |  0.672 | 0.380 |
| GraphRAG    | 0.806 |  0.679 | 0.408 |
| CyANCHOR    | 0.758 |  0.729 | 0.356 |
