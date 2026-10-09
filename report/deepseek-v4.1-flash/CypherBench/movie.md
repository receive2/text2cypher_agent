# Report — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `movie`, 359 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T17:49:53-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.103 | 0.172 | 359 |   1 |        0 |
| FCAV        | vector    | 0.415 | 0.494 | 359 |   3 |        0 |
| ReAct       | fuzzy     | 0.287 | 0.360 | 359 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.487 | 0.595 | 359 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.705 | 0.772 | 359 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.406 | 0.183 |   0.061 |  0.069 | 0.020 |
| FCAV        |  0.688 | 0.550 |   0.439 |  0.277 | 0.370 |
| ReAct       |  0.438 | 0.550 |   0.348 |  0.208 | 0.120 |
| GraphRAG    |  0.844 | 0.700 |   0.591 |  0.406 | 0.260 |
| CyANCHOR    |  0.906 | 0.900 |   0.818 |  0.673 | 0.480 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.062 |  0.095 | 0.131 |
| FCAV        | 0.333 |  0.450 | 0.393 |
| ReAct       | 0.375 |  0.254 | 0.303 |
| GraphRAG    | 0.583 |  0.503 | 0.426 |
| CyANCHOR    | 0.625 |  0.714 | 0.721 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.462 | 0.212 |   0.175 |  0.139 | 0.084 |
| FCAV        |  0.721 | 0.590 |   0.587 |  0.352 | 0.444 |
| ReAct       |  0.523 | 0.567 |   0.473 |  0.272 | 0.197 |
| GraphRAG    |  0.869 | 0.783 |   0.690 |  0.563 | 0.364 |
| CyANCHOR    |  0.907 | 0.913 |   0.901 |  0.731 | 0.600 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.103 |  0.103 | 0.305 |
| FCAV        | 0.428 |  0.499 | 0.511 |
| ReAct       | 0.420 |  0.291 | 0.442 |
| GraphRAG    | 0.628 |  0.574 | 0.616 |
| CyANCHOR    | 0.689 |  0.781 | 0.790 |
