# Report — er (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** MindTheQuery `er`, 202 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev). LLMs: gpt-4.1 for grounding and Cypher generation.

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
| No Val Link          | —         | 0.325 | 0.267 | 191 |  11 |
| FCAV                 | vector    | 0.328 | 0.266 | 192 |  10 |
| ReAct (Node + Rel)   | fuzzy     | 0.538 | 0.548 | 199 |   3 |
| GraphRAG             | norm-Lev  | 0.702 | 0.791 | 198 |   4 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.704 | 0.791 | 199 |   3 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.579 | 0.338 |   0.514 |  0.127 |
| FCAV                 |  0.579 | 0.338 |   0.543 |  0.125 |
| ReAct (Node + Rel)   |  0.600 | 0.813 |   0.722 |  0.118 |
| GraphRAG             |  0.600 | 0.838 |   0.694 |  0.588 |
| CyANCHOR (fuzzy+lev) |  0.600 | 0.840 |   0.778 |  0.544 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.667 |  0.344 | 0.194 |
| FCAV                 | 0.667 |  0.348 | 0.206 |
| ReAct (Node + Rel)   | 0.667 |  0.569 | 0.389 |
| GraphRAG             | 1.000 |  0.731 | 0.543 |
| CyANCHOR (fuzzy+lev) | 0.667 |  0.725 | 0.611 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.526 | 0.243 |   0.457 |  0.111 |
| FCAV                 |  0.526 | 0.243 |   0.486 |  0.094 |
| ReAct (Node + Rel)   |  0.738 | 0.831 |   0.719 |  0.088 |
| GraphRAG             |  0.737 | 0.829 |   0.644 |  0.843 |
| CyANCHOR (fuzzy+lev) |  0.759 | 0.877 |   0.726 |  0.739 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.306 | 0.097 |
| FCAV                 | 0.000 |  0.303 | 0.118 |
| ReAct (Node + Rel)   | 0.000 |  0.588 | 0.413 |
| GraphRAG             | 0.333 |  0.836 | 0.630 |
| CyANCHOR (fuzzy+lev) | 0.000 |  0.818 | 0.737 |
