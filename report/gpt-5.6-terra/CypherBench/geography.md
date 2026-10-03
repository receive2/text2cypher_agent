# Report — geography (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `geography`, 331 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02T01:29:00-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.097 | 0.160 | 331 |   6 |        0 |
| FCAV        | vector    | 0.393 | 0.513 | 331 |   6 |        0 |
| ReAct       | fuzzy     | 0.408 | 0.474 | 331 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.435 | 0.523 | 331 |   2 |        0 |
| CyANCHOR    | fuzzy+lev | 0.710 | 0.806 | 331 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.278 | 0.021 |   0.127 |  0.076 | 0.071 |
| FCAV        |  0.556 | 0.417 |   0.309 |  0.203 | 0.504 |
| ReAct       |  0.778 | 0.625 |   0.436 |  0.139 | 0.372 |
| GraphRAG    |  0.556 | 0.583 |   0.364 |  0.380 | 0.407 |
| CyANCHOR    |  0.833 | 0.854 |   0.673 |  0.658 | 0.664 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.091 |  0.065 | 0.150 |
| FCAV        | 0.636 |  0.331 | 0.364 |
| ReAct       | 0.436 |  0.373 | 0.449 |
| GraphRAG    | 0.582 |  0.408 | 0.402 |
| CyANCHOR    | 0.818 |  0.669 | 0.720 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.353 | 0.054 |   0.131 |  0.269 | 0.080 |
| FCAV        |  0.677 | 0.437 |   0.348 |  0.385 | 0.662 |
| ReAct       |  0.889 | 0.752 |   0.453 |  0.220 | 0.412 |
| GraphRAG    |  0.655 | 0.699 |   0.354 |  0.506 | 0.501 |
| CyANCHOR    |  0.907 | 0.944 |   0.668 |  0.786 | 0.795 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.147 |  0.137 | 0.201 |
| FCAV        | 0.727 |  0.479 | 0.456 |
| ReAct       | 0.455 |  0.426 | 0.560 |
| GraphRAG    | 0.612 |  0.508 | 0.502 |
| CyANCHOR    | 0.878 |  0.776 | 0.816 |
