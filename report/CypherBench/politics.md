# Report — politics (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-25.

**Setup.** CypherBench `politics`, 365 entity-perturbed test questions
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
| No Val Link          | —         | 0.105 | 0.127 | 352 |  13 |
| FCAV                 | vector    | 0.150 | 0.212 | 353 |  12 |
| ReAct (Node + Rel)   | fuzzy     | 0.370 | 0.423 | 365 |   0 |
| GraphRAG             | norm-Lev  | 0.548 | 0.616 | 365 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.710 | 0.748 | 359 |   6 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.139 | 0.138 |   0.086 |  0.038 | 0.143 |
| FCAV                 |  0.250 | 0.165 |   0.139 |  0.100 | 0.152 |
| ReAct (Node + Rel)   |  0.486 | 0.537 |   0.402 |  0.195 | 0.293 |
| GraphRAG             |  0.730 | 0.793 |   0.537 |  0.317 | 0.463 |
| CyANCHOR (fuzzy+lev) |  0.944 | 0.877 |   0.753 |  0.506 | 0.598 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.086 |  0.049 | 0.205 |
| FCAV                 | 0.153 |  0.098 | 0.234 |
| ReAct (Node + Rel)   | 0.373 |  0.344 | 0.412 |
| GraphRAG             | 0.593 |  0.557 | 0.509 |
| CyANCHOR (fuzzy+lev) | 0.793 |  0.660 | 0.755 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.203 | 0.138 |   0.111 |  0.067 | 0.159 |
| FCAV                 |  0.362 | 0.223 |   0.174 |  0.211 | 0.171 |
| ReAct (Node + Rel)   |  0.497 | 0.589 |   0.477 |  0.277 | 0.317 |
| GraphRAG             |  0.761 | 0.836 |   0.570 |  0.486 | 0.505 |
| CyANCHOR (fuzzy+lev) |  0.883 | 0.850 |   0.813 |  0.587 | 0.677 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.074 |  0.065 | 0.256 |
| FCAV                 | 0.160 |  0.158 | 0.329 |
| ReAct (Node + Rel)   | 0.436 |  0.395 | 0.465 |
| GraphRAG             | 0.645 |  0.621 | 0.591 |
| CyANCHOR (fuzzy+lev) | 0.791 |  0.713 | 0.785 |
