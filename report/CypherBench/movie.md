# Report — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `movie`, 370 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-06-23T07:54:50+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
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
| No Val Link          | —         | 0.043 | 0.107 | 370 |   6 |
| FCAV                 | vector    | 0.251 | 0.366 | 370 |  11 |
| ReAct (Node + Rel)   | fuzzy     | 0.376 | 0.445 | 370 |   4 |
| GraphRAG             | norm-Lev  | 0.497 | 0.569 | 370 |   3 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.630 | 0.668 | 370 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.270 | 0.012 |   0.012 |  0.036 | 0.012 |
| FCAV                 |  0.541 | 0.321 |   0.293 |  0.084 | 0.179 |
| ReAct (Node + Rel)   |  0.568 | 0.476 |   0.439 |  0.349 | 0.155 |
| GraphRAG             |  0.838 | 0.762 |   0.537 |  0.301 | 0.238 |
| CyANCHOR (fuzzy+lev) |  0.838 | 0.798 |   0.793 |  0.398 | 0.440 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.020 |  0.046 | 0.048 |
| FCAV                 | 0.180 |  0.258 | 0.270 |
| ReAct (Node + Rel)   | 0.440 |  0.392 | 0.325 |
| GraphRAG             | 0.580 |  0.552 | 0.381 |
| CyANCHOR (fuzzy+lev) | 0.660 |  0.634 | 0.611 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.308 | 0.087 |   0.099 |  0.089 | 0.062 |
| FCAV                 |  0.657 | 0.446 |   0.476 |  0.161 | 0.254 |
| ReAct (Node + Rel)   |  0.620 | 0.504 |   0.567 |  0.414 | 0.219 |
| GraphRAG             |  0.849 | 0.848 |   0.604 |  0.404 | 0.297 |
| CyANCHOR (fuzzy+lev) |  0.839 | 0.847 |   0.835 |  0.429 | 0.485 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.043 |  0.046 | 0.225 |
| FCAV                 | 0.220 |  0.335 | 0.473 |
| ReAct (Node + Rel)   | 0.479 |  0.412 | 0.481 |
| GraphRAG             | 0.618 |  0.575 | 0.542 |
| CyANCHOR (fuzzy+lev) | 0.719 |  0.645 | 0.682 |
