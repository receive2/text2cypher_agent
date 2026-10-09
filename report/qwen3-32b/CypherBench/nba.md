# Report — nba (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `nba`, 251 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T14:39:32-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.032 | 0.073 | 251 |  28 |        0 |
| FCAV        | vector    | 0.319 | 0.390 | 251 |  35 |        0 |
| ReAct       | fuzzy     | 0.167 | 0.235 | 251 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.486 | 0.627 | 251 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.614 | 0.722 | 251 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.120 | 0.143 |   0.017 |  0.031 | 0.011 |
| FCAV        |  0.600 | 0.571 |   0.356 |  0.277 | 0.232 |
| ReAct       |  0.360 | 0.571 |   0.220 |  0.077 | 0.116 |
| GraphRAG    |  0.760 | 0.714 |   0.610 |  0.400 | 0.379 |
| CyANCHOR    |  0.800 | 0.571 |   0.763 |  0.554 | 0.516 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.014 | 0.078 |
| FCAV        | 0.444 |  0.275 | 0.338 |
| ReAct       | 0.306 |  0.123 | 0.182 |
| GraphRAG    | 0.861 |  0.471 | 0.338 |
| CyANCHOR    | 0.833 |  0.551 | 0.623 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.100 | 0.204 |   0.071 |  0.083 | 0.050 |
| FCAV        |  0.590 | 0.514 |   0.411 |  0.356 | 0.338 |
| ReAct       |  0.483 | 0.759 |   0.253 |  0.156 | 0.173 |
| GraphRAG    |  0.815 | 0.702 |   0.781 |  0.615 | 0.485 |
| CyANCHOR    |  0.842 | 0.714 |   0.846 |  0.735 | 0.607 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.034 | 0.176 |
| FCAV        | 0.437 |  0.341 | 0.457 |
| ReAct       | 0.316 |  0.167 | 0.319 |
| GraphRAG    | 0.829 |  0.620 | 0.547 |
| CyANCHOR    | 0.833 |  0.682 | 0.743 |
