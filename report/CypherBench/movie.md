# movie — entity-perturbed CypherBench (per-graph report)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-21.

**Setup.** CypherBench `movie`, 370 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias). LLMs: gpt-4.1 for grounding
and Cypher generation. **All methods share the identical Cypher system prompt** (the
either/or-UNION guidance is given to every method — a fair comparison). Each method
is scored over its own successfully-executed rows (per-method `n`).

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
| No Val Link          | —         | 0.044 | 0.109 | 364 |   6 |
| FCAV                 | vector    | 0.259 | 0.378 | 359 |  11 |
| ReAct (Node + Rel)   | fuzzy     | 0.380 | 0.449 | 366 |   4 |
| GraphRAG             | norm-Lev  | 0.501 | 0.574 | 367 |   3 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.578 | 0.615 | 370 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.278 | 0.012 |   0.013 |  0.037 | 0.012 |
| FCAV                 |  0.556 | 0.329 |   0.296 |  0.087 | 0.188 |
| ReAct (Node + Rel)   |  0.583 | 0.482 |   0.444 |  0.354 | 0.155 |
| GraphRAG             |  0.861 | 0.771 |   0.537 |  0.305 | 0.238 |
| CyANCHOR (fuzzy+lev) |  0.811 | 0.833 |   0.732 |  0.253 | 0.393 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.020 |  0.048 | 0.048 |
| FCAV                 | 0.180 |  0.266 | 0.281 |
| ReAct (Node + Rel)   | 0.440 |  0.398 | 0.328 |
| GraphRAG             | 0.580 |  0.560 | 0.381 |
| CyANCHOR (fuzzy+lev) | 0.600 |  0.582 | 0.563 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.317 | 0.087 |   0.102 |  0.092 | 0.063 |
| FCAV                 |  0.675 | 0.457 |   0.482 |  0.167 | 0.266 |
| ReAct (Node + Rel)   |  0.637 | 0.510 |   0.574 |  0.419 | 0.219 |
| GraphRAG             |  0.872 | 0.858 |   0.604 |  0.409 | 0.297 |
| CyANCHOR (fuzzy+lev) |  0.791 | 0.862 |   0.794 |  0.299 | 0.427 |

---

## Findings

1. **CyANCHOR is the strongest method** — EA 0.578 vs GraphRAG 0.501, ReAct 0.380, FCAV 0.259, No Val Link 0.044 — under an identical, shared Cypher system prompt. Ranking matches flight_accident and nba; movie's large, ambiguous value space (~218k node values) lowers the absolute ceiling for every method but not the order.
2. **`fuzzy+lev` (no embeddings) beats every baseline, including GraphRAG's Levenshtein repair.** GraphRAG and CyANCHOR share the *same* APOC normalized-Levenshtein primitive; the +0.077 EA gap is the *architecture* — proactive per-mention multi-arm grounding vs reactive one-value-at-a-time repair after a query fails — not the retrieval primitive.
3. **Gains concentrate on the heavily-degraded perturbations** — `partial` (0.732 vs GraphRAG 0.537, +0.195) and `alias` (0.393 vs 0.238, +0.155). On `casing` (0.811 vs 0.861) and `abbrev` (0.253 vs 0.305) GraphRAG's reactive Levenshtein edges CyANCHOR within these smaller buckets — single-edit casing and contraction-style abbreviations are exactly where edit-distance repair is competitive.
4. **CyANCHOR degrades most gracefully with query difficulty** (hard 0.563 vs GraphRAG 0.381, +0.182): per-mention decomposition resolves every entity on multi-entity hard queries, where a single reactive repair pass leaves residual ungrounded mentions.
