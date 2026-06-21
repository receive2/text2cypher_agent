# flight_accident — entity-perturbed CypherBench (per-graph report)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-21.

**Setup.** CypherBench `flight_accident`, 170 entity-perturbed test questions
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
| No Val Link          | —         | 0.107 | 0.117 | 168 |   2 |
| FCAV                 | vector    | 0.479 | 0.521 | 167 |   3 |
| ReAct (Node + Rel)   | fuzzy     | 0.406 | 0.410 | 170 |   0 |
| GraphRAG             | norm-Lev  | 0.612 | 0.621 | 170 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.794 | 0.843 | 170 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.176 | 0.027 |   0.158 |  0.132 | 0.079 |
| FCAV                 |  0.706 | 0.605 |   0.486 |  0.378 | 0.342 |
| ReAct (Node + Rel)   |  0.588 | 0.579 |   0.395 |  0.237 | 0.333 |
| GraphRAG             |  0.824 | 0.895 |   0.526 |  0.500 | 0.436 |
| CyANCHOR (fuzzy+lev) |  1.000 | 0.921 |   0.737 |  0.737 | 0.692 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.058 |  0.056 | 0.250 |
| FCAV                 | 0.404 |  0.444 | 0.628 |
| ReAct (Node + Rel)   | 0.462 |  0.370 | 0.400 |
| GraphRAG             | 0.635 |  0.589 | 0.622 |
| CyANCHOR (fuzzy+lev) | 0.808 |  0.781 | 0.800 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.254 | 0.052 |   0.108 |  0.180 | 0.066 |
| FCAV                 |  0.783 | 0.669 |   0.460 |  0.485 | 0.348 |
| ReAct (Node + Rel)   |  0.588 | 0.546 |   0.388 |  0.269 | 0.359 |
| GraphRAG             |  0.842 | 0.927 |   0.566 |  0.522 | 0.375 |
| CyANCHOR (fuzzy+lev) |  1.000 | 0.991 |   0.845 |  0.778 | 0.690 |

---

## Findings

1. **CyANCHOR is the strongest method** — EA 0.794 vs GraphRAG 0.612, FCAV 0.479, ReAct 0.406, No Val Link 0.107 — under an identical, shared Cypher system prompt.
2. **Normalized Levenshtein (fuzzy+lev) needs no embeddings yet beats every baseline.** GraphRAG and CyANCHOR share the same APOC Levenshtein primitive; the gap is the architecture (proactive per-mention grounding vs reactive repair), not the primitive.
3. **Gains concentrate on the hardest perturbations** (partial / abbrev / alias), where per-mention decomposition + the edit-distance arm recover values BM25/fuzzy miss.
4. **GraphRAG's reactive Levenshtein repair lifts it above the other baselines**, but CyANCHOR's proactive multi-arm grounding is decisively ahead.
