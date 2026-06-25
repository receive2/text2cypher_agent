# Report — covid (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** MindTheQuery `covid`, 342 entity-perturbed test questions
(strategies: casing · typo · partial · alias). LLMs: gpt-4.1 for grounding and Cypher generation.

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
| No Val Link          | —         | 0.053 | 0.137 | 150 | 192 |
| FCAV                 | vector    | 0.049 | 0.181 | 143 | 199 |
| ReAct (Node + Rel)   | fuzzy     | 0.198 | 0.341 | 283 |  59 |
| GraphRAG             | norm-Lev  | 0.456 | 0.556 | 283 |  59 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.456 | 0.239 | 283 |  59 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | alias |
| -------------------- | -----: | ----: | ------: | ----: |
| No Val Link          |  0.056 | 0.032 |   0.097 | 0.125 |
| FCAV                 |  0.053 | 0.034 |   0.074 | 0.125 |
| ReAct (Node + Rel)   |  0.242 | 0.205 |   0.167 | 0.118 |
| GraphRAG             |  0.333 | 0.465 |   0.625 | 0.118 |
| CyANCHOR (fuzzy+lev) |  0.485 | 0.459 |   0.479 | 0.294 |

## By query-difficulty — EA

| method               | medium |  hard |
| -------------------- | -----: | ----: |
| No Val Link          |  0.071 | 0.037 |
| FCAV                 |  0.071 | 0.027 |
| ReAct (Node + Rel)   |  0.178 | 0.210 |
| GraphRAG             |  0.514 | 0.420 |
| CyANCHOR (fuzzy+lev) |  0.467 | 0.449 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | alias |
| -------------------- | -----: | ----: | ------: | ----: |
| No Val Link          |  0.178 | 0.112 |   0.139 | 0.326 |
| FCAV                 |  0.192 | 0.127 |   0.273 | 0.451 |
| ReAct (Node + Rel)   |  0.517 | 0.311 |   0.376 | 0.218 |
| GraphRAG             |  0.574 | 0.518 |   0.742 | 0.404 |
| CyANCHOR (fuzzy+lev) |  0.251 | 0.230 |   0.278 | 0.208 |

## By query-difficulty — PSJS

| method               | medium |  hard |
| -------------------- | -----: | ----: |
| No Val Link          |  0.137 | 0.136 |
| FCAV                 |  0.181 | 0.182 |
| ReAct (Node + Rel)   |  0.396 | 0.307 |
| GraphRAG             |  0.755 | 0.434 |
| CyANCHOR (fuzzy+lev) |  0.280 | 0.214 |
