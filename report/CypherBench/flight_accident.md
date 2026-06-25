# Report — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** CypherBench `flight_accident`, 170 entity-perturbed test questions
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
| No Val Link          | —         | 0.107 | 0.117 | 168 |   2 |
| FCAV                 | vector    | 0.479 | 0.521 | 167 |   3 |
| ReAct (Node + Rel)   | fuzzy     | 0.406 | 0.410 | 170 |   0 |
| GraphRAG             | norm-Lev  | 0.612 | 0.621 | 170 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.800 | 0.845 | 170 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.176 | 0.027 |   0.158 |  0.132 | 0.079 |
| FCAV                 |  0.706 | 0.605 |   0.486 |  0.378 | 0.342 |
| ReAct (Node + Rel)   |  0.588 | 0.579 |   0.395 |  0.237 | 0.333 |
| GraphRAG             |  0.824 | 0.895 |   0.526 |  0.500 | 0.436 |
| CyANCHOR (fuzzy+lev) |  0.941 | 0.947 |   0.816 |  0.711 | 0.667 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.058 |  0.056 | 0.250 |
| FCAV                 | 0.404 |  0.444 | 0.628 |
| ReAct (Node + Rel)   | 0.462 |  0.370 | 0.400 |
| GraphRAG             | 0.635 |  0.589 | 0.622 |
| CyANCHOR (fuzzy+lev) | 0.827 |  0.753 | 0.844 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.254 | 0.052 |   0.108 |  0.180 | 0.066 |
| FCAV                 |  0.783 | 0.669 |   0.460 |  0.485 | 0.348 |
| ReAct (Node + Rel)   |  0.588 | 0.546 |   0.388 |  0.269 | 0.359 |
| GraphRAG             |  0.842 | 0.927 |   0.566 |  0.522 | 0.375 |
| CyANCHOR (fuzzy+lev) |  1.000 | 0.969 |   0.874 |  0.786 | 0.684 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.101 |  0.063 | 0.224 |
| FCAV                 | 0.432 |  0.502 | 0.658 |
| ReAct (Node + Rel)   | 0.460 |  0.356 | 0.441 |
| GraphRAG             | 0.615 |  0.622 | 0.624 |
| CyANCHOR (fuzzy+lev) | 0.840 |  0.840 | 0.858 |
