# Report — fictional_character (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `fictional_character`, 324 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-13T21:16:55-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.080 | 0.107 | 324 |   5 |        0 |
| FCAV        | vector    | 0.247 | 0.311 | 324 |   6 |        0 |
| ReAct       | fuzzy     | 0.265 | 0.304 | 324 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.358 | 0.402 | 324 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.540 | 0.597 | 324 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.143 | 0.092 |   0.082 |  0.000 | 0.071 |
| FCAV        |  0.343 | 0.250 |   0.306 |  0.133 | 0.194 |
| ReAct       |  0.371 | 0.263 |   0.412 |  0.100 | 0.153 |
| GraphRAG    |  0.514 | 0.566 |   0.388 |  0.100 | 0.194 |
| CyANCHOR    |  0.657 | 0.592 |   0.694 |  0.233 | 0.418 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.038 |  0.016 | 0.236 |
| FCAV        | 0.170 |  0.176 | 0.438 |
| ReAct       | 0.226 |  0.231 | 0.360 |
| GraphRAG    | 0.434 |  0.319 | 0.393 |
| CyANCHOR    | 0.566 |  0.538 | 0.528 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.157 | 0.110 |   0.119 |  0.066 | 0.090 |
| FCAV        |  0.337 | 0.306 |   0.346 |  0.252 | 0.293 |
| ReAct       |  0.348 | 0.325 |   0.443 |  0.145 | 0.199 |
| GraphRAG    |  0.581 | 0.604 |   0.429 |  0.175 | 0.226 |
| CyANCHOR    |  0.676 | 0.670 |   0.712 |  0.350 | 0.488 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.055 |  0.042 | 0.272 |
| FCAV        | 0.175 |  0.275 | 0.466 |
| ReAct       | 0.226 |  0.281 | 0.396 |
| GraphRAG    | 0.462 |  0.356 | 0.460 |
| CyANCHOR    | 0.553 |  0.607 | 0.603 |
