# Report — CypherBench (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `all graphs pooled`, 2090 entity-perturbed test questions
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
| No Val Link | —         | 0.061 | 0.083 | 2090 | 187 |        0 |
| FCAV        | vector    | 0.219 | 0.271 | 2090 | 245 |        0 |
| ReAct       | fuzzy     | 0.201 | 0.247 | 2090 |   6 |        0 |
| GraphRAG    | norm-Lev  | 0.354 | 0.441 | 2090 |   7 |        1 |
| CyANCHOR    | fuzzy+lev | 0.473 | 0.557 | 2090 |   0 |        0 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 1 of the 2090 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.120 | 0.091 |   0.067 |  0.045 | 0.041 |
| FCAV        |  0.406 | 0.268 |   0.248 |  0.165 | 0.175 |
| ReAct       |  0.375 | 0.309 |   0.284 |  0.110 | 0.141 |
| GraphRAG    |  0.609 | 0.551 |   0.401 |  0.251 | 0.266 |
| CyANCHOR    |  0.646 | 0.596 |   0.623 |  0.357 | 0.390 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.024 |  0.019 | 0.152 |
| FCAV        | 0.270 |  0.181 | 0.256 |
| ReAct       | 0.237 |  0.159 | 0.256 |
| GraphRAG    | 0.513 |  0.310 | 0.346 |
| CyANCHOR    | 0.617 |  0.404 | 0.516 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.143 | 0.099 |   0.093 |  0.075 | 0.060 |
| FCAV        |  0.479 | 0.291 |   0.299 |  0.211 | 0.240 |
| ReAct       |  0.458 | 0.348 |   0.323 |  0.157 | 0.180 |
| GraphRAG    |  0.702 | 0.636 |   0.470 |  0.370 | 0.330 |
| CyANCHOR    |  0.737 | 0.688 |   0.702 |  0.447 | 0.465 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.037 |  0.029 | 0.201 |
| FCAV        | 0.284 |  0.236 | 0.325 |
| ReAct       | 0.262 |  0.194 | 0.329 |
| GraphRAG    | 0.543 |  0.400 | 0.456 |
| CyANCHOR    | 0.645 |  0.507 | 0.596 |
