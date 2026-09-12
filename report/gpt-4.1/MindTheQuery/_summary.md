# Report — MindTheQuery (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `all graphs pooled`, 1298 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-06-22. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.

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
| No Val Link          | —         | 0.250 | 0.294 | 1298 | 247 |
| FCAV                 | vector    | 0.252 | 0.299 | 1298 | 246 |
| ReAct (Node + Rel)   | fuzzy     | 0.462 | 0.545 | 1298 |  79 |
| GraphRAG             | norm-Lev  | 0.564 | 0.652 | 1298 |  80 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.569 | 0.597 | 1298 |  79 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.273 | 0.159 |   0.245 |  0.312 | 0.446 |
| FCAV                 |  0.280 | 0.163 |   0.245 |  0.312 | 0.446 |
| ReAct (Node + Rel)   |  0.485 | 0.444 |   0.523 |  0.336 | 0.477 |
| GraphRAG             |  0.545 | 0.554 |   0.604 |  0.616 | 0.503 |
| CyANCHOR (fuzzy+lev) |  0.591 | 0.560 |   0.582 |  0.600 | 0.538 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.198 |  0.308 | 0.147 |
| FCAV                 | 0.198 |  0.313 | 0.145 |
| ReAct (Node + Rel)   | 0.531 |  0.531 | 0.316 |
| GraphRAG             | 0.630 |  0.620 | 0.442 |
| CyANCHOR (fuzzy+lev) | 0.630 |  0.619 | 0.461 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.290 | 0.165 |   0.399 |  0.304 | 0.463 |
| FCAV                 |  0.301 | 0.169 |   0.406 |  0.296 | 0.474 |
| ReAct (Node + Rel)   |  0.645 | 0.540 |   0.620 |  0.320 | 0.509 |
| GraphRAG             |  0.706 | 0.630 |   0.681 |  0.762 | 0.555 |
| CyANCHOR (fuzzy+lev) |  0.615 | 0.547 |   0.645 |  0.711 | 0.565 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.355 |  0.347 | 0.180 |
| FCAV                 | 0.358 |  0.354 | 0.182 |
| ReAct (Node + Rel)   | 0.707 |  0.605 | 0.396 |
| GraphRAG             | 0.816 |  0.724 | 0.479 |
| CyANCHOR (fuzzy+lev) | 0.812 |  0.666 | 0.420 |
