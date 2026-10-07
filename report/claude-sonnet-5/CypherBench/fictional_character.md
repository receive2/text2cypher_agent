# Report — fictional_character (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `fictional_character`, 322 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-04T07:04:00-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.124 | 0.146 | 322 |  11 |        0 |
| FCAV        | vector    | 0.531 | 0.561 | 322 |   6 |        0 |
| ReAct       | fuzzy     | 0.379 | 0.414 | 322 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.503 | 0.527 | 322 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.714 | 0.756 | 322 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.429 | 0.132 |   0.096 |  0.000 | 0.071 |
| FCAV        |  0.657 | 0.513 |   0.627 |  0.200 | 0.520 |
| ReAct       |  0.514 | 0.368 |   0.554 |  0.233 | 0.235 |
| GraphRAG    |  0.914 | 0.763 |   0.470 |  0.167 | 0.286 |
| CyANCHOR    |  0.914 | 0.829 |   0.880 |  0.400 | 0.510 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.057 |  0.093 | 0.230 |
| FCAV        | 0.585 |  0.495 | 0.575 |
| ReAct       | 0.358 |  0.357 | 0.437 |
| GraphRAG    | 0.585 |  0.467 | 0.529 |
| CyANCHOR    | 0.736 |  0.698 | 0.736 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.422 | 0.138 |   0.140 |  0.042 | 0.090 |
| FCAV        |  0.694 | 0.519 |   0.614 |  0.246 | 0.596 |
| ReAct       |  0.558 | 0.407 |   0.533 |  0.306 | 0.300 |
| GraphRAG    |  0.907 | 0.764 |   0.500 |  0.209 | 0.326 |
| CyANCHOR    |  0.947 | 0.878 |   0.889 |  0.450 | 0.573 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.079 |  0.111 | 0.259 |
| FCAV        | 0.591 |  0.525 | 0.617 |
| ReAct       | 0.399 |  0.387 | 0.480 |
| GraphRAG    | 0.613 |  0.487 | 0.556 |
| CyANCHOR    | 0.746 |  0.759 | 0.757 |
