# Report — er (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `er`, 202 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-06-24T06:48:54+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
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
| No Val Link          | —         | 0.307 | 0.252 | 202 |  11 |
| FCAV                 | vector    | 0.312 | 0.252 | 202 |  10 |
| ReAct (Node + Rel)   | fuzzy     | 0.530 | 0.539 | 202 |   3 |
| GraphRAG             | norm-Lev  | 0.688 | 0.779 | 202 |   4 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.693 | 0.779 | 202 |   3 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.524 | 0.329 |   0.500 |  0.116 |
| FCAV                 |  0.524 | 0.329 |   0.528 |  0.116 |
| ReAct (Node + Rel)   |  0.571 | 0.803 |   0.722 |  0.116 |
| GraphRAG             |  0.571 | 0.816 |   0.694 |  0.580 |
| CyANCHOR (fuzzy+lev) |  0.571 | 0.829 |   0.778 |  0.536 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.667 |  0.333 | 0.162 |
| FCAV                 | 0.667 |  0.333 | 0.189 |
| ReAct (Node + Rel)   | 0.667 |  0.562 | 0.378 |
| GraphRAG             | 1.000 |  0.722 | 0.514 |
| CyANCHOR (fuzzy+lev) | 0.667 |  0.716 | 0.595 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.476 | 0.237 |   0.444 |  0.101 |
| FCAV                 |  0.476 | 0.237 |   0.472 |  0.087 |
| ReAct (Node + Rel)   |  0.703 | 0.820 |   0.719 |  0.087 |
| GraphRAG             |  0.702 | 0.818 |   0.644 |  0.831 |
| CyANCHOR (fuzzy+lev) |  0.723 | 0.866 |   0.726 |  0.729 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.296 | 0.081 |
| FCAV                 | 0.000 |  0.290 | 0.108 |
| ReAct (Node + Rel)   | 0.000 |  0.581 | 0.401 |
| GraphRAG             | 0.333 |  0.826 | 0.613 |
| CyANCHOR (fuzzy+lev) | 0.000 |  0.808 | 0.717 |
