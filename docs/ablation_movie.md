# Ablation — movie (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over each mode's successfully-scored rows. Generated 2026-06-18.

**Setup.** CypherBench `movie` (~459k nodes: Movie 218,828 · Person 234,309 · plus
Award/Genre/Country/FilmSeries/ProductionCompany), 200 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias). LLMs: gpt-4.1 for grounding and
Cypher generation. Each mode is scored over its own successfully-executed rows (per-mode `n`).

> **Retrieval is fuzzy-only here.** Hybrid (BM25 ∪ in-graph vector) needs a per-graph
> vector index; building it on movie was previously ~tens of hours due to a missing
> range index on the `.name` properties — now fixed in `setup_project.py`
> (`ensure_value_range_indexes`), making hybrid setup ~30 min. The **Plan&Exec Hybrid**
> row is pending that build.

**Modes.**
- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).
- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve candidate
  values from a self-built value index, an LLM generates the entity JSON.
- **ReAct Fuzzy (Node + Rel)** — ReAct NER agent (BM25/fuzzy retrieval) over node + relation tools.
- **Plan&Exec Fuzzy (Node + Rel)** — plan-and-execute grounder: decompose the question into
  entity mentions, route each to a database field, retrieve candidates with an LLM-judge
  corrective loop (adds the right field / more values when a mention is not yet grounded),
  then the Cypher LLM value-links. Fuzzy = BM25 only (zero embeddings).

---

## Overall

| mode                          | retrieval |    EA |  PSJS |   n | err |
| ----------------------------- | --------- | ----: | ----: | --: | --: |
| No Val Link                   | —         | 0.030 | 0.115 | 200 |   6 |
| FCAV (RAG)                    | vector    | 0.200 | 0.381 | 200 |   4 |
| ReAct Fuzzy (Node + Rel)      | fuzzy     | 0.240 | 0.464 | 200 |   5 |
| Plan&Exec Fuzzy (Node + Rel)  | fuzzy     | 0.310 | 0.561 | 200 |   5 |
| Plan&Exec Hybrid (Node + Rel) | hybrid    |   _pending_ |   _–_ |   _–_ |   _–_ |

## By perturbation strategy — EA

| mode                          | casing |  typo | partial | abbrev | alias |
| ----------------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link                   |  0.250 | 0.022 |   0.000 |  0.000 | 0.000 |
| FCAV (RAG)                    |  0.550 | 0.326 |   0.174 |  0.048 | 0.087 |
| ReAct Fuzzy (Node + Rel)      |  0.700 | 0.348 |   0.217 |  0.143 | 0.043 |
| Plan&Exec Fuzzy (Node + Rel)  |  0.550 | 0.478 |   0.370 |  0.143 | 0.130 |

## By query-difficulty — EA

| mode                          |  easy | medium |  hard |
| ----------------------------- | ----: | -----: | ----: |
| No Val Link                   | 0.000 |  0.057 | 0.000 |
| FCAV (RAG)                    | 0.200 |  0.248 | 0.129 |
| ReAct Fuzzy (Node + Rel)      | 0.240 |  0.352 | 0.071 |
| Plan&Exec Fuzzy (Node + Rel)  | 0.440 |  0.400 | 0.129 |

## By perturbation strategy — PSJS

| mode                          | casing |  typo | partial | abbrev | alias |
| ----------------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link                   |  0.392 | 0.066 |   0.141 |  0.067 | 0.061 |
| FCAV (RAG)                    |  0.800 | 0.431 |   0.455 |  0.204 | 0.236 |
| ReAct Fuzzy (Node + Rel)      |  0.952 | 0.533 |   0.485 |  0.395 | 0.224 |
| Plan&Exec Fuzzy (Node + Rel)  |  0.801 | 0.640 |   0.755 |  0.325 | 0.400 |

---

## Findings

1. **Monotone gain from grounding quality.** No Val Link 0.030 → FCAV 0.200 → ReAct Fuzzy
   0.240 → **Plan&Exec Fuzzy 0.310**. Plan&Exec beats both the ReAct agent and the
   retrieve-then-generate RAG baseline, consistent with flight_accident.
2. **The advantage is real but smaller than on flight_accident** (where Plan&Exec hit 0.77).
   On movie the residual failures are dominated by **Cypher-generation** errors, not
   grounding: in the both-fail set, ~41% of cases have the entities grounded *correctly* but
   the generated query is structurally wrong (e.g. count-then-UNION instead of UNION-then-
   count on "either/or" questions). No grounding method can recover those.
3. **Remaining grounding misses are the hardest perturbations** — abbreviations (`LOTR:TTT`)
   and semantic substitutions (`Jason's ship` → `Argo`) that BM25 fuzzy cannot match. These
   are where **Hybrid** (in-graph vector) is expected to help; that row is pending.
4. **PSJS tracks EA** (0.115 → 0.381 → 0.464 → 0.561): even when EA fails, Plan&Exec's
   partial subgraph overlap is highest, i.e. its queries are closest to gold.
5. **One reversal: ReAct edges Plan&Exec on `casing`** (0.700 vs 0.550, small n). On the
   easiest perturbation, Plan&Exec's PLAN stage occasionally over-decomposes — treating
   schema words (`"movies"`, `"cast members"`) as groundable mentions and routing the real
   entity to a non-`name` field — adding noise the simpler ReAct path avoids. A natural
   improvement target (constrain PLAN mentions; prefer `*.name` routing), orthogonal to the
   Cypher-generation ceiling in (2).
