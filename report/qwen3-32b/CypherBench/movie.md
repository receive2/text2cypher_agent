# Report — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `movie`, 359 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T10:20:06-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.036 | 0.089 | 359 |  35 |        0 |
| FCAV        | vector    | 0.226 | 0.317 | 359 |  46 |        0 |
| ReAct       | fuzzy     | 0.192 | 0.245 | 359 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.295 | 0.428 | 359 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.451 | 0.538 | 359 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.188 | 0.050 |   0.015 |  0.030 | 0.000 |
| FCAV        |  0.531 | 0.267 |   0.242 |  0.168 | 0.150 |
| ReAct       |  0.500 | 0.317 |   0.258 |  0.129 | 0.040 |
| GraphRAG    |  0.625 | 0.533 |   0.394 |  0.178 | 0.100 |
| CyANCHOR    |  0.688 | 0.650 |   0.667 |  0.248 | 0.320 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.021 |  0.026 | 0.057 |
| FCAV        | 0.167 |  0.249 | 0.213 |
| ReAct       | 0.312 |  0.164 | 0.189 |
| GraphRAG    | 0.500 |  0.296 | 0.213 |
| CyANCHOR    | 0.521 |  0.402 | 0.500 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.163 | 0.117 |   0.089 |  0.080 | 0.056 |
| FCAV        |  0.548 | 0.357 |   0.371 |  0.214 | 0.287 |
| ReAct       |  0.483 | 0.380 |   0.323 |  0.166 | 0.116 |
| GraphRAG    |  0.700 | 0.692 |   0.531 |  0.319 | 0.226 |
| CyANCHOR    |  0.734 | 0.726 |   0.730 |  0.345 | 0.431 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.041 |  0.030 | 0.198 |
| FCAV        | 0.218 |  0.317 | 0.356 |
| ReAct       | 0.340 |  0.167 | 0.328 |
| GraphRAG    | 0.572 |  0.379 | 0.448 |
| CyANCHOR    | 0.562 |  0.488 | 0.606 |
