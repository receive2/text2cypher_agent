# Report — bloom (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `bloom`, 24 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-07T20:31:55-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.250 | 0.208 |  24 |   0 |        0 |
| FCAV        | vector    | 0.375 | 0.333 |  24 |   0 |        0 |
| ReAct       | fuzzy     | 0.250 | 0.250 |  24 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.625 | 0.542 |  24 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.750 | 0.625 |  24 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.500 | 0.000 |   0.364 |  0.000 |
| FCAV        |  0.250 | 0.500 |   0.455 |  0.200 |
| ReAct       |  0.250 | 0.500 |   0.273 |  0.000 |
| GraphRAG    |  1.000 | 0.250 |   0.636 |  0.600 |
| CyANCHOR    |  1.000 | 1.000 |   0.636 |  0.600 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 1.000 |  0.182 | 1.000 |
| FCAV        | 1.000 |  0.318 | 1.000 |
| ReAct       | 1.000 |  0.182 | 1.000 |
| GraphRAG    | 1.000 |  0.591 | 1.000 |
| CyANCHOR    | 1.000 |  0.727 | 1.000 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.500 | 0.000 |   0.273 |  0.000 |
| FCAV        |  0.250 | 0.500 |   0.364 |  0.200 |
| ReAct       |  0.250 | 0.500 |   0.273 |  0.000 |
| GraphRAG    |  0.750 | 0.250 |   0.636 |  0.400 |
| CyANCHOR    |  0.750 | 1.000 |   0.545 |  0.400 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 1.000 |  0.136 | 1.000 |
| FCAV        | 1.000 |  0.273 | 1.000 |
| ReAct       | 1.000 |  0.182 | 1.000 |
| GraphRAG    | 1.000 |  0.500 | 1.000 |
| CyANCHOR    | 1.000 |  0.591 | 1.000 |
