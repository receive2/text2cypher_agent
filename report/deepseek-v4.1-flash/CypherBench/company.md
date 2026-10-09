# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `company`, 303 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T03:48:39-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.106 | 0.116 | 303 |   3 |        0 |
| FCAV        | vector    | 0.370 | 0.419 | 303 |   3 |        0 |
| ReAct       | fuzzy     | 0.409 | 0.431 | 303 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.512 | 0.565 | 303 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.710 | 0.756 | 303 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.290 | 0.140 |   0.115 |  0.062 | 0.057 |
| FCAV        |  0.710 | 0.349 |   0.426 |  0.175 | 0.398 |
| ReAct       |  0.548 | 0.674 |   0.443 |  0.188 | 0.409 |
| GraphRAG    |  0.774 | 0.651 |   0.574 |  0.375 | 0.432 |
| CyANCHOR    |  0.806 | 0.767 |   0.885 |  0.575 | 0.648 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.079 |  0.047 | 0.221 |
| FCAV        | 0.500 |  0.300 | 0.442 |
| ReAct       | 0.447 |  0.359 | 0.484 |
| GraphRAG    | 0.658 |  0.500 | 0.474 |
| CyANCHOR    | 0.789 |  0.671 | 0.747 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.339 | 0.110 |   0.109 |  0.086 | 0.073 |
| FCAV        |  0.849 | 0.334 |   0.420 |  0.269 | 0.444 |
| ReAct       |  0.729 | 0.646 |   0.426 |  0.225 | 0.411 |
| GraphRAG    |  0.930 | 0.673 |   0.585 |  0.429 | 0.493 |
| CyANCHOR    |  0.952 | 0.810 |   0.897 |  0.611 | 0.695 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.079 |  0.064 | 0.225 |
| FCAV        | 0.541 |  0.371 | 0.456 |
| ReAct       | 0.464 |  0.376 | 0.516 |
| GraphRAG    | 0.658 |  0.580 | 0.501 |
| CyANCHOR    | 0.832 |  0.718 | 0.793 |
