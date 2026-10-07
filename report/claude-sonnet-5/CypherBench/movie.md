# Report — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `movie`, 359 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-04T19:34:52-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.123 | 0.193 | 359 |   5 |        0 |
| FCAV        | vector    | 0.535 | 0.638 | 359 |   7 |        0 |
| ReAct       | fuzzy     | 0.407 | 0.478 | 359 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.493 | 0.619 | 359 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.691 | 0.762 | 359 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.531 | 0.217 |   0.045 |  0.059 | 0.050 |
| FCAV        |  0.875 | 0.600 |   0.591 |  0.327 | 0.560 |
| ReAct       |  0.781 | 0.600 |   0.530 |  0.297 | 0.200 |
| GraphRAG    |  0.875 | 0.783 |   0.606 |  0.297 | 0.320 |
| CyANCHOR    |  0.938 | 0.883 |   0.848 |  0.554 | 0.530 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.062 |  0.143 | 0.115 |
| FCAV        | 0.521 |  0.556 | 0.508 |
| ReAct       | 0.479 |  0.392 | 0.402 |
| GraphRAG    | 0.521 |  0.556 | 0.385 |
| CyANCHOR    | 0.708 |  0.661 | 0.730 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.566 | 0.255 |   0.146 |  0.139 | 0.123 |
| FCAV        |  0.932 | 0.708 |   0.680 |  0.437 | 0.678 |
| ReAct       |  0.809 | 0.663 |   0.604 |  0.369 | 0.289 |
| GraphRAG    |  0.904 | 0.903 |   0.735 |  0.476 | 0.426 |
| CyANCHOR    |  0.965 | 0.925 |   0.913 |  0.641 | 0.621 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.103 |  0.153 | 0.290 |
| FCAV        | 0.594 |  0.637 | 0.657 |
| ReAct       | 0.522 |  0.420 | 0.552 |
| GraphRAG    | 0.606 |  0.652 | 0.574 |
| CyANCHOR    | 0.752 |  0.739 | 0.802 |
