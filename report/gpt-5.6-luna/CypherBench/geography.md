# Report — geography (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `geography`, 331 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06T21:56:47-05:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.088 | 0.108 | 331 |  12 |        0 |
| FCAV        | vector    | 0.326 | 0.367 | 331 |   8 |        0 |
| ReAct       | fuzzy     | 0.317 | 0.360 | 331 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.423 | 0.472 | 331 |   2 |        0 |
| CyANCHOR    | fuzzy+lev | 0.698 | 0.776 | 331 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.167 | 0.021 |   0.127 |  0.089 | 0.071 |
| FCAV        |  0.444 | 0.271 |   0.291 |  0.241 | 0.389 |
| ReAct       |  0.500 | 0.396 |   0.291 |  0.190 | 0.327 |
| GraphRAG    |  0.611 | 0.562 |   0.327 |  0.380 | 0.381 |
| CyANCHOR    |  0.889 | 0.812 |   0.636 |  0.620 | 0.673 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.127 |  0.030 | 0.159 |
| FCAV        | 0.418 |  0.290 | 0.336 |
| ReAct       | 0.273 |  0.290 | 0.383 |
| GraphRAG    | 0.564 |  0.373 | 0.430 |
| CyANCHOR    | 0.764 |  0.633 | 0.766 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.183 | 0.046 |   0.111 |  0.165 | 0.069 |
| FCAV        |  0.475 | 0.255 |   0.265 |  0.306 | 0.474 |
| ReAct       |  0.539 | 0.426 |   0.315 |  0.261 | 0.365 |
| GraphRAG    |  0.632 | 0.552 |   0.321 |  0.540 | 0.412 |
| CyANCHOR    |  0.861 | 0.875 |   0.626 |  0.803 | 0.760 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.146 |  0.048 | 0.184 |
| FCAV        | 0.479 |  0.324 | 0.378 |
| ReAct       | 0.291 |  0.314 | 0.469 |
| GraphRAG    | 0.573 |  0.423 | 0.497 |
| CyANCHOR    | 0.810 |  0.726 | 0.836 |
