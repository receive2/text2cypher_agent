# Report — healthcare (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `healthcare`, 418 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-08T17:28:25-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.481 | 0.487 | 418 |   0 |        4 |
| FCAV        | vector    | 0.557 | 0.577 | 418 |   1 |        4 |
| ReAct       | fuzzy     | 0.519 | 0.544 | 418 |   0 |        4 |
| GraphRAG    | norm-Lev  | 0.658 | 0.707 | 418 |   0 |        4 |
| CyANCHOR    | fuzzy+lev | 0.701 | 0.747 | 418 |   0 |        4 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 4 of the 418 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.523 | 0.544 |   0.667 |  0.403 | 0.444 |
| FCAV        |  0.636 | 0.646 |   0.667 |  0.519 | 0.476 |
| ReAct       |  0.523 | 0.684 |   0.738 |  0.426 | 0.435 |
| GraphRAG    |  0.818 | 0.772 |   0.905 |  0.605 | 0.500 |
| CyANCHOR    |  0.841 | 0.747 |   0.929 |  0.698 | 0.548 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.486 | 0.475 |
| FCAV        | 0.000 |  0.558 | 0.566 |
| ReAct       | 0.000 |  0.527 | 0.505 |
| GraphRAG    | 1.000 |  0.669 | 0.616 |
| CyANCHOR    | 1.000 |  0.716 | 0.646 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.523 | 0.544 |   0.671 |  0.406 | 0.461 |
| FCAV        |  0.659 | 0.646 |   0.690 |  0.534 | 0.510 |
| ReAct       |  0.568 | 0.739 |   0.738 |  0.434 | 0.460 |
| GraphRAG    |  0.883 | 0.854 |   0.910 |  0.630 | 0.564 |
| CyANCHOR    |  0.902 | 0.806 |   0.944 |  0.734 | 0.600 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.490 | 0.489 |
| FCAV        | 0.000 |  0.575 | 0.593 |
| ReAct       | 0.000 |  0.553 | 0.526 |
| GraphRAG    | 1.000 |  0.724 | 0.649 |
| CyANCHOR    | 1.000 |  0.766 | 0.682 |
