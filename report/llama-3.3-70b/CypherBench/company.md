# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `company`, 305 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-21T20:29:07-05:00. LLMs: NER `llama-3.3-70b-deepinfra` · Cypher `llama-3.3-70b-deepinfra` · QA `llama-3.3-70b-deepinfra`.

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
| No Val Link | —         | 0.043 | 0.060 | 305 |  35 |        0 |
| ReAct       | fuzzy     | 0.154 | 0.185 | 305 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.361 | 0.383 | 305 |   5 |        0 |
| CyANCHOR    | fuzzy+lev | 0.279 | 0.324 | 298 |  67 |        9 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 9 of the 305 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.194 | 0.047 |   0.032 |  0.000 | 0.034 |
| ReAct       |  0.097 | 0.186 |   0.190 |  0.138 | 0.148 |
| GraphRAG    |  0.387 | 0.535 |   0.476 |  0.212 | 0.318 |
| CyANCHOR    |  0.300 | 0.452 |   0.371 |  0.177 | 0.212 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.029 | 0.084 |
| ReAct       | 0.103 |  0.123 | 0.232 |
| GraphRAG    | 0.564 |  0.316 | 0.358 |
| CyANCHOR    | 0.359 |  0.226 | 0.341 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.258 | 0.031 |   0.041 |  0.023 | 0.050 |
| ReAct       |  0.219 | 0.144 |   0.188 |  0.187 | 0.189 |
| GraphRAG    |  0.589 | 0.444 |   0.468 |  0.243 | 0.346 |
| CyANCHOR    |  0.463 | 0.442 |   0.416 |  0.209 | 0.257 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.026 |  0.028 | 0.130 |
| ReAct       | 0.103 |  0.140 | 0.301 |
| GraphRAG    | 0.564 |  0.344 | 0.378 |
| CyANCHOR    | 0.370 |  0.278 | 0.390 |
