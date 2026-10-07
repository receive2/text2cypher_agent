# Report — geography (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `geography`, 331 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-04T14:32:55-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.169 | 0.193 | 331 |   4 |        0 |
| FCAV        | vector    | 0.447 | 0.513 | 331 |   6 |        0 |
| ReAct       | fuzzy     | 0.465 | 0.550 | 331 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.465 | 0.541 | 331 |   1 |        1 |
| CyANCHOR    | fuzzy+lev | 0.662 | 0.764 | 331 |   0 |        0 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 1 of the 331 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.472 | 0.271 |   0.182 |  0.089 | 0.080 |
| FCAV        |  0.611 | 0.354 |   0.400 |  0.278 | 0.575 |
| ReAct       |  0.778 | 0.625 |   0.527 |  0.165 | 0.478 |
| GraphRAG    |  0.722 | 0.625 |   0.309 |  0.418 | 0.425 |
| CyANCHOR    |  0.861 | 0.771 |   0.600 |  0.633 | 0.602 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.109 |  0.136 | 0.252 |
| FCAV        | 0.709 |  0.402 | 0.383 |
| ReAct       | 0.582 |  0.438 | 0.449 |
| GraphRAG    | 0.582 |  0.426 | 0.467 |
| CyANCHOR    | 0.745 |  0.627 | 0.673 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.572 | 0.268 |   0.159 |  0.146 | 0.089 |
| FCAV        |  0.722 | 0.428 |   0.443 |  0.362 | 0.623 |
| ReAct       |  0.881 | 0.715 |   0.528 |  0.290 | 0.566 |
| GraphRAG    |  0.766 | 0.710 |   0.322 |  0.550 | 0.498 |
| CyANCHOR    |  0.891 | 0.861 |   0.609 |  0.822 | 0.717 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.109 |  0.169 | 0.273 |
| FCAV        | 0.764 |  0.492 | 0.419 |
| ReAct       | 0.600 |  0.544 | 0.533 |
| GraphRAG    | 0.613 |  0.538 | 0.509 |
| CyANCHOR    | 0.825 |  0.775 | 0.715 |
