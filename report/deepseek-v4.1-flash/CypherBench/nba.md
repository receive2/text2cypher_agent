# Report — nba (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `nba`, 251 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T20:14:21-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.080 | 0.115 | 251 |   1 |        0 |
| FCAV        | vector    | 0.566 | 0.673 | 251 |   0 |        0 |
| ReAct       | fuzzy     | 0.271 | 0.308 | 251 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.709 | 0.779 | 251 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.789 | 0.871 | 251 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.440 | 0.286 |   0.034 |  0.046 | 0.021 |
| FCAV        |  0.760 | 0.714 |   0.610 |  0.477 | 0.537 |
| ReAct       |  0.720 | 0.571 |   0.356 |  0.092 | 0.200 |
| GraphRAG    |  0.880 | 1.000 |   0.763 |  0.677 | 0.632 |
| CyANCHOR    |  0.840 | 0.857 |   0.864 |  0.754 | 0.747 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.056 |  0.065 | 0.117 |
| FCAV        | 0.722 |  0.529 | 0.558 |
| ReAct       | 0.333 |  0.246 | 0.286 |
| GraphRAG    | 0.861 |  0.754 | 0.558 |
| CyANCHOR    | 0.944 |  0.797 | 0.701 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.460 | 0.331 |   0.082 |  0.095 | 0.042 |
| FCAV        |  0.897 | 0.763 |   0.717 |  0.597 | 0.632 |
| ReAct       |  0.721 | 0.816 |   0.367 |  0.130 | 0.247 |
| GraphRAG    |  0.921 | 0.712 |   0.852 |  0.795 | 0.690 |
| CyANCHOR    |  0.843 | 0.946 |   0.922 |  0.887 | 0.829 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.056 |  0.088 | 0.191 |
| FCAV        | 0.790 |  0.626 | 0.703 |
| ReAct       | 0.343 |  0.268 | 0.364 |
| GraphRAG    | 0.867 |  0.807 | 0.687 |
| CyANCHOR    | 0.944 |  0.873 | 0.832 |
