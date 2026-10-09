# Report — MindTheQuery (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `all graphs pooled`, 1217 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-08. LLMs: NER `qwen3-32b` · Cypher `qwen3-32b` · QA `qwen3-32b`.

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
| No Val Link | —         | 0.218 | 0.215 | 1217 | 293 |       17 |
| FCAV        | vector    | 0.289 | 0.331 | 1217 | 304 |       23 |
| ReAct       | fuzzy     | 0.311 | 0.359 | 1217 |   2 |       71 |
| GraphRAG    | norm-Lev  | 0.451 | 0.566 | 1217 |   2 |       70 |
| CyANCHOR    | fuzzy+lev | 0.450 | 0.541 | 1217 |   2 |       71 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 71 of the 1217 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.227 | 0.165 |   0.263 |  0.201 | 0.289 |
| FCAV        |  0.258 | 0.244 |   0.371 |  0.300 | 0.299 |
| ReAct       |  0.305 | 0.302 |   0.376 |  0.264 | 0.336 |
| GraphRAG    |  0.469 | 0.425 |   0.500 |  0.485 | 0.393 |
| CyANCHOR    |  0.523 | 0.444 |   0.541 |  0.396 | 0.412 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.143 |  0.277 | 0.119 |
| FCAV        | 0.286 |  0.364 | 0.144 |
| ReAct       | 0.299 |  0.390 | 0.160 |
| GraphRAG    | 0.364 |  0.549 | 0.278 |
| CyANCHOR    | 0.429 |  0.532 | 0.296 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.223 | 0.159 |   0.242 |  0.207 | 0.298 |
| FCAV        |  0.353 | 0.290 |   0.408 |  0.337 | 0.314 |
| ReAct       |  0.379 | 0.370 |   0.432 |  0.298 | 0.347 |
| GraphRAG    |  0.604 | 0.526 |   0.645 |  0.633 | 0.448 |
| CyANCHOR    |  0.664 | 0.522 |   0.676 |  0.482 | 0.463 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.143 |  0.275 | 0.114 |
| FCAV        | 0.530 |  0.392 | 0.175 |
| ReAct       | 0.592 |  0.423 | 0.189 |
| GraphRAG    | 0.641 |  0.640 | 0.408 |
| CyANCHOR    | 0.712 |  0.613 | 0.368 |
