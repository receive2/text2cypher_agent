# Report — nba (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `nba`, 251 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-14T12:25:56-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.064 | 0.101 | 251 |   4 |        0 |
| FCAV        | vector    | 0.578 | 0.690 | 251 |   2 |        0 |
| ReAct       | fuzzy     | 0.251 | 0.316 | 251 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.610 | 0.725 | 251 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.729 | 0.827 | 251 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.400 | 0.143 |   0.034 |  0.031 | 0.011 |
| FCAV        |  0.840 | 0.714 |   0.627 |  0.492 | 0.526 |
| ReAct       |  0.520 | 0.571 |   0.441 |  0.077 | 0.158 |
| GraphRAG    |  0.840 | 0.857 |   0.780 |  0.615 | 0.421 |
| CyANCHOR    |  0.920 | 0.857 |   0.864 |  0.569 | 0.695 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.051 | 0.117 |
| FCAV        | 0.722 |  0.558 | 0.545 |
| ReAct       | 0.222 |  0.203 | 0.351 |
| GraphRAG    | 0.778 |  0.594 | 0.558 |
| CyANCHOR    | 0.861 |  0.710 | 0.701 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.425 | 0.147 |   0.079 |  0.081 | 0.039 |
| FCAV        |  0.889 | 0.959 |   0.723 |  0.580 | 0.671 |
| ReAct       |  0.613 | 0.616 |   0.481 |  0.132 | 0.241 |
| GraphRAG    |  0.921 | 0.861 |   0.868 |  0.771 | 0.542 |
| CyANCHOR    |  0.981 | 0.908 |   0.925 |  0.673 | 0.825 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.002 |  0.071 | 0.199 |
| FCAV        | 0.741 |  0.662 | 0.715 |
| ReAct       | 0.237 |  0.260 | 0.455 |
| GraphRAG    | 0.811 |  0.701 | 0.727 |
| CyANCHOR    | 0.906 |  0.805 | 0.829 |
