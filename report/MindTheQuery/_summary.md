# Report — MindTheQuery (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-22.

**Setup.** MindTheQuery `all graphs pooled`, 1298 entity-perturbed test questions
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

| method               | retrieval |    EA |  PSJS |    n | err |
| -------------------- | --------- | ----: | ----: | ---: | --: |
| No Val Link          | —         | 0.308 | 0.364 | 1051 | 247 |
| FCAV                 | vector    | 0.311 | 0.369 | 1052 | 246 |
| ReAct (Node + Rel)   | fuzzy     | 0.492 | 0.580 | 1219 |  79 |
| GraphRAG             | norm-Lev  | 0.601 | 0.694 | 1218 |  80 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.606 | 0.635 | 1219 |  79 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.330 | 0.218 |   0.292 |  0.331 | 0.503 |
| FCAV                 |  0.333 | 0.224 |   0.296 |  0.328 | 0.494 |
| ReAct (Node + Rel)   |  0.508 | 0.479 |   0.571 |  0.341 | 0.489 |
| GraphRAG             |  0.571 | 0.600 |   0.659 |  0.626 | 0.516 |
| CyANCHOR (fuzzy+lev) |  0.619 | 0.605 |   0.635 |  0.610 | 0.553 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.200 |  0.346 | 0.237 |
| FCAV                 | 0.200 |  0.350 | 0.235 |
| ReAct (Node + Rel)   | 0.531 |  0.554 | 0.355 |
| GraphRAG             | 0.630 |  0.648 | 0.497 |
| CyANCHOR (fuzzy+lev) | 0.630 |  0.646 | 0.518 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.351 | 0.228 |   0.476 |  0.322 | 0.522 |
| FCAV                 |  0.358 | 0.233 |   0.491 |  0.311 | 0.525 |
| ReAct (Node + Rel)   |  0.675 | 0.584 |   0.676 |  0.325 | 0.522 |
| GraphRAG             |  0.739 | 0.681 |   0.743 |  0.775 | 0.569 |
| CyANCHOR (fuzzy+lev) |  0.644 | 0.591 |   0.704 |  0.722 | 0.580 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.359 |  0.391 | 0.290 |
| FCAV                 | 0.362 |  0.397 | 0.295 |
| ReAct (Node + Rel)   | 0.707 |  0.632 | 0.444 |
| GraphRAG             | 0.816 |  0.756 | 0.538 |
| CyANCHOR (fuzzy+lev) | 0.812 |  0.696 | 0.471 |
