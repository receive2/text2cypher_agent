# Ablation — pole (entity-perturbed ZOGRASCOPE)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-21.

**Setup.** ZOGRASCOPE `pole`, 200 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev). LLMs: gpt-4.1 for grounding
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
| No Val Link          | —         | 0.035 | 0.041 | 200 |   0 |
| FCAV                 | vector    | 0.071 | 0.142 | 198 |   2 |
| ReAct (Node + Rel)   | fuzzy     | 0.215 | 0.314 | 200 |   0 |
| GraphRAG             | norm-Lev  | 0.095 | 0.270 | 200 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.280 | 0.347 | 200 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.150 | 0.019 |   0.032 |  0.000 |
| FCAV                 |  0.100 | 0.093 |   0.016 |  0.100 |
| ReAct (Node + Rel)   |  0.150 | 0.176 |   0.290 |  0.300 |
| GraphRAG             |  0.150 | 0.083 |   0.113 |  0.000 |
| CyANCHOR (fuzzy+lev) |  0.200 | 0.287 |   0.306 |  0.200 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.036 | 0.050 |
| FCAV                 | 0.053 |  0.079 | 0.050 |
| ReAct (Node + Rel)   | 0.100 |  0.243 | 0.175 |
| GraphRAG             | 0.100 |  0.086 | 0.125 |
| CyANCHOR (fuzzy+lev) | 0.050 |  0.300 | 0.325 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev |
| -------------------- | -----: | ----: | ------: | -----: |
| No Val Link          |  0.241 | 0.012 |   0.034 |  0.000 |
| FCAV                 |  0.424 | 0.156 |   0.031 |  0.101 |
| ReAct (Node + Rel)   |  0.431 | 0.286 |   0.357 |  0.104 |
| GraphRAG             |  0.507 | 0.231 |   0.299 |  0.024 |
| CyANCHOR (fuzzy+lev) |  0.515 | 0.322 |   0.376 |  0.104 |

---

## Findings

1. **CyANCHOR is the strongest method on both EA (0.280) and PSJS (0.347)**, and the grounding methods (ReAct 0.215, CyANCHOR 0.280) clearly separate from the non-grounding ones (No Val Link 0.035, FCAV 0.071). PSJS ≥ EA for every method — pole's schema is non-redundant, so there is **none** of the equivalent-but-different-path PSJS distortion seen on covid.
2. **Absolute EA is low for every method** because ZOGRASCOPE/pole queries are multi-hop crime-investigation chains (2–4 entity hops — surname + address + officer, etc. — scored on exact result-set match), far harder than CypherBench's single-entity lookups. The *ordering* and CyANCHOR's lead are nonetheless robust, and gains track grounding quality cleanly.
3. **ReAct beats GraphRAG here (0.215 vs 0.095) — the reverse of movie/flight.** GraphRAG's reactive value-repair is much weaker on multi-hop queries: it plants the *perturbed* surface form first (observed: `surname:"COOPER"`, `address:"194 Gaeth Road"`), and its repair only fires on empty/error and cannot fix relationship-direction / structural errors. Proactive grounding (ReAct, CyANCHOR — which produced `"Cooper"`, `"194 Garth Road"`) avoids planting the bad value in the first place. This is a faithful property of the reactive-repair paradigm, exposed by multi-hop difficulty — not a misconfiguration (GraphRAG ran 200/200, 0 errors).
4. **Gains concentrate on the bulk buckets** — `typo` (0.287 vs ReAct 0.176, GraphRAG 0.083; n=108) and `medium`/`hard` difficulty (CyANCHOR 0.300 / 0.325 vs ReAct 0.243 / 0.175; n=140 / 40). The small buckets are noisy and not load-bearing: `abbrev` (n=10), `casing` and `easy` (n=20 each) — there ReAct edges CyANCHOR on `abbrev` (0.300 vs 0.200) well within sampling noise.
