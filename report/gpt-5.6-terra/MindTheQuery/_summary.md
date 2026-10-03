# Report — MindTheQuery (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `all graphs pooled`, 1217 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.

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

| method      | retrieval |    EA |  PSJS |    n | err | gold err |
| ----------- | --------- | ----: | ----: | ---: | --: | -------: |
| No Val Link | —         | 0.248 | 0.268 | 1217 | 147 |       32 |
| FCAV        | vector    | 0.282 | 0.443 | 1217 | 154 |       34 |
| ReAct       | fuzzy     | 0.501 | 0.567 | 1217 |   0 |       71 |
| GraphRAG    | norm-Lev  | 0.600 | 0.700 | 1217 |   0 |       71 |
| CyANCHOR    | fuzzy+lev | 0.615 | 0.713 | 1217 |   0 |       71 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 71 of the 1217 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.273 | 0.176 |   0.278 |  0.244 | 0.341 |
| FCAV        |  0.266 | 0.236 |   0.320 |  0.284 | 0.336 |
| ReAct       |  0.602 | 0.598 |   0.613 |  0.333 | 0.403 |
| GraphRAG    |  0.656 | 0.596 |   0.696 |  0.587 | 0.502 |
| CyANCHOR    |  0.648 | 0.617 |   0.706 |  0.617 | 0.507 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.169 |  0.307 | 0.149 |
| FCAV        | 0.221 |  0.348 | 0.165 |
| ReAct       | 0.571 |  0.535 | 0.423 |
| GraphRAG    | 0.727 |  0.660 | 0.459 |
| CyANCHOR    | 0.727 |  0.661 | 0.505 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.318 | 0.197 |   0.261 |  0.263 | 0.377 |
| FCAV        |  0.516 | 0.410 |   0.554 |  0.421 | 0.388 |
| ReAct       |  0.707 | 0.687 |   0.717 |  0.345 | 0.449 |
| GraphRAG    |  0.754 | 0.692 |   0.796 |  0.698 | 0.593 |
| CyANCHOR    |  0.754 | 0.713 |   0.811 |  0.737 | 0.563 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.182 |  0.314 | 0.195 |
| FCAV        | 0.752 |  0.491 | 0.289 |
| ReAct       | 0.662 |  0.581 | 0.522 |
| GraphRAG    | 0.837 |  0.741 | 0.592 |
| CyANCHOR    | 0.838 |  0.751 | 0.613 |
