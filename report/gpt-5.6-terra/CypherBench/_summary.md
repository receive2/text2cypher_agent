# Report — CypherBench (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `all graphs pooled`, 2090 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-03. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.

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
| No Val Link | —         | 0.112 | 0.141 | 2090 |  35 |        0 |
| FCAV        | vector    | 0.507 | 0.577 | 2090 |  51 |        0 |
| ReAct       | fuzzy     | 0.366 | 0.414 | 2090 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.485 | 0.570 | 2090 |   2 |        0 |
| CyANCHOR    | fuzzy+lev | 0.706 | 0.788 | 2090 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.339 | 0.094 |   0.101 |  0.113 | 0.057 |
| FCAV        |  0.688 | 0.513 |   0.540 |  0.371 | 0.561 |
| ReAct       |  0.625 | 0.525 |   0.506 |  0.225 | 0.272 |
| GraphRAG    |  0.740 | 0.694 |   0.566 |  0.381 | 0.370 |
| CyANCHOR    |  0.880 | 0.864 |   0.811 |  0.571 | 0.655 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.104 |  0.066 | 0.197 |
| FCAV        | 0.674 |  0.445 | 0.525 |
| ReAct       | 0.448 |  0.320 | 0.402 |
| GraphRAG    | 0.605 |  0.469 | 0.449 |
| CyANCHOR    | 0.786 |  0.683 | 0.705 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.376 | 0.104 |   0.133 |  0.156 | 0.077 |
| FCAV        |  0.763 | 0.550 |   0.585 |  0.458 | 0.644 |
| ReAct       |  0.693 | 0.576 |   0.541 |  0.274 | 0.320 |
| GraphRAG    |  0.828 | 0.766 |   0.612 |  0.496 | 0.455 |
| CyANCHOR    |  0.934 | 0.914 |   0.849 |  0.684 | 0.755 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.123 |  0.081 | 0.254 |
| FCAV        | 0.682 |  0.527 | 0.609 |
| ReAct       | 0.462 |  0.361 | 0.480 |
| GraphRAG    | 0.622 |  0.563 | 0.555 |
| CyANCHOR    | 0.817 |  0.774 | 0.798 |
