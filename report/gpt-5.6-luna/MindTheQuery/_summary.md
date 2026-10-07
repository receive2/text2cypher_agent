# Report — MindTheQuery (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `all graphs pooled`, 1217 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.

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
| No Val Link | —         | 0.247 | 0.260 | 1217 | 133 |       49 |
| FCAV        | vector    | 0.348 | 0.406 | 1217 | 121 |       52 |
| ReAct       | fuzzy     | 0.403 | 0.486 | 1217 |   0 |       71 |
| GraphRAG    | norm-Lev  | 0.513 | 0.643 | 1217 |   0 |       71 |
| CyANCHOR    | fuzzy+lev | 0.537 | 0.658 | 1217 |   0 |       71 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 71 of the 1217 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.273 | 0.178 |   0.268 |  0.248 | 0.332 |
| FCAV        |  0.336 | 0.310 |   0.423 |  0.360 | 0.336 |
| ReAct       |  0.406 | 0.446 |   0.485 |  0.330 | 0.355 |
| GraphRAG    |  0.555 | 0.507 |   0.593 |  0.515 | 0.422 |
| CyANCHOR    |  0.531 | 0.525 |   0.644 |  0.525 | 0.479 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.156 |  0.307 | 0.147 |
| FCAV        | 0.403 |  0.422 | 0.193 |
| ReAct       | 0.455 |  0.467 | 0.271 |
| GraphRAG    | 0.519 |  0.572 | 0.397 |
| CyANCHOR    | 0.545 |  0.588 | 0.436 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.293 | 0.203 |   0.254 |  0.250 | 0.364 |
| FCAV        |  0.469 | 0.366 |   0.514 |  0.370 | 0.394 |
| ReAct       |  0.571 | 0.544 |   0.558 |  0.392 | 0.401 |
| GraphRAG    |  0.690 | 0.656 |   0.722 |  0.657 | 0.501 |
| CyANCHOR    |  0.706 | 0.629 |   0.772 |  0.673 | 0.553 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.143 |  0.309 | 0.188 |
| FCAV        | 0.582 |  0.466 | 0.256 |
| ReAct       | 0.667 |  0.531 | 0.363 |
| GraphRAG    | 0.788 |  0.695 | 0.515 |
| CyANCHOR    | 0.747 |  0.709 | 0.541 |
