# Report — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `flight_accident`, 168 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06T20:50:37-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.095 | 0.096 | 168 |   3 |        0 |
| FCAV        | vector    | 0.351 | 0.418 | 168 |   9 |        0 |
| ReAct       | fuzzy     | 0.262 | 0.302 | 168 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.476 | 0.537 | 168 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.696 | 0.766 | 168 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.267 | 0.100 |   0.056 |  0.090 | 0.056 |
| FCAV        |  0.667 | 0.400 |   0.444 |  0.292 | 0.306 |
| ReAct       |  0.400 | 0.400 |   0.444 |  0.180 | 0.278 |
| GraphRAG    |  0.800 | 0.700 |   0.722 |  0.371 | 0.417 |
| CyANCHOR    |  0.933 | 0.800 |   0.778 |  0.640 | 0.667 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.078 |  0.000 | 0.267 |
| FCAV        | 0.373 |  0.236 | 0.511 |
| ReAct       | 0.314 |  0.181 | 0.333 |
| GraphRAG    | 0.569 |  0.333 | 0.600 |
| CyANCHOR    | 0.745 |  0.611 | 0.778 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.314 | 0.077 |   0.033 |  0.099 | 0.035 |
| FCAV        |  0.757 | 0.505 |   0.574 |  0.348 | 0.350 |
| ReAct       |  0.467 | 0.471 |   0.519 |  0.215 | 0.294 |
| GraphRAG    |  0.914 | 0.709 |   0.830 |  0.454 | 0.393 |
| CyANCHOR    |  0.888 | 0.805 |   0.881 |  0.741 | 0.709 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.099 |  0.000 | 0.247 |
| FCAV        | 0.399 |  0.370 | 0.517 |
| ReAct       | 0.326 |  0.263 | 0.339 |
| GraphRAG    | 0.570 |  0.447 | 0.645 |
| CyANCHOR    | 0.753 |  0.734 | 0.832 |
