# nba — entity-perturbed CypherBench (per-graph report)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-21.

**Setup.** CypherBench `nba`, 258 entity-perturbed test questions
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
| No Val Link          | —         | 0.074 | 0.110 | 257 |   1 |
| FCAV                 | vector    | 0.078 | 0.126 | 256 |   2 |
| ReAct (Node + Rel)   | fuzzy     | 0.337 | 0.368 | 258 |   0 |
| GraphRAG             | norm-Lev  | 0.682 | 0.759 | 258 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.779 | 0.858 | 258 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.269 | 0.052 |   0.053 |  0.070 | 0.034 |
| FCAV                 |  0.308 | 0.051 |   0.054 |  0.054 | 0.051 |
| ReAct (Node + Rel)   |  0.577 | 0.458 |   0.439 |  0.140 | 0.203 |
| GraphRAG             |  0.769 | 0.780 |   0.754 |  0.667 | 0.492 |
| CyANCHOR (fuzzy+lev) |  0.885 | 0.831 |   0.877 |  0.737 | 0.627 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.075 |  0.057 | 0.104 |
| FCAV                 | 0.100 |  0.058 | 0.104 |
| ReAct (Node + Rel)   | 0.300 |  0.333 | 0.364 |
| GraphRAG             | 0.800 |  0.723 | 0.545 |
| CyANCHOR (fuzzy+lev) | 0.775 |  0.787 | 0.766 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.259 | 0.110 |   0.062 |  0.146 | 0.055 |
| FCAV                 |  0.340 | 0.114 |   0.068 |  0.134 | 0.092 |
| ReAct (Node + Rel)   |  0.597 | 0.523 |   0.443 |  0.212 | 0.188 |
| GraphRAG             |  0.797 | 0.872 |   0.831 |  0.769 | 0.549 |
| CyANCHOR (fuzzy+lev) |  0.923 | 0.944 |   0.935 |  0.869 | 0.659 |

---

## Findings

1. **CyANCHOR is the strongest method** — EA 0.779 vs GraphRAG 0.682, ReAct 0.337, FCAV 0.078, No Val Link 0.074 — under an identical, shared Cypher system prompt. nba's value space (player / team / season names) is smaller and cleaner than movie's, so absolute scores are high; the ranking matches movie and flight_accident.
2. **CyANCHOR beats GraphRAG on every perturbation strategy** (casing 0.885 vs 0.769, typo 0.831 vs 0.780, partial 0.877 vs 0.754, abbrev 0.737 vs 0.667, alias 0.627 vs 0.492) — unlike movie, where GraphRAG's reactive Levenshtein tied on typo. The gains are largest on `partial` (+0.123) and `alias` (+0.135), the perturbations that degrade the surface form most.
3. **The query-difficulty axis is the cleanest separator.** CyANCHOR is flat across difficulty (easy 0.775 / medium 0.787 / hard 0.766); GraphRAG degrades sharply (0.800 → 0.723 → 0.545). On hard, multi-entity queries CyANCHOR leads by +0.221 — proactive per-mention grounding resolves every entity, whereas a single reactive repair pass leaves residual ungrounded mentions. GraphRAG only edges CyANCHOR on `easy` (0.800 vs 0.775), where fixing one value suffices.
4. **The no-grounding methods collapse** (No Val Link 0.074, FCAV 0.078): perturbed NBA player/team names are unrecoverable without value linking — confirming nba is grounding-bound, exactly the regime where CyANCHOR's design pays off.
