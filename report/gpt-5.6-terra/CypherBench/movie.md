# Report — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `movie`, 359 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02T04:21:49-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.064 | 0.127 | 359 |  11 |        0 |
| FCAV        | vector    | 0.460 | 0.547 | 359 |  18 |        0 |
| ReAct       | fuzzy     | 0.276 | 0.342 | 359 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.415 | 0.551 | 359 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.646 | 0.735 | 359 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.406 | 0.050 |   0.061 |  0.030 | 0.000 |
| FCAV        |  0.844 | 0.550 |   0.561 |  0.287 | 0.390 |
| ReAct       |  0.469 | 0.417 |   0.455 |  0.188 | 0.100 |
| GraphRAG    |  0.875 | 0.650 |   0.545 |  0.228 | 0.230 |
| CyANCHOR    |  0.938 | 0.883 |   0.758 |  0.416 | 0.570 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.042 |  0.048 | 0.098 |
| FCAV        | 0.521 |  0.434 | 0.475 |
| ReAct       | 0.396 |  0.249 | 0.270 |
| GraphRAG    | 0.521 |  0.460 | 0.303 |
| CyANCHOR    | 0.625 |  0.624 | 0.689 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.407 | 0.098 |   0.170 |  0.097 | 0.056 |
| FCAV        |  0.898 | 0.633 |   0.645 |  0.366 | 0.502 |
| ReAct       |  0.547 | 0.476 |   0.541 |  0.243 | 0.165 |
| GraphRAG    |  0.932 | 0.776 |   0.681 |  0.426 | 0.335 |
| CyANCHOR    |  0.963 | 0.914 |   0.847 |  0.539 | 0.680 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.082 |  0.054 | 0.256 |
| FCAV        | 0.534 |  0.507 | 0.615 |
| ReAct       | 0.419 |  0.288 | 0.397 |
| GraphRAG    | 0.565 |  0.560 | 0.533 |
| CyANCHOR    | 0.694 |  0.703 | 0.802 |
