# Report — healthcare (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `healthcare`, 419 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-16T05:03:43-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node_rel` · escalate `on` (≤3) · semantic_repair `on` (≤4) · empty_is_wrong `off` · value_snap `on`.

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
| No Val Link | —         | 0.470 | 0.471 | 419 |   5 |        4 |
| FCAV        | vector    | 0.556 | 0.565 | 419 |   6 |        4 |
| ReAct       | fuzzy     | 0.563 | 0.579 | 419 |   0 |        4 |
| GraphRAG    | norm-Lev  | 0.654 | 0.697 | 419 |   0 |        4 |
| CyANCHOR    | fuzzy+lev | 0.692 | 0.736 | 419 |   0 |        4 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 4 of the 419 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.477 | 0.544 |   0.651 |  0.395 | 0.435 |
| FCAV        |  0.568 | 0.608 |   0.721 |  0.574 | 0.444 |
| ReAct       |  0.636 | 0.747 |   0.791 |  0.442 | 0.468 |
| GraphRAG    |  0.818 | 0.785 |   0.837 |  0.612 | 0.492 |
| CyANCHOR    |  0.818 | 0.785 |   0.930 |  0.667 | 0.532 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.478 | 0.455 |
| FCAV        | 0.000 |  0.569 | 0.525 |
| ReAct       | 0.000 |  0.575 | 0.535 |
| GraphRAG    | 0.000 |  0.673 | 0.606 |
| CyANCHOR    | 0.500 |  0.698 | 0.677 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.477 | 0.544 |   0.656 |  0.388 | 0.446 |
| FCAV        |  0.591 | 0.616 |   0.749 |  0.556 | 0.468 |
| ReAct       |  0.676 | 0.787 |   0.792 |  0.436 | 0.487 |
| GraphRAG    |  0.864 | 0.847 |   0.857 |  0.640 | 0.547 |
| CyANCHOR    |  0.872 | 0.854 |   0.935 |  0.718 | 0.561 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.478 | 0.459 |
| FCAV        | 0.000 |  0.575 | 0.541 |
| ReAct       | 0.000 |  0.586 | 0.567 |
| GraphRAG    | 0.500 |  0.717 | 0.638 |
| CyANCHOR    | 0.500 |  0.742 | 0.721 |
