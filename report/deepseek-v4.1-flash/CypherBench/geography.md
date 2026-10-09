# Report — geography (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `geography`, 331 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T14:18:35-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.118 | 0.145 | 331 |   5 |        0 |
| FCAV        | vector    | 0.299 | 0.357 | 331 |   5 |        0 |
| ReAct       | fuzzy     | 0.399 | 0.444 | 331 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.462 | 0.491 | 331 |   0 |        1 |
| CyANCHOR    | fuzzy+lev | 0.698 | 0.746 | 331 |   0 |        0 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 1 of the 331 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.333 | 0.125 |   0.164 |  0.051 | 0.071 |
| FCAV        |  0.583 | 0.271 |   0.236 |  0.152 | 0.354 |
| ReAct       |  0.778 | 0.625 |   0.418 |  0.076 | 0.398 |
| GraphRAG    |  0.667 | 0.604 |   0.364 |  0.430 | 0.407 |
| CyANCHOR    |  0.861 | 0.812 |   0.636 |  0.684 | 0.637 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.091 |  0.077 | 0.196 |
| FCAV        | 0.382 |  0.290 | 0.271 |
| ReAct       | 0.436 |  0.373 | 0.421 |
| GraphRAG    | 0.564 |  0.456 | 0.421 |
| CyANCHOR    | 0.782 |  0.704 | 0.645 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.413 | 0.137 |   0.139 |  0.123 | 0.081 |
| FCAV        |  0.597 | 0.308 |   0.265 |  0.244 | 0.426 |
| ReAct       |  0.796 | 0.665 |   0.434 |  0.151 | 0.446 |
| GraphRAG    |  0.720 | 0.639 |   0.332 |  0.510 | 0.421 |
| CyANCHOR    |  0.906 | 0.838 |   0.660 |  0.769 | 0.682 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.091 |  0.119 | 0.213 |
| FCAV        | 0.422 |  0.338 | 0.355 |
| ReAct       | 0.464 |  0.411 | 0.484 |
| GraphRAG    | 0.551 |  0.477 | 0.483 |
| CyANCHOR    | 0.794 |  0.753 | 0.710 |
