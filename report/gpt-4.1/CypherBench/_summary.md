# Report — CypherBench (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `all graphs pooled`, 2136 entity-perturbed test questions
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
| No Val Link          | —         | 0.075 | 0.109 | 2136 |  31 |
| FCAV                 | vector    | 0.167 | 0.230 | 2136 |  49 |
| ReAct (Node + Rel)   | fuzzy     | 0.382 | 0.423 | 2136 |   4 |
| GraphRAG             | norm-Lev  | 0.526 | 0.577 | 2136 |   3 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.697 | 0.742 | 2136 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.172 | 0.059 |   0.084 |  0.042 | 0.069 |
| FCAV                 |  0.330 | 0.179 |   0.178 |  0.103 | 0.124 |
| ReAct (Node + Rel)   |  0.558 | 0.501 |   0.451 |  0.257 | 0.219 |
| GraphRAG             |  0.740 | 0.751 |   0.523 |  0.358 | 0.347 |
| CyANCHOR (fuzzy+lev) |  0.860 | 0.830 |   0.786 |  0.554 | 0.523 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.046 |  0.042 | 0.149 |
| FCAV                 | 0.169 |  0.130 | 0.228 |
| ReAct (Node + Rel)   | 0.361 |  0.375 | 0.403 |
| GraphRAG             | 0.570 |  0.530 | 0.495 |
| CyANCHOR (fuzzy+lev) | 0.719 |  0.686 | 0.705 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.219 | 0.096 |   0.109 |  0.095 | 0.088 |
| FCAV                 |  0.400 | 0.245 |   0.237 |  0.187 | 0.173 |
| ReAct (Node + Rel)   |  0.571 | 0.549 |   0.505 |  0.317 | 0.238 |
| GraphRAG             |  0.766 | 0.810 |   0.564 |  0.460 | 0.371 |
| CyANCHOR (fuzzy+lev) |  0.876 | 0.872 |   0.823 |  0.640 | 0.558 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.071 |  0.058 | 0.218 |
| FCAV                 | 0.204 |  0.182 | 0.328 |
| ReAct (Node + Rel)   | 0.391 |  0.396 | 0.486 |
| GraphRAG             | 0.591 |  0.571 | 0.581 |
| CyANCHOR (fuzzy+lev) | 0.734 |  0.732 | 0.765 |
