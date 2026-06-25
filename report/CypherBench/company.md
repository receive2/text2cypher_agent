# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** CypherBench `company`, 308 entity-perturbed test questions
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
| No Val Link          | —         | 0.075 | 0.112 | 306 |   2 |
| FCAV                 | vector    | 0.083 | 0.123 | 302 |   6 |
| ReAct (Node + Rel)   | fuzzy     | 0.464 | 0.486 | 308 |   0 |
| GraphRAG             | norm-Lev  | 0.503 | 0.530 | 308 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.699 | 0.712 | 302 |   6 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.161 | 0.029 |   0.159 |  0.029 | 0.043 |
| FCAV                 |  0.129 | 0.030 |   0.159 |  0.090 | 0.029 |
| ReAct (Node + Rel)   |  0.677 | 0.614 |   0.594 |  0.279 | 0.271 |
| GraphRAG             |  0.806 | 0.771 |   0.609 |  0.176 | 0.314 |
| CyANCHOR (fuzzy+lev) |  0.871 | 0.862 |   0.870 |  0.426 | 0.565 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.041 | 0.168 |
| FCAV                 | 0.000 |  0.053 | 0.170 |
| ReAct (Node + Rel)   | 0.436 |  0.425 | 0.547 |
| GraphRAG             | 0.462 |  0.506 | 0.516 |
| CyANCHOR (fuzzy+lev) | 0.684 |  0.696 | 0.710 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.240 | 0.057 |   0.164 |  0.074 | 0.095 |
| FCAV                 |  0.179 | 0.044 |   0.135 |  0.190 | 0.097 |
| ReAct (Node + Rel)   |  0.638 | 0.676 |   0.575 |  0.323 | 0.299 |
| GraphRAG             |  0.834 | 0.795 |   0.576 |  0.258 | 0.347 |
| CyANCHOR (fuzzy+lev) |  0.932 | 0.879 |   0.768 |  0.501 | 0.607 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.074 |  0.069 | 0.205 |
| FCAV                 | 0.077 |  0.072 | 0.234 |
| ReAct (Node + Rel)   | 0.436 |  0.440 | 0.590 |
| GraphRAG             | 0.479 |  0.535 | 0.540 |
| CyANCHOR (fuzzy+lev) | 0.637 |  0.714 | 0.739 |
