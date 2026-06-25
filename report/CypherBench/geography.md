# Report — geography (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** CypherBench `geography`, 339 entity-perturbed test questions
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
| No Val Link          | —         | 0.075 | 0.107 | 335 |   4 |
| FCAV                 | vector    | 0.189 | 0.287 | 328 |  11 |
| ReAct (Node + Rel)   | fuzzy     | 0.392 | 0.433 | 339 |   0 |
| GraphRAG             | norm-Lev  | 0.496 | 0.544 | 339 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.722 | 0.773 | 334 |   5 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.147 | 0.052 |   0.128 |  0.000 | 0.079 |
| FCAV                 |  0.469 | 0.197 |   0.244 |  0.059 | 0.122 |
| ReAct (Node + Rel)   |  0.618 | 0.538 |   0.385 |  0.338 | 0.205 |
| GraphRAG             |  0.647 | 0.692 |   0.462 |  0.366 | 0.385 |
| CyANCHOR (fuzzy+lev) |  0.912 | 0.870 |   0.671 |  0.757 | 0.506 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.055 |  0.035 | 0.147 |
| FCAV                 | 0.255 |  0.153 | 0.214 |
| ReAct (Node + Rel)   | 0.291 |  0.402 | 0.427 |
| GraphRAG             | 0.491 |  0.477 | 0.527 |
| CyANCHOR (fuzzy+lev) | 0.709 |  0.725 | 0.722 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.223 | 0.084 |   0.123 |  0.082 | 0.083 |
| FCAV                 |  0.557 | 0.291 |   0.347 |  0.114 | 0.261 |
| ReAct (Node + Rel)   |  0.647 | 0.580 |   0.477 |  0.395 | 0.181 |
| GraphRAG             |  0.694 | 0.724 |   0.502 |  0.467 | 0.412 |
| CyANCHOR (fuzzy+lev) |  0.930 | 0.890 |   0.762 |  0.816 | 0.558 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.055 |  0.077 | 0.180 |
| FCAV                 | 0.289 |  0.281 | 0.296 |
| ReAct (Node + Rel)   | 0.330 |  0.413 | 0.515 |
| GraphRAG             | 0.512 |  0.520 | 0.598 |
| CyANCHOR (fuzzy+lev) | 0.737 |  0.772 | 0.792 |
