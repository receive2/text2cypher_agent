# Report — healthcare (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `healthcare`, 418 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-08T04:44:30-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.411 | 0.416 | 418 |  72 |        2 |
| FCAV        | vector    | 0.483 | 0.491 | 418 |  73 |        2 |
| ReAct       | fuzzy     | 0.490 | 0.513 | 418 |   1 |        4 |
| GraphRAG    | norm-Lev  | 0.622 | 0.655 | 418 |   1 |        4 |
| CyANCHOR    | fuzzy+lev | 0.624 | 0.675 | 418 |   0 |        4 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 4 of the 418 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.386 | 0.468 |   0.619 |  0.364 | 0.363 |
| FCAV        |  0.500 | 0.506 |   0.643 |  0.512 | 0.379 |
| ReAct       |  0.500 | 0.620 |   0.667 |  0.395 | 0.444 |
| GraphRAG    |  0.727 | 0.684 |   0.857 |  0.605 | 0.484 |
| CyANCHOR    |  0.773 | 0.709 |   0.786 |  0.581 | 0.508 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.429 | 0.364 |
| FCAV        | 0.000 |  0.502 | 0.434 |
| ReAct       | 0.000 |  0.505 | 0.455 |
| GraphRAG    | 1.000 |  0.644 | 0.545 |
| CyANCHOR    | 0.500 |  0.634 | 0.596 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.386 | 0.468 |   0.619 |  0.372 | 0.369 |
| FCAV        |  0.500 | 0.517 |   0.643 |  0.523 | 0.385 |
| ReAct       |  0.538 | 0.683 |   0.663 |  0.415 | 0.446 |
| GraphRAG    |  0.744 | 0.769 |   0.898 |  0.599 | 0.527 |
| CyANCHOR    |  0.829 | 0.794 |   0.825 |  0.613 | 0.558 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.434 | 0.366 |
| FCAV        | 0.000 |  0.510 | 0.437 |
| ReAct       | 0.000 |  0.527 | 0.479 |
| GraphRAG    | 1.000 |  0.670 | 0.601 |
| CyANCHOR    | 0.500 |  0.686 | 0.641 |
