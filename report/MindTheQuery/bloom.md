# Report — bloom (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** MindTheQuery `bloom`, 40 entity-perturbed test questions
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
| No Val Link          | —         | 0.282 | 0.384 |  39 |   1 |
| FCAV                 | vector    | 0.308 | 0.409 |  39 |   1 |
| ReAct (Node + Rel)   | fuzzy     | 0.525 | 0.500 |  40 |   0 |
| GraphRAG             | norm-Lev  | 0.525 | 0.649 |  40 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.550 | 0.620 |  40 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.500 | 0.263 |   0.364 |  0.000 |
| FCAV                 |  0.500 | 0.316 |   0.364 |  0.000 |
| ReAct (Node + Rel)   |  0.750 | 0.650 |   0.364 |  0.200 |
| GraphRAG             |  0.750 | 0.500 |   0.455 |  0.600 |
| CyANCHOR (fuzzy+lev) |  0.750 | 0.550 |   0.545 |  0.400 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 1.000 |  0.250 | 0.500 |
| FCAV                 | 1.000 |  0.278 | 0.500 |
| ReAct (Node + Rel)   | 1.000 |  0.514 | 0.500 |
| GraphRAG             | 1.000 |  0.514 | 0.500 |
| CyANCHOR (fuzzy+lev) | 1.000 |  0.541 | 0.500 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.500 | 0.524 |   0.273 |  0.000 |
| FCAV                 |  0.500 | 0.577 |   0.273 |  0.000 |
| ReAct (Node + Rel)   |  0.500 | 0.700 |   0.273 |  0.200 |
| GraphRAG             |  0.750 | 0.598 |   0.727 |  0.600 |
| CyANCHOR (fuzzy+lev) |  0.750 | 0.630 |   0.727 |  0.242 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 1.000 |  0.360 | 0.500 |
| FCAV                 | 1.000 |  0.388 | 0.500 |
| ReAct (Node + Rel)   | 1.000 |  0.486 | 0.500 |
| GraphRAG             | 1.000 |  0.648 | 0.500 |
| CyANCHOR (fuzzy+lev) | 1.000 |  0.616 | 0.500 |
