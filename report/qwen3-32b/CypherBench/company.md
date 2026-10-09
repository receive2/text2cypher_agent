# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `company`, 303 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06T18:20:53-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.069 | 0.073 | 303 |  20 |        0 |
| FCAV        | vector    | 0.211 | 0.224 | 303 |  31 |        0 |
| ReAct       | fuzzy     | 0.215 | 0.234 | 303 |   2 |        0 |
| GraphRAG    | norm-Lev  | 0.343 | 0.400 | 303 |   1 |        0 |
| CyANCHOR    | fuzzy+lev | 0.393 | 0.455 | 303 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.097 | 0.070 |   0.131 |  0.037 | 0.045 |
| FCAV        |  0.290 | 0.326 |   0.279 |  0.075 | 0.205 |
| ReAct       |  0.258 | 0.302 |   0.295 |  0.100 | 0.205 |
| GraphRAG    |  0.484 | 0.581 |   0.410 |  0.150 | 0.307 |
| CyANCHOR    |  0.419 | 0.512 |   0.639 |  0.212 | 0.318 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.012 | 0.200 |
| FCAV        | 0.263 |  0.159 | 0.284 |
| ReAct       | 0.132 |  0.159 | 0.347 |
| GraphRAG    | 0.474 |  0.312 | 0.347 |
| CyANCHOR    | 0.553 |  0.324 | 0.453 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.186 | 0.053 |   0.117 |  0.045 | 0.039 |
| FCAV        |  0.419 | 0.257 |   0.292 |  0.087 | 0.218 |
| ReAct       |  0.443 | 0.247 |   0.322 |  0.111 | 0.203 |
| GraphRAG    |  0.683 | 0.557 |   0.458 |  0.219 | 0.349 |
| CyANCHOR    |  0.647 | 0.535 |   0.723 |  0.230 | 0.368 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.026 |  0.024 | 0.181 |
| FCAV        | 0.237 |  0.176 | 0.305 |
| ReAct       | 0.158 |  0.187 | 0.347 |
| GraphRAG    | 0.526 |  0.362 | 0.419 |
| CyANCHOR    | 0.592 |  0.406 | 0.488 |
