# Report — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `flight_accident`, 168 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-13T23:10:51-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.155 | 0.155 | 168 |   0 |        0 |
| FCAV        | vector    | 0.530 | 0.572 | 168 |   1 |        0 |
| ReAct       | fuzzy     | 0.405 | 0.424 | 168 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.494 | 0.543 | 168 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.833 | 0.866 | 168 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.400 | 0.100 |   0.056 |  0.157 | 0.111 |
| FCAV        |  0.800 | 0.700 |   0.333 |  0.506 | 0.528 |
| ReAct       |  0.667 | 0.400 |   0.556 |  0.337 | 0.389 |
| GraphRAG    |  0.667 | 0.800 |   0.556 |  0.449 | 0.417 |
| CyANCHOR    |  1.000 | 0.900 |   1.000 |  0.787 | 0.778 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.118 |  0.069 | 0.333 |
| FCAV        | 0.549 |  0.417 | 0.689 |
| ReAct       | 0.392 |  0.292 | 0.600 |
| GraphRAG    | 0.569 |  0.389 | 0.578 |
| CyANCHOR    | 0.882 |  0.750 | 0.911 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.447 | 0.100 |   0.033 |  0.174 | 0.063 |
| FCAV        |  0.745 | 0.609 |   0.358 |  0.592 | 0.548 |
| ReAct       |  0.667 | 0.400 |   0.556 |  0.386 | 0.358 |
| GraphRAG    |  0.714 | 0.771 |   0.635 |  0.533 | 0.387 |
| CyANCHOR    |  1.000 | 0.900 |   0.963 |  0.857 | 0.773 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.124 |  0.065 | 0.333 |
| FCAV        | 0.505 |  0.548 | 0.687 |
| ReAct       | 0.384 |  0.329 | 0.622 |
| GraphRAG    | 0.529 |  0.516 | 0.601 |
| CyANCHOR    | 0.837 |  0.846 | 0.930 |
