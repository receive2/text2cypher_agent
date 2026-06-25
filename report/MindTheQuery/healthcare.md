# Report — healthcare (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** MindTheQuery `healthcare`, 439 entity-perturbed test questions
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
| No Val Link          | —         | 0.481 | 0.474 | 426 |  13 |
| FCAV                 | vector    | 0.480 | 0.473 | 429 |  10 |
| ReAct (Node + Rel)   | fuzzy     | 0.675 | 0.706 | 434 |   5 |
| GraphRAG             | norm-Lev  | 0.698 | 0.721 | 434 |   5 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.710 | 0.749 | 434 |   5 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.476 | 0.407 |   0.400 |  0.628 | 0.584 |
| FCAV                 |  0.488 | 0.412 |   0.397 |  0.628 | 0.575 |
| ReAct (Node + Rel)   |  0.744 | 0.681 |   0.759 |  0.674 | 0.560 |
| GraphRAG             |  0.791 | 0.767 |   0.750 |  0.628 | 0.569 |
| CyANCHOR (fuzzy+lev) |  0.814 | 0.767 |   0.724 |  0.674 | 0.612 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.482 | 0.490 |
| FCAV                 | 0.000 |  0.483 | 0.479 |
| ReAct (Node + Rel)   | 0.500 |  0.689 | 0.633 |
| GraphRAG             | 0.500 |  0.698 | 0.704 |
| CyANCHOR (fuzzy+lev) | 0.500 |  0.701 | 0.745 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.476 | 0.389 |   0.384 |  0.628 | 0.590 |
| FCAV                 |  0.488 | 0.395 |   0.372 |  0.628 | 0.590 |
| ReAct (Node + Rel)   |  0.781 | 0.737 |   0.787 |  0.674 | 0.577 |
| GraphRAG             |  0.822 | 0.825 |   0.748 |  0.649 | 0.578 |
| CyANCHOR (fuzzy+lev) |  0.822 | 0.824 |   0.784 |  0.707 | 0.629 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.475 | 0.478 |
| FCAV                 | 0.000 |  0.480 | 0.458 |
| ReAct (Node + Rel)   | 0.251 |  0.721 | 0.663 |
| GraphRAG             | 0.609 |  0.727 | 0.701 |
| CyANCHOR (fuzzy+lev) | 0.592 |  0.744 | 0.772 |
