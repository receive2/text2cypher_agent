# Report — MindTheQuery (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `all graphs pooled`, 1217 entity-perturbed test questions
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
| No Val Link | —         | 0.250 | 0.253 | 1217 |  40 |       67 |
| FCAV        | vector    | 0.342 | 0.423 | 1217 |  40 |       67 |
| ReAct       | fuzzy     | 0.358 | 0.444 | 1217 |   0 |       71 |
| GraphRAG    | norm-Lev  | 0.518 | 0.625 | 1217 |   0 |       71 |
| CyANCHOR    | fuzzy+lev | 0.542 | 0.679 | 1217 |   0 |       71 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 71 of the 1217 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.289 | 0.181 |   0.284 |  0.241 | 0.332 |
| FCAV        |  0.359 | 0.315 |   0.387 |  0.327 | 0.360 |
| ReAct       |  0.352 | 0.402 |   0.418 |  0.281 | 0.341 |
| GraphRAG    |  0.570 | 0.514 |   0.588 |  0.521 | 0.427 |
| CyANCHOR    |  0.617 | 0.496 |   0.567 |  0.591 | 0.488 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.169 |  0.307 | 0.155 |
| FCAV        | 0.312 |  0.414 | 0.209 |
| ReAct       | 0.325 |  0.432 | 0.222 |
| GraphRAG    | 0.506 |  0.582 | 0.397 |
| CyANCHOR    | 0.442 |  0.614 | 0.423 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.296 | 0.188 |   0.264 |  0.239 | 0.353 |
| FCAV        |  0.468 | 0.386 |   0.541 |  0.385 | 0.407 |
| ReAct       |  0.480 | 0.521 |   0.520 |  0.324 | 0.386 |
| GraphRAG    |  0.695 | 0.595 |   0.702 |  0.677 | 0.492 |
| CyANCHOR    |  0.741 | 0.628 |   0.725 |  0.758 | 0.576 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.156 |  0.309 | 0.163 |
| FCAV        | 0.692 |  0.476 | 0.266 |
| ReAct       | 0.673 |  0.505 | 0.279 |
| GraphRAG    | 0.802 |  0.685 | 0.473 |
| CyANCHOR    | 0.835 |  0.733 | 0.543 |
