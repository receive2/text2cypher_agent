# Report — healthcare (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `healthcare`, 418 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-05T20:39:57-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.500 | 0.509 | 418 |   1 |        4 |
| FCAV        | vector    | 0.593 | 0.604 | 418 |   6 |        4 |
| ReAct       | fuzzy     | 0.600 | 0.631 | 418 |   0 |        4 |
| GraphRAG    | norm-Lev  | 0.715 | 0.752 | 418 |   0 |        4 |
| CyANCHOR    | fuzzy+lev | 0.734 | 0.765 | 418 |   0 |        4 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 4 of the 418 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.591 | 0.544 |   0.667 |  0.442 | 0.444 |
| FCAV        |  0.727 | 0.671 |   0.714 |  0.589 | 0.460 |
| ReAct       |  0.636 | 0.696 |   0.857 |  0.496 | 0.548 |
| GraphRAG    |  0.909 | 0.810 |   0.881 |  0.674 | 0.573 |
| CyANCHOR    |  0.909 | 0.785 |   0.905 |  0.667 | 0.653 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.508 | 0.485 |
| FCAV        | 0.000 |  0.599 | 0.586 |
| ReAct       | 0.500 |  0.612 | 0.566 |
| GraphRAG    | 0.500 |  0.713 | 0.727 |
| CyANCHOR    | 1.000 |  0.732 | 0.737 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.585 | 0.544 |   0.682 |  0.450 | 0.461 |
| FCAV        |  0.722 | 0.679 |   0.719 |  0.597 | 0.482 |
| ReAct       |  0.685 | 0.729 |   0.873 |  0.510 | 0.593 |
| GraphRAG    |  0.926 | 0.870 |   0.901 |  0.697 | 0.624 |
| CyANCHOR    |  0.926 | 0.846 |   0.920 |  0.689 | 0.682 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.513 | 0.504 |
| FCAV        | 0.000 |  0.609 | 0.598 |
| ReAct       | 0.500 |  0.641 | 0.602 |
| GraphRAG    | 1.000 |  0.754 | 0.743 |
| CyANCHOR    | 1.000 |  0.771 | 0.741 |
