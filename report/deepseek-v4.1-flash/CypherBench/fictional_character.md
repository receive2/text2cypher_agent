# Report — fictional_character (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `fictional_character`, 322 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T08:25:25-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.121 | 0.145 | 322 |   2 |        0 |
| FCAV        | vector    | 0.323 | 0.386 | 322 |   3 |        0 |
| ReAct       | fuzzy     | 0.276 | 0.316 | 322 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.453 | 0.487 | 322 |   1 |        0 |
| CyANCHOR    | fuzzy+lev | 0.615 | 0.666 | 322 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.286 | 0.118 |   0.084 |  0.067 | 0.112 |
| FCAV        |  0.429 | 0.289 |   0.373 |  0.167 | 0.316 |
| ReAct       |  0.314 | 0.342 |   0.386 |  0.167 | 0.153 |
| GraphRAG    |  0.800 | 0.684 |   0.386 |  0.133 | 0.306 |
| CyANCHOR    |  0.714 | 0.658 |   0.795 |  0.267 | 0.500 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.038 |  0.077 | 0.264 |
| FCAV        | 0.302 |  0.269 | 0.448 |
| ReAct       | 0.283 |  0.275 | 0.276 |
| GraphRAG    | 0.509 |  0.440 | 0.448 |
| CyANCHOR    | 0.717 |  0.593 | 0.598 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.337 | 0.101 |   0.135 |  0.122 | 0.127 |
| FCAV        |  0.495 | 0.349 |   0.440 |  0.256 | 0.369 |
| ReAct       |  0.310 | 0.371 |   0.459 |  0.202 | 0.190 |
| GraphRAG    |  0.812 | 0.678 |   0.432 |  0.229 | 0.348 |
| CyANCHOR    |  0.821 | 0.722 |   0.808 |  0.347 | 0.543 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.069 |  0.092 | 0.303 |
| FCAV        | 0.338 |  0.337 | 0.516 |
| ReAct       | 0.290 |  0.299 | 0.368 |
| GraphRAG    | 0.532 |  0.468 | 0.500 |
| CyANCHOR    | 0.729 |  0.655 | 0.650 |
