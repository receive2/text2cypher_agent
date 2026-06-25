# Report — ZOGRASCOPE (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-22.

**Setup.** ZOGRASCOPE `all graphs pooled`, 1441 entity-perturbed test questions
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

| method               | retrieval |    EA |  PSJS |    n | err |
| -------------------- | --------- | ----: | ----: | ---: | --: |
| No Val Link          | —         | 0.050 | 0.044 | 1429 |  12 |
| FCAV                 | vector    | 0.087 | 0.126 | 1421 |  20 |
| ReAct (Node + Rel)   | fuzzy     | 0.176 | 0.231 | 1441 |   0 |
| GraphRAG             | norm-Lev  | 0.164 | 0.260 | 1441 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.291 | 0.362 | 1441 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.113 | 0.018 |   0.095 |  0.000 |
| FCAV                 |  0.155 | 0.083 |   0.082 |  0.024 |
| ReAct (Node + Rel)   |  0.188 | 0.130 |   0.275 |  0.081 |
| GraphRAG             |  0.188 | 0.100 |   0.270 |  0.163 |
| CyANCHOR (fuzzy+lev) |  0.347 | 0.238 |   0.379 |  0.244 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.033 |  0.053 | 0.040 |
| FCAV                 | 0.057 |  0.091 | 0.078 |
| ReAct (Node + Rel)   | 0.066 |  0.188 | 0.169 |
| GraphRAG             | 0.099 |  0.151 | 0.234 |
| CyANCHOR (fuzzy+lev) | 0.088 |  0.285 | 0.381 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.122 | 0.020 |   0.070 |  0.003 |
| FCAV                 |  0.264 | 0.145 |   0.066 |  0.019 |
| ReAct (Node + Rel)   |  0.263 | 0.188 |   0.336 |  0.042 |
| GraphRAG             |  0.319 | 0.219 |   0.323 |  0.220 |
| CyANCHOR (fuzzy+lev) |  0.430 | 0.342 |   0.409 |  0.189 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.044 |  0.036 | 0.076 |
| FCAV                 | 0.178 |  0.107 | 0.182 |
| ReAct (Node + Rel)   | 0.393 |  0.224 | 0.208 |
| GraphRAG             | 0.449 |  0.220 | 0.355 |
| CyANCHOR (fuzzy+lev) | 0.381 |  0.322 | 0.509 |
