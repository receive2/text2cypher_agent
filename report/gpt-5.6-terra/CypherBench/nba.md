# Report — nba (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `nba`, 251 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02T10:01:09-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.092 | 0.127 | 251 |   4 |        0 |
| FCAV        | vector    | 0.586 | 0.822 | 251 |   5 |        0 |
| ReAct       | fuzzy     | 0.319 | 0.377 | 251 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.618 | 0.764 | 251 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.777 | 0.904 | 251 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.440 | 0.286 |   0.068 |  0.062 | 0.021 |
| FCAV        |  0.720 | 0.571 |   0.695 |  0.385 | 0.621 |
| ReAct       |  0.720 | 0.857 |   0.475 |  0.154 | 0.189 |
| GraphRAG    |  0.760 | 0.857 |   0.797 |  0.554 | 0.495 |
| CyANCHOR    |  0.800 | 0.857 |   0.881 |  0.692 | 0.758 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.111 |  0.065 | 0.130 |
| FCAV        | 0.833 |  0.529 | 0.571 |
| ReAct       | 0.472 |  0.261 | 0.351 |
| GraphRAG    | 0.833 |  0.601 | 0.545 |
| CyANCHOR    | 0.944 |  0.783 | 0.688 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.500 | 0.229 |   0.110 |  0.108 | 0.046 |
| FCAV        |  0.960 | 0.714 |   0.855 |  0.711 | 0.849 |
| ReAct       |  0.827 | 0.800 |   0.489 |  0.212 | 0.271 |
| GraphRAG    |  0.921 | 0.800 |   0.895 |  0.736 | 0.658 |
| CyANCHOR    |  0.981 | 0.959 |   0.943 |  0.875 | 0.876 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.111 |  0.089 | 0.204 |
| FCAV        | 0.898 |  0.794 | 0.837 |
| ReAct       | 0.472 |  0.319 | 0.437 |
| GraphRAG    | 0.814 |  0.758 | 0.753 |
| CyANCHOR    | 0.944 |  0.912 | 0.871 |
