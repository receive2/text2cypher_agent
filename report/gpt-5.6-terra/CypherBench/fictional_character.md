# Report — fictional_character (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `fictional_character`, 322 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-01T20:21:55-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.090 | 0.115 | 322 |   0 |        0 |
| FCAV        | vector    | 0.444 | 0.523 | 322 |   0 |        0 |
| ReAct       | fuzzy     | 0.295 | 0.333 | 322 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.425 | 0.479 | 322 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.683 | 0.745 | 322 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.200 | 0.118 |   0.072 |  0.000 | 0.071 |
| FCAV        |  0.543 | 0.408 |   0.434 |  0.200 | 0.520 |
| ReAct       |  0.371 | 0.355 |   0.458 |  0.067 | 0.153 |
| GraphRAG    |  0.771 | 0.671 |   0.386 |  0.167 | 0.224 |
| CyANCHOR    |  0.886 | 0.829 |   0.843 |  0.233 | 0.500 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.038 |  0.038 | 0.230 |
| FCAV        | 0.528 |  0.407 | 0.471 |
| ReAct       | 0.358 |  0.258 | 0.333 |
| GraphRAG    | 0.509 |  0.368 | 0.494 |
| CyANCHOR    | 0.698 |  0.681 | 0.678 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.216 | 0.117 |   0.119 |  0.042 | 0.095 |
| FCAV        |  0.594 | 0.479 |   0.477 |  0.367 | 0.620 |
| ReAct       |  0.396 | 0.386 |   0.512 |  0.093 | 0.192 |
| GraphRAG    |  0.827 | 0.706 |   0.436 |  0.237 | 0.288 |
| CyANCHOR    |  0.866 | 0.874 |   0.884 |  0.331 | 0.609 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.063 |  0.054 | 0.272 |
| FCAV        | 0.528 |  0.515 | 0.538 |
| ReAct       | 0.371 |  0.298 | 0.383 |
| GraphRAG    | 0.546 |  0.436 | 0.527 |
| CyANCHOR    | 0.730 |  0.755 | 0.732 |
