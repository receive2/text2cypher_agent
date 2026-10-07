# Report — CypherBench (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `all graphs pooled`, 2090 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.

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

| method      | retrieval |    EA |  PSJS |    n | err | gold err |
| ----------- | --------- | ----: | ----: | ---: | --: | -------: |
| No Val Link | —         | 0.087 | 0.115 | 2090 |  45 |        0 |
| FCAV        | vector    | 0.388 | 0.451 | 2090 |  36 |        0 |
| ReAct       | fuzzy     | 0.292 | 0.341 | 2090 |   4 |        0 |
| GraphRAG    | norm-Lev  | 0.455 | 0.516 | 2090 |   2 |        0 |
| CyANCHOR    | fuzzy+lev | 0.667 | 0.727 | 2090 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.271 | 0.072 |   0.075 |  0.081 | 0.049 |
| FCAV        |  0.573 | 0.370 |   0.388 |  0.316 | 0.410 |
| ReAct       |  0.500 | 0.374 |   0.393 |  0.175 | 0.246 |
| GraphRAG    |  0.693 | 0.679 |   0.509 |  0.374 | 0.334 |
| CyANCHOR    |  0.823 | 0.777 |   0.757 |  0.580 | 0.601 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.068 |  0.041 | 0.175 |
| FCAV        | 0.421 |  0.337 | 0.458 |
| ReAct       | 0.285 |  0.250 | 0.368 |
| GraphRAG    | 0.549 |  0.435 | 0.441 |
| CyANCHOR    | 0.733 |  0.634 | 0.688 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.293 | 0.088 |   0.101 |  0.130 | 0.066 |
| FCAV        |  0.603 | 0.398 |   0.426 |  0.398 | 0.494 |
| ReAct       |  0.533 | 0.434 |   0.431 |  0.240 | 0.288 |
| GraphRAG    |  0.745 | 0.690 |   0.548 |  0.472 | 0.396 |
| CyANCHOR    |  0.842 | 0.827 |   0.783 |  0.659 | 0.683 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.081 |  0.060 | 0.228 |
| FCAV        | 0.436 |  0.409 | 0.530 |
| ReAct       | 0.299 |  0.292 | 0.450 |
| GraphRAG    | 0.574 |  0.490 | 0.530 |
| CyANCHOR    | 0.760 |  0.700 | 0.757 |
