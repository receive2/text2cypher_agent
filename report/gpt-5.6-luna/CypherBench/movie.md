# Report — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `movie`, 360 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-14T09:27:48-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.042 | 0.110 | 360 |  10 |        0 |
| FCAV        | vector    | 0.456 | 0.536 | 360 |   3 |        0 |
| ReAct       | fuzzy     | 0.333 | 0.395 | 360 |   3 |        0 |
| GraphRAG    | norm-Lev  | 0.456 | 0.543 | 360 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.625 | 0.685 | 360 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.281 | 0.033 |   0.015 |  0.030 | 0.000 |
| FCAV        |  0.750 | 0.450 |   0.478 |  0.297 | 0.510 |
| ReAct       |  0.562 | 0.450 |   0.418 |  0.248 | 0.220 |
| GraphRAG    |  0.844 | 0.800 |   0.552 |  0.307 | 0.210 |
| CyANCHOR    |  0.812 | 0.883 |   0.716 |  0.465 | 0.510 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.021 |  0.037 | 0.057 |
| FCAV        | 0.333 |  0.460 | 0.496 |
| ReAct       | 0.354 |  0.344 | 0.309 |
| GraphRAG    | 0.500 |  0.503 | 0.366 |
| CyANCHOR    | 0.667 |  0.577 | 0.683 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.351 | 0.096 |   0.108 |  0.097 | 0.056 |
| FCAV        |  0.798 | 0.508 |   0.556 |  0.390 | 0.601 |
| ReAct       |  0.615 | 0.520 |   0.500 |  0.309 | 0.268 |
| GraphRAG    |  0.919 | 0.849 |   0.635 |  0.412 | 0.311 |
| CyANCHOR    |  0.838 | 0.926 |   0.774 |  0.513 | 0.606 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.062 |  0.060 | 0.206 |
| FCAV        | 0.432 |  0.515 | 0.608 |
| ReAct       | 0.392 |  0.364 | 0.445 |
| GraphRAG    | 0.585 |  0.536 | 0.538 |
| CyANCHOR    | 0.687 |  0.639 | 0.756 |
