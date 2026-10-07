# Report — CypherBench (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `all graphs pooled`, 2090 entity-perturbed test questions
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
| No Val Link | —         | 0.156 | 0.187 | 2090 |  37 |        0 |
| FCAV        | vector    | 0.541 | 0.615 | 2090 |  33 |        0 |
| ReAct       | fuzzy     | 0.470 | 0.541 | 2090 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.523 | 0.598 | 2090 |   1 |        1 |
| CyANCHOR    | fuzzy+lev | 0.699 | 0.781 | 2090 |   0 |        0 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 1 of the 2090 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.474 | 0.238 |   0.124 |  0.118 | 0.083 |
| FCAV        |  0.755 | 0.551 |   0.623 |  0.381 | 0.577 |
| ReAct       |  0.729 | 0.577 |   0.579 |  0.381 | 0.367 |
| GraphRAG    |  0.812 | 0.774 |   0.589 |  0.415 | 0.394 |
| CyANCHOR    |  0.891 | 0.838 |   0.837 |  0.613 | 0.580 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.139 |  0.128 | 0.214 |
| FCAV        | 0.718 |  0.497 | 0.523 |
| ReAct       | 0.540 |  0.445 | 0.478 |
| GraphRAG    | 0.653 |  0.508 | 0.481 |
| CyANCHOR    | 0.786 |  0.679 | 0.686 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.523 | 0.243 |   0.157 |  0.164 | 0.102 |
| FCAV        |  0.841 | 0.596 |   0.657 |  0.471 | 0.671 |
| ReAct       |  0.794 | 0.621 |   0.609 |  0.483 | 0.446 |
| GraphRAG    |  0.882 | 0.810 |   0.636 |  0.519 | 0.478 |
| CyANCHOR    |  0.954 | 0.882 |   0.879 |  0.729 | 0.677 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.150 |  0.147 | 0.277 |
| FCAV        | 0.751 |  0.582 | 0.602 |
| ReAct       | 0.562 |  0.518 | 0.571 |
| GraphRAG    | 0.678 |  0.592 | 0.568 |
| CyANCHOR    | 0.811 |  0.783 | 0.762 |
