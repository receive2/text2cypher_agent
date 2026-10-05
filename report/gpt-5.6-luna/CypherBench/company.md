# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `company`, 305 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-13T17:26:44-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node_rel` · escalate `on` (≤3) · semantic_repair `on` (≤4) · empty_is_wrong `off` · value_snap `on`.

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
| No Val Link | —         | 0.102 | 0.105 | 305 |   5 |        0 |
| FCAV        | vector    | 0.341 | 0.398 | 305 |   7 |        0 |
| ReAct       | fuzzy     | 0.315 | 0.357 | 305 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.475 | 0.501 | 305 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.695 | 0.730 | 305 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.323 | 0.070 |   0.111 |  0.087 | 0.045 |
| FCAV        |  0.581 | 0.302 |   0.317 |  0.188 | 0.432 |
| ReAct       |  0.516 | 0.349 |   0.397 |  0.125 | 0.341 |
| GraphRAG    |  0.742 | 0.698 |   0.540 |  0.250 | 0.432 |
| CyANCHOR    |  0.774 | 0.791 |   0.825 |  0.537 | 0.670 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.051 |  0.047 | 0.221 |
| FCAV        | 0.308 |  0.281 | 0.463 |
| ReAct       | 0.359 |  0.234 | 0.442 |
| GraphRAG    | 0.615 |  0.450 | 0.463 |
| CyANCHOR    | 0.769 |  0.673 | 0.705 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.323 | 0.050 |   0.098 |  0.125 | 0.042 |
| FCAV        |  0.679 | 0.348 |   0.320 |  0.268 | 0.498 |
| ReAct       |  0.570 | 0.449 |   0.411 |  0.190 | 0.351 |
| GraphRAG    |  0.837 | 0.672 |   0.527 |  0.297 | 0.465 |
| CyANCHOR    |  0.867 | 0.805 |   0.837 |  0.570 | 0.714 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.051 |  0.055 | 0.217 |
| FCAV        | 0.308 |  0.346 | 0.529 |
| ReAct       | 0.375 |  0.284 | 0.481 |
| GraphRAG    | 0.615 |  0.481 | 0.489 |
| CyANCHOR    | 0.836 |  0.696 | 0.748 |
