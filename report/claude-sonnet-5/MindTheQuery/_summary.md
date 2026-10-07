# Report — MindTheQuery (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `all graphs pooled`, 1217 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.

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
| No Val Link | —         | 0.261 | 0.275 | 1217 |  54 |       61 |
| FCAV        | vector    | 0.393 | 0.473 | 1217 |  57 |       61 |
| ReAct       | fuzzy     | 0.481 | 0.611 | 1217 |   0 |       71 |
| GraphRAG    | norm-Lev  | 0.560 | 0.687 | 1217 |   0 |       71 |
| CyANCHOR    | fuzzy+lev | 0.578 | 0.727 | 1217 |   0 |       71 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 71 of the 1217 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.352 | 0.184 |   0.278 |  0.257 | 0.336 |
| FCAV        |  0.445 | 0.360 |   0.459 |  0.393 | 0.360 |
| ReAct       |  0.523 | 0.507 |   0.536 |  0.399 | 0.474 |
| GraphRAG    |  0.609 | 0.580 |   0.598 |  0.541 | 0.488 |
| CyANCHOR    |  0.625 | 0.546 |   0.639 |  0.578 | 0.550 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.182 |  0.320 | 0.162 |
| FCAV        | 0.494 |  0.468 | 0.227 |
| ReAct       | 0.506 |  0.532 | 0.376 |
| GraphRAG    | 0.532 |  0.601 | 0.487 |
| CyANCHOR    | 0.558 |  0.633 | 0.474 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.365 | 0.212 |   0.261 |  0.255 | 0.375 |
| FCAV        |  0.592 | 0.444 |   0.566 |  0.439 | 0.416 |
| ReAct       |  0.707 | 0.663 |   0.711 |  0.486 | 0.547 |
| GraphRAG    |  0.756 | 0.702 |   0.736 |  0.690 | 0.569 |
| CyANCHOR    |  0.775 | 0.711 |   0.811 |  0.733 | 0.640 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.169 |  0.318 | 0.212 |
| FCAV        | 0.756 |  0.524 | 0.318 |
| ReAct       | 0.763 |  0.638 | 0.529 |
| GraphRAG    | 0.810 |  0.726 | 0.587 |
| CyANCHOR    | 0.801 |  0.765 | 0.638 |
