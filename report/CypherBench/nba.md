# Report — nba (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `nba`, 258 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-06-24T05:01:33+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
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
| No Val Link          | —         | 0.074 | 0.109 | 258 |   1 |
| FCAV                 | vector    | 0.078 | 0.125 | 258 |   2 |
| ReAct (Node + Rel)   | fuzzy     | 0.337 | 0.368 | 258 |   0 |
| GraphRAG             | norm-Lev  | 0.682 | 0.759 | 258 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.806 | 0.876 | 258 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.269 | 0.051 |   0.053 |  0.070 | 0.034 |
| FCAV                 |  0.308 | 0.051 |   0.053 |  0.053 | 0.051 |
| ReAct (Node + Rel)   |  0.577 | 0.458 |   0.439 |  0.140 | 0.203 |
| GraphRAG             |  0.769 | 0.780 |   0.754 |  0.667 | 0.492 |
| CyANCHOR (fuzzy+lev) |  0.885 | 0.898 |   0.860 |  0.702 | 0.729 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.075 |  0.057 | 0.104 |
| FCAV                 | 0.100 |  0.057 | 0.104 |
| ReAct (Node + Rel)   | 0.300 |  0.333 | 0.364 |
| GraphRAG             | 0.800 |  0.723 | 0.545 |
| CyANCHOR (fuzzy+lev) | 0.775 |  0.837 | 0.766 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.259 | 0.108 |   0.062 |  0.146 | 0.055 |
| FCAV                 |  0.340 | 0.114 |   0.067 |  0.132 | 0.092 |
| ReAct (Node + Rel)   |  0.597 | 0.523 |   0.443 |  0.212 | 0.188 |
| GraphRAG             |  0.797 | 0.872 |   0.831 |  0.769 | 0.549 |
| CyANCHOR (fuzzy+lev) |  0.906 | 0.993 |   0.932 |  0.849 | 0.717 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.100 |  0.077 | 0.173 |
| FCAV                 | 0.125 |  0.084 | 0.200 |
| ReAct (Node + Rel)   | 0.313 |  0.346 | 0.436 |
| GraphRAG             | 0.802 |  0.791 | 0.677 |
| CyANCHOR (fuzzy+lev) | 0.778 |  0.907 | 0.870 |
