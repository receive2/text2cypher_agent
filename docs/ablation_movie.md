# Ablation — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-21.

**Setup.** CypherBench `movie`, 200 entity-perturbed test questions
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
| No Val Link          | —         | 0.052 | 0.111 | 194 |   6 |
| FCAV                 | vector    | 0.276 | 0.375 | 196 |   4 |
| ReAct (Node + Rel)   | fuzzy     | 0.376 | 0.415 | 197 |   3 |
| GraphRAG             | norm-Lev  | 0.467 | 0.537 | 199 |   1 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.569 | 0.622 | 197 |   3 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.316 | 0.000 |   0.043 |  0.025 | 0.023 |
| FCAV                 |  0.667 | 0.326 |   0.304 |  0.095 | 0.205 |
| ReAct (Node + Rel)   |  0.737 | 0.478 |   0.422 |  0.341 | 0.109 |
| GraphRAG             |  0.895 | 0.761 |   0.478 |  0.262 | 0.174 |
| CyANCHOR (fuzzy+lev) |  0.947 | 0.733 |   0.756 |  0.286 | 0.326 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.060 | 0.058 |
| FCAV                 | 0.240 |  0.272 | 0.294 |
| ReAct (Node + Rel)   | 0.440 |  0.379 | 0.348 |
| GraphRAG             | 0.520 |  0.538 | 0.343 |
| CyANCHOR (fuzzy+lev) | 0.600 |  0.573 | 0.551 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.360 | 0.068 |   0.139 |  0.071 | 0.055 |
| FCAV                 |  0.743 | 0.413 |   0.478 |  0.159 | 0.285 |
| ReAct (Node + Rel)   |  0.740 | 0.474 |   0.508 |  0.395 | 0.146 |
| GraphRAG             |  0.886 | 0.883 |   0.549 |  0.316 | 0.234 |
| CyANCHOR (fuzzy+lev) |  0.896 | 0.779 |   0.858 |  0.324 | 0.397 |

---

## Findings

1. **CyANCHOR is the strongest method** — EA 0.569 vs GraphRAG 0.467, ReAct 0.376, FCAV 0.276, No Val Link 0.052 — under an identical, shared Cypher system prompt. The ranking is identical to flight_accident; movie's larger, more ambiguous value space (~218k node values) lowers the absolute ceiling for every method but does not change the order.
2. **`fuzzy+lev` (no embeddings) already beats every baseline, including GraphRAG's Levenshtein repair.** GraphRAG and CyANCHOR share the *same* APOC normalized-Levenshtein primitive (server-side scan over the full value set); the +0.102 EA gap is the *architecture* — CyANCHOR grounds every mention proactively via the union of arms, GraphRAG only repairs values reactively, one at a time, after a generated query fails validation — not the retrieval primitive.
3. **Gains concentrate on `partial`** (0.756 vs GraphRAG 0.478, +0.278) and on `alias` / `casing`. On `typo`, GraphRAG's reactive single-value repair is on par (0.761 vs 0.733, within noise) — single-character typos are exactly what edit-distance repair nails. `abbrev` stays hard for every method (≤0.34): contractions are not recoverable by edit distance alone, and here token-fuzzy ReAct (0.341) edges the Lev-based methods.
4. **CyANCHOR degrades most gracefully with query difficulty** (hard 0.551 vs GraphRAG 0.343, FCAV 0.294): decomposing the question per entity mention helps most on multi-entity hard queries, where a single reactive repair pass tends to leave residual ungrounded mentions.
