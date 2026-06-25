# Report — CypherBench (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-22.

**Setup.** CypherBench `all graphs pooled`, 2136 entity-perturbed test questions
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
| No Val Link          | —         | 0.076 | 0.111 | 2105 |  31 |
| FCAV                 | vector    | 0.171 | 0.236 | 2087 |  49 |
| ReAct (Node + Rel)   | fuzzy     | 0.382 | 0.424 | 2132 |   4 |
| GraphRAG             | norm-Lev  | 0.526 | 0.578 | 2133 |   3 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.697 | 0.741 | 2108 |  28 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.174 | 0.060 |   0.085 |  0.042 | 0.071 |
| FCAV                 |  0.336 | 0.183 |   0.181 |  0.106 | 0.129 |
| ReAct (Node + Rel)   |  0.561 | 0.502 |   0.452 |  0.258 | 0.219 |
| GraphRAG             |  0.743 | 0.753 |   0.523 |  0.359 | 0.347 |
| CyANCHOR (fuzzy+lev) |  0.859 | 0.830 |   0.787 |  0.552 | 0.524 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.046 |  0.042 | 0.151 |
| FCAV                 | 0.169 |  0.133 | 0.236 |
| ReAct (Node + Rel)   | 0.361 |  0.376 | 0.404 |
| GraphRAG             | 0.570 |  0.531 | 0.495 |
| CyANCHOR (fuzzy+lev) | 0.718 |  0.686 | 0.705 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.221 | 0.098 |   0.110 |  0.096 | 0.090 |
| FCAV                 |  0.408 | 0.250 |   0.240 |  0.192 | 0.179 |
| ReAct (Node + Rel)   |  0.573 | 0.550 |   0.506 |  0.318 | 0.238 |
| GraphRAG             |  0.770 | 0.812 |   0.564 |  0.462 | 0.371 |
| CyANCHOR (fuzzy+lev) |  0.875 | 0.873 |   0.824 |  0.637 | 0.558 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.071 |  0.060 | 0.220 |
| FCAV                 | 0.204 |  0.187 | 0.338 |
| ReAct (Node + Rel)   | 0.391 |  0.397 | 0.487 |
| GraphRAG             | 0.591 |  0.572 | 0.581 |
| CyANCHOR (fuzzy+lev) | 0.732 |  0.732 | 0.762 |
