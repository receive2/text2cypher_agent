# Report — fictional_character (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** CypherBench `fictional_character`, 326 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias). LLMs: gpt-4.1 for grounding and Cypher generation.

**Methods.**
- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).
- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve
  candidate values from a self-built value index, an LLM generates the entity JSON.
- **ReAct (Node + Rel)** — ReAct NER agent (fuzzy/BM25 retrieval) over node + relation tools.
- **GraphRAG** — Multi-Agent GraphRAG baseline: generate→execute→evaluate→repair; on
  error/empty it extracts the query's labels/values/rels, validates them, and proposes
  normalized-Levenshtein replacements, iterating the generator.
- **CyANCHOR (Node + Rel)** — our plan-and-execute grounder: decompose the question into
  entity mentions, route each to a database field, retrieve candidates with an LLM-judge
  corrective loop, then the Cypher LLM value-links. Retrieval is the union of independently
  toggleable arms — **fuzzy** (BM25) · **lev** (APOC normalized Levenshtein) · **vector**
  (in-graph embeddings).

---

## Overall

| method               | retrieval |    EA |  PSJS |   n | err |
| -------------------- | --------- | ----: | ----: | --: | --: |
| No Val Link          | —         | 0.071 | 0.097 | 323 |   3 |
| FCAV                 | vector    | 0.071 | 0.097 | 322 |   4 |
| ReAct (Node + Rel)   | fuzzy     | 0.334 | 0.378 | 326 |   0 |
| GraphRAG             | norm-Lev  | 0.417 | 0.455 | 326 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.592 | 0.655 | 321 |   5 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.061 | 0.083 |   0.043 |  0.000 | 0.098 |
| FCAV                 |  0.091 | 0.083 |   0.033 |  0.000 | 0.098 |
| ReAct (Node + Rel)   |  0.424 | 0.375 |   0.484 |  0.000 | 0.147 |
| GraphRAG             |  0.606 | 0.667 |   0.344 |  0.000 | 0.211 |
| CyANCHOR (fuzzy+lev) |  0.667 | 0.681 |   0.791 |  0.125 | 0.326 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.019 |  0.022 | 0.202 |
| FCAV                 | 0.037 |  0.022 | 0.195 |
| ReAct (Node + Rel)   | 0.241 |  0.352 | 0.356 |
| GraphRAG             | 0.463 |  0.379 | 0.467 |
| CyANCHOR (fuzzy+lev) | 0.574 |  0.582 | 0.622 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.069 | 0.123 |   0.096 |  0.000 | 0.093 |
| FCAV                 |  0.097 | 0.123 |   0.087 |  0.000 | 0.089 |
| ReAct (Node + Rel)   |  0.427 | 0.452 |   0.534 |  0.000 | 0.169 |
| GraphRAG             |  0.629 | 0.751 |   0.402 |  0.000 | 0.190 |
| CyANCHOR (fuzzy+lev) |  0.713 | 0.788 |   0.826 |  0.684 | 0.336 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.061 |  0.026 | 0.265 |
| FCAV                 | 0.079 |  0.022 | 0.263 |
| ReAct (Node + Rel)   | 0.282 |  0.376 | 0.440 |
| GraphRAG             | 0.489 |  0.403 | 0.539 |
| CyANCHOR (fuzzy+lev) | 0.605 |  0.647 | 0.699 |
