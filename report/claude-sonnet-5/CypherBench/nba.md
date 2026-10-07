# Report — nba (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `nba`, 251 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-04T22:51:30-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.112 | 0.162 | 251 |   5 |        0 |
| FCAV        | vector    | 0.681 | 0.798 | 251 |   3 |        0 |
| ReAct       | fuzzy     | 0.426 | 0.509 | 251 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.629 | 0.781 | 251 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.713 | 0.874 | 251 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.560 | 0.286 |   0.068 |  0.062 | 0.042 |
| FCAV        |  0.840 | 0.857 |   0.831 |  0.508 | 0.653 |
| ReAct       |  0.760 | 0.714 |   0.559 |  0.354 | 0.284 |
| GraphRAG    |  0.840 | 0.857 |   0.763 |  0.600 | 0.495 |
| CyANCHOR    |  0.760 | 0.714 |   0.864 |  0.738 | 0.589 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.139 |  0.087 | 0.143 |
| FCAV        | 0.917 |  0.645 | 0.636 |
| ReAct       | 0.528 |  0.435 | 0.364 |
| GraphRAG    | 0.861 |  0.630 | 0.519 |
| CyANCHOR    | 0.917 |  0.717 | 0.610 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.625 | 0.290 |   0.127 |  0.138 | 0.069 |
| FCAV        |  0.905 | 0.959 |   0.901 |  0.636 | 0.805 |
| ReAct       |  0.901 | 0.759 |   0.575 |  0.464 | 0.378 |
| GraphRAG    |  0.945 | 0.800 |   0.873 |  0.791 | 0.671 |
| CyANCHOR    |  0.977 | 0.817 |   0.968 |  0.932 | 0.752 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.139 |  0.142 | 0.210 |
| FCAV        | 0.924 |  0.780 | 0.771 |
| ReAct       | 0.528 |  0.527 | 0.470 |
| GraphRAG    | 0.861 |  0.817 | 0.677 |
| CyANCHOR    | 0.918 |  0.909 | 0.788 |
