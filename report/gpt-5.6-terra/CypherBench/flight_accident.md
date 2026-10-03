# Report — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `flight_accident`, 168 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-01T22:24:00-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.179 | 0.190 | 168 |   2 |        0 |
| FCAV        | vector    | 0.667 | 0.724 | 168 |   2 |        0 |
| ReAct       | fuzzy     | 0.464 | 0.466 | 168 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.637 | 0.637 | 168 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.887 | 0.910 | 168 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.267 | 0.100 |   0.056 |  0.236 | 0.083 |
| FCAV        |  0.800 | 0.800 |   0.833 |  0.573 | 0.722 |
| ReAct       |  0.667 | 0.600 |   0.722 |  0.393 | 0.389 |
| GraphRAG    |  0.800 | 0.900 |   0.889 |  0.573 | 0.528 |
| CyANCHOR    |  1.000 | 1.000 |   0.889 |  0.854 | 0.889 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.118 |  0.111 | 0.356 |
| FCAV        | 0.843 |  0.472 | 0.778 |
| ReAct       | 0.490 |  0.347 | 0.622 |
| GraphRAG    | 0.706 |  0.556 | 0.689 |
| CyANCHOR    | 0.941 |  0.861 | 0.867 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.381 | 0.164 |   0.033 |  0.243 | 0.066 |
| FCAV        |  0.848 | 0.800 |   0.830 |  0.667 | 0.739 |
| ReAct       |  0.667 | 0.600 |   0.694 |  0.407 | 0.376 |
| GraphRAG    |  0.803 | 0.964 |   0.922 |  0.592 | 0.447 |
| CyANCHOR    |  1.000 | 1.000 |   0.889 |  0.902 | 0.881 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.155 |  0.128 | 0.329 |
| FCAV        | 0.822 |  0.583 | 0.838 |
| ReAct       | 0.493 |  0.353 | 0.616 |
| GraphRAG    | 0.676 |  0.589 | 0.672 |
| CyANCHOR    | 0.941 |  0.893 | 0.903 |
