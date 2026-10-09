# Report — politics (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `politics`, 356 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-08T09:57:11-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.140 | 0.157 | 356 |   4 |        0 |
| FCAV        | vector    | 0.289 | 0.359 | 356 |   5 |        0 |
| ReAct       | fuzzy     | 0.323 | 0.386 | 356 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.447 | 0.526 | 356 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.615 | 0.702 | 356 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.444 | 0.333 |   0.133 |  0.104 | 0.111 |
| FCAV        |  0.389 | 0.429 |   0.289 |  0.231 | 0.343 |
| ReAct       |  0.722 | 0.810 |   0.467 |  0.185 | 0.323 |
| GraphRAG    |  0.722 | 0.762 |   0.444 |  0.439 | 0.343 |
| CyANCHOR    |  0.833 | 0.857 |   0.711 |  0.543 | 0.606 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.143 |  0.095 | 0.216 |
| FCAV        | 0.357 |  0.259 | 0.306 |
| ReAct       | 0.464 |  0.249 | 0.378 |
| GraphRAG    | 0.589 |  0.460 | 0.351 |
| CyANCHOR    | 0.696 |  0.619 | 0.568 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.436 | 0.276 |   0.134 |  0.130 | 0.140 |
| FCAV        |  0.441 | 0.368 |   0.369 |  0.316 | 0.414 |
| ReAct       |  0.717 | 0.828 |   0.539 |  0.224 | 0.444 |
| GraphRAG    |  0.736 | 0.738 |   0.476 |  0.546 | 0.432 |
| CyANCHOR    |  0.855 | 0.889 |   0.816 |  0.640 | 0.691 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.140 |  0.103 | 0.258 |
| FCAV        | 0.429 |  0.333 | 0.368 |
| ReAct       | 0.478 |  0.323 | 0.446 |
| GraphRAG    | 0.622 |  0.554 | 0.430 |
| CyANCHOR    | 0.739 |  0.707 | 0.675 |
