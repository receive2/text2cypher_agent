# Report — pole (entity-perturbed ZOGRASCOPE)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** ZOGRASCOPE `pole`, 1283 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-02T18:13:43-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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

| method      | retrieval |    EA |  PSJS |    n | err | gold err |
| ----------- | --------- | ----: | ----: | ---: | --: | -------: |
| No Val Link | —         | 0.048 | 0.027 | 1283 |   2 |        0 |
| FCAV        | vector    | 0.175 | 0.147 | 1283 |   0 |        0 |
| ReAct       | fuzzy     | 0.373 | 0.283 | 1283 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.436 | 0.338 | 1283 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.568 | 0.436 | 1283 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.147 | 0.043 |   0.021 |  0.018 |
| FCAV        |  0.357 | 0.208 |   0.026 |  0.027 |
| ReAct       |  0.490 | 0.366 |   0.449 |  0.115 |
| GraphRAG    |  0.462 | 0.396 |   0.577 |  0.398 |
| CyANCHOR    |  0.531 | 0.512 |   0.748 |  0.637 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.086 |  0.046 | 0.044 |
| FCAV        | 0.296 |  0.170 | 0.157 |
| ReAct       | 0.605 |  0.358 | 0.351 |
| GraphRAG    | 0.753 |  0.391 | 0.508 |
| CyANCHOR    | 0.691 |  0.539 | 0.641 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.120 | 0.019 |   0.007 |  0.007 |
| FCAV        |  0.315 | 0.178 |   0.003 |  0.024 |
| ReAct       |  0.389 | 0.279 |   0.341 |  0.056 |
| GraphRAG    |  0.360 | 0.312 |   0.450 |  0.263 |
| CyANCHOR    |  0.462 | 0.393 |   0.596 |  0.378 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.080 |  0.023 | 0.026 |
| FCAV        | 0.192 |  0.136 | 0.178 |
| ReAct       | 0.405 |  0.260 | 0.331 |
| GraphRAG    | 0.474 |  0.276 | 0.533 |
| CyANCHOR    | 0.442 |  0.392 | 0.604 |
