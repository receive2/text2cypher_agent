# Report — politics (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `politics`, 356 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-05T05:52:27-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.202 | 0.226 | 356 |   6 |        0 |
| FCAV        | vector    | 0.469 | 0.557 | 356 |   2 |        0 |
| ReAct       | fuzzy     | 0.520 | 0.627 | 356 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.497 | 0.548 | 356 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.663 | 0.743 | 356 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.500 | 0.429 |   0.200 |  0.173 | 0.152 |
| FCAV        |  0.944 | 0.714 |   0.578 |  0.341 | 0.505 |
| ReAct       |  0.778 | 0.810 |   0.667 |  0.457 | 0.455 |
| GraphRAG    |  0.778 | 0.857 |   0.667 |  0.434 | 0.404 |
| CyANCHOR    |  0.944 | 0.905 |   0.867 |  0.595 | 0.586 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.214 |  0.169 | 0.252 |
| FCAV        | 0.714 |  0.434 | 0.405 |
| ReAct       | 0.571 |  0.508 | 0.514 |
| GraphRAG    | 0.679 |  0.492 | 0.414 |
| CyANCHOR    | 0.732 |  0.683 | 0.595 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.535 | 0.390 |   0.234 |  0.211 | 0.158 |
| FCAV        |  0.944 | 0.692 |   0.652 |  0.432 | 0.631 |
| ReAct       |  0.760 | 0.809 |   0.770 |  0.601 | 0.545 |
| GraphRAG    |  0.813 | 0.870 |   0.679 |  0.495 | 0.464 |
| CyANCHOR    |  0.926 | 0.921 |   0.906 |  0.702 | 0.671 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.202 |  0.178 | 0.320 |
| FCAV        | 0.762 |  0.525 | 0.507 |
| ReAct       | 0.607 |  0.619 | 0.650 |
| GraphRAG    | 0.700 |  0.533 | 0.497 |
| CyANCHOR    | 0.783 |  0.760 | 0.695 |
