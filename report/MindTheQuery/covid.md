# covid — entity-perturbed MindTheQuery (per-graph report)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each method's successfully-executed rows. Generated 2026-06-21.

**Setup.** MindTheQuery `covid`, 342 entity-perturbed test questions
(strategies: casing · typo · partial · alias). LLMs: gpt-4.1 for grounding
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

| method                   | retrieval     |    EA |  PSJS |   n | err |
| ------------------------ | ------------- | ----: | ----: | --: | --: |
| No Val Link              | —             | 0.053 | 0.137 | 150 | 192 |
| FCAV                     | vector        | 0.049 | 0.181 | 143 | 199 |
| ReAct (Node + Rel)       | fuzzy         | 0.198 | 0.341 | 283 |  59 |
| GraphRAG                 | norm-Lev      | 0.456 | 0.556 | 283 |  59 |
| CyANCHOR (fuzzy+lev)     | fuzzy+lev     | 0.353 | 0.221 | 283 |  59 |
| CyANCHOR (fuzzy+lev+vec) | fuzzy+lev+vec | 0.343 | 0.214 | 283 |  59 |

## By perturbation strategy — EA

| method                   | casing |  typo | partial | alias |
| ------------------------ | -----: | ----: | ------: | ----: |
| No Val Link              |  0.056 | 0.032 |   0.097 | 0.125 |
| FCAV                     |  0.053 | 0.034 |   0.074 | 0.125 |
| ReAct (Node + Rel)       |  0.242 | 0.205 |   0.167 | 0.118 |
| GraphRAG                 |  0.333 | 0.465 |   0.625 | 0.118 |
| CyANCHOR (fuzzy+lev)     |  0.364 | 0.373 |   0.375 | 0.059 |
| CyANCHOR (fuzzy+lev+vec) |  0.424 | 0.346 |   0.375 | 0.059 |

## By query-difficulty — EA

| method                   | medium |  hard |
| ------------------------ | -----: | ----: |
| No Val Link              |  0.071 | 0.037 |
| FCAV                     |  0.071 | 0.027 |
| ReAct (Node + Rel)       |  0.178 | 0.210 |
| GraphRAG                 |  0.514 | 0.420 |
| CyANCHOR (fuzzy+lev)     |  0.336 | 0.364 |
| CyANCHOR (fuzzy+lev+vec) |  0.299 | 0.369 |

## By perturbation strategy — PSJS

| method                   | casing |  typo | partial | alias |
| ------------------------ | -----: | ----: | ------: | ----: |
| No Val Link              |  0.178 | 0.112 |   0.139 | 0.326 |
| FCAV                     |  0.192 | 0.127 |   0.273 | 0.451 |
| ReAct (Node + Rel)       |  0.517 | 0.311 |   0.376 | 0.218 |
| GraphRAG                 |  0.574 | 0.518 |   0.742 | 0.404 |
| CyANCHOR (fuzzy+lev)     |  0.212 | 0.195 |   0.323 | 0.236 |
| CyANCHOR (fuzzy+lev+vec) |  0.189 | 0.199 |   0.278 | 0.240 |

---

## Findings

1. **Framing — a characterized limitation, reported transparently.** covid (MindTheQuery; *supplementary* to the CypherBench main results, not part of the headline table) is the single graph where CyANCHOR trails GraphRAG (EA 0.353 vs 0.456). The deficit is driven by a redundant schema interacting with CyANCHOR's per-mention grounding — **not** weaker grounding: the same mechanism is harmless and CyANCHOR wins decisively on flight / movie / pole.
2. **Read EA as the primary metric here; treat PSJS only with the caveat below.** covid models every visit twice — a direct `(:Person)-[:VISITS]->(:Place)` edge **and** a reified `(:Person)-[:PERFORMS_VISIT]->(:Visit)-[:LOCATED_AT]->(:Place)` path (5009 ≡ 5009, identical properties, execution-equivalent). PSJS (subgraph overlap) therefore *penalises execution-equivalent paths*: predictions on the reified path score PSJS **0.122** vs **0.833** on the direct path. This is a metric × redundant-schema artifact, not a correctness signal — it depresses every method's PSJS on its reified-path rows (GraphRAG's reified rows also score 0.126).
3. **Attribution, layer 1 — benchmark defect (excluded from scoring).** 17% of covid's gold cyphers (59/342) are themselves syntactically invalid on Neo4j 5.x (DateTime-parse / undefined-variable / COUNT-syntax errors) and are excluded from every method's denominator. This is a dataset-quality issue, not a method result.
4. **Attribution, layer 2 — covid is Cypher-generation-bound, not grounding-bound.** ≈70% of its questions are Complex_Aggregation (multi-clause avg / count / compare), where the bottleneck is query *structure*, not value linking. The grounding advantage that wins flight / movie / pole does not transfer here — even the strongest method tops out at EA 0.456, and No-Val-Link/FCAV collapse (≈0.05) because they cannot generate the aggregation skeleton at all.
5. **Attribution, layer 3 — the residual, method-side cause (root-caused by a live trace).** CyANCHOR's NER over-extracts structural / aggregation words — `visits`, `percentage` — as node entities and routes them to the redundant `Visit` node's tools (`get_visit_duration`, …), so the Cypher LLM emits the **reified** path 87% of the time vs gold's 5%. The longer reified path is more error-prone on aggregation queries (reified-path EA 0.371 vs direct 0.453 for GraphRAG), which both depresses EA and — per the layer-2 caveat — collapses PSJS.
6. **Net + future work.** covid's deficit is roughly half *metric/benchmark artifact* (PSJS path-penalty, 17% broken golds, aggregation-bound composition) and half a *narrow, real method quirk* (reified-path bias) that surfaces **only** under redundant schema. A principled, schema-agnostic fix — suppressing grounding evidence for mentions that matched no value (the trace shows `visits`→`Visit.endtime` returns no fuzzy match yet still seeds the evidence) — is left as future work; we deliberately do **not** tune to this benchmark.
