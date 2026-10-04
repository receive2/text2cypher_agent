# Report — healthcare (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `healthcare`, 418 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02T13:26:49-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.502 | 0.507 | 418 |   6 |        4 |
| FCAV        | vector    | 0.555 | 0.567 | 418 |  14 |        4 |
| ReAct       | fuzzy     | 0.579 | 0.592 | 418 |   0 |        4 |
| GraphRAG    | norm-Lev  | 0.711 | 0.738 | 418 |   0 |        4 |
| CyANCHOR    | fuzzy+lev | 0.708 | 0.739 | 418 |   0 |        4 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 4 of the 418 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.523 | 0.544 |   0.667 |  0.473 | 0.444 |
| FCAV        |  0.614 | 0.620 |   0.667 |  0.574 | 0.435 |
| ReAct       |  0.750 | 0.734 |   0.762 |  0.496 | 0.444 |
| GraphRAG    |  0.841 | 0.823 |   0.881 |  0.674 | 0.573 |
| CyANCHOR    |  0.818 | 0.797 |   0.905 |  0.705 | 0.548 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.508 | 0.495 |
| FCAV        | 0.000 |  0.568 | 0.525 |
| ReAct       | 0.000 |  0.593 | 0.545 |
| GraphRAG    | 0.500 |  0.716 | 0.697 |
| CyANCHOR    | 0.500 |  0.722 | 0.667 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.517 | 0.544 |   0.671 |  0.473 | 0.459 |
| FCAV        |  0.624 | 0.628 |   0.667 |  0.589 | 0.451 |
| ReAct       |  0.777 | 0.774 |   0.786 |  0.489 | 0.452 |
| GraphRAG    |  0.864 | 0.853 |   0.910 |  0.689 | 0.615 |
| CyANCHOR    |  0.843 | 0.849 |   0.905 |  0.734 | 0.583 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.510 | 0.507 |
| FCAV        | 0.000 |  0.576 | 0.549 |
| ReAct       | 0.000 |  0.605 | 0.562 |
| GraphRAG    | 0.500 |  0.753 | 0.695 |
| CyANCHOR    | 0.592 |  0.755 | 0.692 |
