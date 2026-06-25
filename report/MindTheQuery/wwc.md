# Report — wwc (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** MindTheQuery `wwc`, 275 entity-perturbed test questions
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
| No Val Link          | —         | 0.155 | 0.383 | 245 |  30 |
| FCAV                 | vector    | 0.157 | 0.373 | 249 |  26 |
| ReAct (Node + Rel)   | fuzzy     | 0.468 | 0.667 | 263 |  12 |
| GraphRAG             | norm-Lev  | 0.532 | 0.731 | 263 |  12 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.532 | 0.759 | 263 |  12 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.077 | 0.049 |   0.101 |  0.571 | 0.385 |
| FCAV                 |  0.077 | 0.048 |   0.103 |  0.571 | 0.382 |
| ReAct (Node + Rel)   |  0.346 | 0.466 |   0.506 |  0.571 | 0.456 |
| GraphRAG             |  0.462 | 0.489 |   0.565 |  1.000 | 0.526 |
| CyANCHOR (fuzzy+lev) |  0.462 | 0.511 |   0.553 |  1.000 | 0.509 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.176 |  0.171 | 0.083 |
| FCAV                 | 0.176 |  0.176 | 0.080 |
| ReAct (Node + Rel)   | 0.520 |  0.511 | 0.298 |
| GraphRAG             | 0.613 |  0.565 | 0.351 |
| CyANCHOR (fuzzy+lev) | 0.627 |  0.588 | 0.281 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.117 | 0.052 |   0.779 |  0.571 | 0.404 |
| FCAV                 |  0.117 | 0.036 |   0.777 |  0.571 | 0.403 |
| ReAct (Node + Rel)   |  0.680 | 0.717 |   0.729 |  0.574 | 0.500 |
| GraphRAG             |  0.812 | 0.724 |   0.779 |  1.000 | 0.601 |
| CyANCHOR (fuzzy+lev) |  0.743 | 0.792 |   0.822 |  0.992 | 0.591 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.375 |  0.426 | 0.284 |
| FCAV                 | 0.378 |  0.414 | 0.260 |
| ReAct (Node + Rel)   | 0.743 |  0.692 | 0.508 |
| GraphRAG             | 0.839 |  0.762 | 0.519 |
| CyANCHOR (fuzzy+lev) | 0.847 |  0.786 | 0.578 |
