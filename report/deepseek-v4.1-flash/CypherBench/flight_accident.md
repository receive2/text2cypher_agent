# Report — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `flight_accident`, 168 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T10:04:48-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.208 | 0.214 | 168 |   2 |        0 |
| FCAV        | vector    | 0.613 | 0.666 | 168 |   1 |        0 |
| ReAct       | fuzzy     | 0.524 | 0.544 | 168 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.583 | 0.610 | 168 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.851 | 0.898 | 168 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.400 | 0.100 |   0.333 |  0.202 | 0.111 |
| FCAV        |  0.800 | 0.800 |   0.722 |  0.539 | 0.611 |
| ReAct       |  0.800 | 0.800 |   0.722 |  0.393 | 0.556 |
| GraphRAG    |  0.667 | 0.800 |   0.667 |  0.539 | 0.556 |
| CyANCHOR    |  1.000 | 1.000 |   0.889 |  0.798 | 0.861 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.275 |  0.056 | 0.378 |
| FCAV        | 0.765 |  0.458 | 0.689 |
| ReAct       | 0.569 |  0.458 | 0.578 |
| GraphRAG    | 0.627 |  0.500 | 0.667 |
| CyANCHOR    | 0.843 |  0.833 | 0.889 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.447 | 0.100 |   0.274 |  0.225 | 0.090 |
| FCAV        |  0.914 | 0.800 |   0.796 |  0.604 | 0.611 |
| ReAct       |  0.781 | 0.800 |   0.756 |  0.440 | 0.528 |
| GraphRAG    |  0.714 | 0.856 |   0.719 |  0.589 | 0.494 |
| CyANCHOR    |  1.000 | 1.000 |   0.922 |  0.880 | 0.861 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.301 |  0.056 | 0.369 |
| FCAV        | 0.753 |  0.567 | 0.725 |
| ReAct       | 0.571 |  0.496 | 0.591 |
| GraphRAG    | 0.618 |  0.570 | 0.663 |
| CyANCHOR    | 0.843 |  0.939 | 0.895 |
