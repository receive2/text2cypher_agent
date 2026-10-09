# Report — CypherBench (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `all graphs pooled`, 2090 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-08. LLMs: NER `deepseek-v4.1-flash` · Cypher `deepseek-v4.1-flash` · QA `deepseek-v4.1-flash`.

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
| No Val Link | —         | 0.121 | 0.149 | 2090 |  18 |        0 |
| FCAV        | vector    | 0.389 | 0.457 | 2090 |  20 |        0 |
| ReAct       | fuzzy     | 0.344 | 0.390 | 2090 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.509 | 0.569 | 2090 |   1 |        1 |
| CyANCHOR    | fuzzy+lev | 0.697 | 0.759 | 2090 |   0 |        0 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 1 of the 2090 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.359 | 0.158 |   0.106 |  0.092 | 0.068 |
| FCAV        |  0.615 | 0.396 |   0.416 |  0.288 | 0.397 |
| ReAct       |  0.589 | 0.555 |   0.413 |  0.194 | 0.285 |
| GraphRAG    |  0.771 | 0.687 |   0.525 |  0.449 | 0.404 |
| CyANCHOR    |  0.839 | 0.792 |   0.796 |  0.632 | 0.617 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.110 |  0.076 | 0.203 |
| FCAV        | 0.466 |  0.351 | 0.413 |
| ReAct       | 0.418 |  0.303 | 0.376 |
| GraphRAG    | 0.614 |  0.509 | 0.455 |
| CyANCHOR    | 0.763 |  0.688 | 0.679 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.407 | 0.154 |   0.137 |  0.135 | 0.091 |
| FCAV        |  0.689 | 0.423 |   0.488 |  0.375 | 0.462 |
| ReAct       |  0.633 | 0.577 |   0.462 |  0.243 | 0.336 |
| GraphRAG    |  0.823 | 0.706 |   0.568 |  0.546 | 0.457 |
| CyANCHOR    |  0.892 | 0.830 |   0.840 |  0.714 | 0.683 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.124 |  0.093 | 0.260 |
| FCAV        | 0.514 |  0.420 | 0.491 |
| ReAct       | 0.436 |  0.339 | 0.452 |
| GraphRAG    | 0.627 |  0.568 | 0.541 |
| CyANCHOR    | 0.787 |  0.756 | 0.751 |
