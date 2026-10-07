# Report — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `flight_accident`, 168 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-04T09:01:12-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.244 | 0.241 | 168 |   1 |        0 |
| FCAV        | vector    | 0.720 | 0.788 | 168 |   3 |        0 |
| ReAct       | fuzzy     | 0.542 | 0.597 | 168 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.583 | 0.633 | 168 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.827 | 0.899 | 168 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.400 | 0.500 |   0.222 |  0.225 | 0.167 |
| FCAV        |  0.933 | 0.900 |   0.889 |  0.618 | 0.750 |
| ReAct       |  0.867 | 0.600 |   0.778 |  0.449 | 0.500 |
| GraphRAG    |  0.933 | 0.900 |   0.833 |  0.494 | 0.444 |
| CyANCHOR    |  1.000 | 0.900 |   0.889 |  0.798 | 0.778 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.294 |  0.167 | 0.311 |
| FCAV        | 0.902 |  0.528 | 0.822 |
| ReAct       | 0.667 |  0.417 | 0.600 |
| GraphRAG    | 0.706 |  0.458 | 0.644 |
| CyANCHOR    | 0.902 |  0.764 | 0.844 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.448 | 0.500 |   0.200 |  0.227 | 0.135 |
| FCAV        |  1.000 | 0.900 |   0.907 |  0.715 | 0.789 |
| ReAct       |  0.867 | 0.600 |   0.889 |  0.514 | 0.541 |
| GraphRAG    |  0.981 | 0.874 |   0.867 |  0.558 | 0.489 |
| CyANCHOR    |  1.000 | 0.905 |   0.963 |  0.904 | 0.812 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.314 |  0.144 | 0.311 |
| FCAV        | 0.908 |  0.657 | 0.860 |
| ReAct       | 0.669 |  0.532 | 0.617 |
| GraphRAG    | 0.706 |  0.565 | 0.659 |
| CyANCHOR    | 0.870 |  0.923 | 0.894 |
