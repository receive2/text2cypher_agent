# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `company`, 303 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-04T03:09:36-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.152 | 0.163 | 303 |   5 |        0 |
| FCAV        | vector    | 0.528 | 0.581 | 303 |   6 |        0 |
| ReAct       | fuzzy     | 0.587 | 0.636 | 303 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.551 | 0.601 | 303 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.690 | 0.752 | 303 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.419 | 0.256 |   0.164 |  0.075 | 0.068 |
| FCAV        |  0.645 | 0.558 |   0.607 |  0.338 | 0.591 |
| ReAct       |  0.742 | 0.721 |   0.607 |  0.537 | 0.500 |
| GraphRAG    |  0.677 | 0.860 |   0.689 |  0.375 | 0.420 |
| CyANCHOR    |  0.871 | 0.837 |   0.918 |  0.475 | 0.591 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.079 |  0.112 | 0.253 |
| FCAV        | 0.737 |  0.465 | 0.558 |
| ReAct       | 0.605 |  0.553 | 0.642 |
| GraphRAG    | 0.711 |  0.518 | 0.547 |
| CyANCHOR    | 0.816 |  0.659 | 0.695 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.484 | 0.245 |   0.150 |  0.109 | 0.069 |
| FCAV        |  0.862 | 0.583 |   0.578 |  0.383 | 0.663 |
| ReAct       |  0.839 | 0.724 |   0.621 |  0.613 | 0.554 |
| GraphRAG    |  0.904 | 0.830 |   0.667 |  0.441 | 0.483 |
| CyANCHOR    |  0.996 | 0.837 |   0.944 |  0.551 | 0.674 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.079 |  0.125 | 0.266 |
| FCAV        | 0.763 |  0.544 | 0.574 |
| ReAct       | 0.605 |  0.614 | 0.688 |
| GraphRAG    | 0.711 |  0.586 | 0.585 |
| CyANCHOR    | 0.816 |  0.731 | 0.764 |
