# Report — company (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `company`, 308 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-06-24T02:00:24+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node_rel` · escalate `on`.

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
| No Val Link          | —         | 0.075 | 0.111 | 308 |   2 |
| FCAV                 | vector    | 0.081 | 0.121 | 308 |   6 |
| ReAct (Node + Rel)   | fuzzy     | 0.464 | 0.486 | 308 |   0 |
| GraphRAG             | norm-Lev  | 0.503 | 0.530 | 308 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.701 | 0.714 | 308 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.161 | 0.029 |   0.159 |  0.029 | 0.043 |
| FCAV                 |  0.129 | 0.029 |   0.159 |  0.088 | 0.029 |
| ReAct (Node + Rel)   |  0.677 | 0.614 |   0.594 |  0.279 | 0.271 |
| GraphRAG             |  0.806 | 0.771 |   0.609 |  0.176 | 0.314 |
| CyANCHOR (fuzzy+lev) |  0.871 | 0.871 |   0.870 |  0.426 | 0.557 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.040 | 0.168 |
| FCAV                 | 0.000 |  0.052 | 0.168 |
| ReAct (Node + Rel)   | 0.436 |  0.425 | 0.547 |
| GraphRAG             | 0.462 |  0.506 | 0.516 |
| CyANCHOR (fuzzy+lev) | 0.692 |  0.695 | 0.716 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.240 | 0.056 |   0.164 |  0.074 | 0.094 |
| FCAV                 |  0.179 | 0.042 |   0.135 |  0.187 | 0.094 |
| ReAct (Node + Rel)   |  0.638 | 0.676 |   0.575 |  0.323 | 0.299 |
| GraphRAG             |  0.834 | 0.795 |   0.576 |  0.258 | 0.347 |
| CyANCHOR (fuzzy+lev) |  0.932 | 0.888 |   0.768 |  0.501 | 0.598 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.074 |  0.068 | 0.205 |
| FCAV                 | 0.077 |  0.070 | 0.232 |
| ReAct (Node + Rel)   | 0.436 |  0.440 | 0.590 |
| GraphRAG             | 0.479 |  0.535 | 0.540 |
| CyANCHOR (fuzzy+lev) | 0.646 |  0.713 | 0.745 |
