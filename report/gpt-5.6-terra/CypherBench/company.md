# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `company`, 303 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-01T21:28:18-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.112 | 0.141 | 303 |   8 |        0 |
| FCAV        | vector    | 0.429 | 0.542 | 303 |  15 |        0 |
| ReAct       | fuzzy     | 0.462 | 0.500 | 303 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.518 | 0.583 | 303 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.723 | 0.788 | 303 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.290 | 0.070 |   0.180 |  0.075 | 0.057 |
| FCAV        |  0.581 | 0.442 |   0.574 |  0.188 | 0.489 |
| ReAct       |  0.774 | 0.628 |   0.541 |  0.287 | 0.375 |
| GraphRAG    |  0.806 | 0.744 |   0.689 |  0.263 | 0.420 |
| CyANCHOR    |  0.903 | 0.860 |   0.869 |  0.450 | 0.739 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.079 |  0.059 | 0.221 |
| FCAV        | 0.553 |  0.365 | 0.495 |
| ReAct       | 0.605 |  0.412 | 0.495 |
| GraphRAG    | 0.684 |  0.488 | 0.505 |
| CyANCHOR    | 0.842 |  0.688 | 0.737 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.387 | 0.049 |   0.166 |  0.126 | 0.097 |
| FCAV        |  0.761 | 0.502 |   0.599 |  0.324 | 0.644 |
| ReAct       |  0.839 | 0.675 |   0.540 |  0.353 | 0.402 |
| GraphRAG    |  0.935 | 0.815 |   0.674 |  0.366 | 0.478 |
| CyANCHOR    |  1.000 | 0.907 |   0.891 |  0.549 | 0.801 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.158 |  0.074 | 0.254 |
| FCAV        | 0.632 |  0.469 | 0.637 |
| ReAct       | 0.605 |  0.459 | 0.532 |
| GraphRAG    | 0.684 |  0.583 | 0.542 |
| CyANCHOR    | 0.868 |  0.771 | 0.786 |
