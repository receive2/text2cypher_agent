# Report — covid (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `covid`, 326 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02T00:18:58-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.025 | 0.083 | 326 | 133 |       14 |
| FCAV        | vector    | 0.018 | 0.121 | 326 | 135 |       16 |
| ReAct       | fuzzy     | 0.411 | 0.538 | 326 |   0 |       52 |
| GraphRAG    | norm-Lev  | 0.439 | 0.596 | 326 |   0 |       52 |
| CyANCHOR    | fuzzy+lev | 0.466 | 0.589 | 326 |   0 |       52 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 52 of the 326 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.029 | 0.006 |   0.056 |  0.069 | 0.041 |
| FCAV        |  0.000 | 0.000 |   0.056 |  0.069 | 0.041 |
| ReAct       |  0.600 | 0.407 |   0.528 |  0.241 | 0.306 |
| GraphRAG    |  0.514 | 0.412 |   0.639 |  0.345 | 0.388 |
| CyANCHOR    |  0.543 | 0.446 |   0.611 |  0.345 | 0.449 |

## By query-difficulty — EA

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.045 | 0.010 |
| FCAV        |  0.030 | 0.010 |
| ReAct       |  0.366 | 0.443 |
| GraphRAG    |  0.478 | 0.411 |
| CyANCHOR    |  0.425 | 0.495 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.143 | 0.062 |   0.065 |  0.039 | 0.155 |
| FCAV        |  0.200 | 0.086 |   0.119 |  0.142 | 0.178 |
| ReAct       |  0.732 | 0.505 |   0.736 |  0.364 | 0.479 |
| GraphRAG    |  0.765 | 0.511 |   0.877 |  0.476 | 0.645 |
| CyANCHOR    |  0.738 | 0.528 |   0.838 |  0.493 | 0.574 |

## By query-difficulty — PSJS

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.057 | 0.101 |
| FCAV        |  0.109 | 0.129 |
| ReAct       |  0.486 | 0.575 |
| GraphRAG    |  0.617 | 0.581 |
| CyANCHOR    |  0.574 | 0.599 |
