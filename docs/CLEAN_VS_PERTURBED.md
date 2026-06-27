# Clean vs. entity-perturbed — robustness snapshot

How the five methods behave on the **original (clean)** benchmark questions vs.
their **entity-perturbed** versions, on one graph from each of two benchmarks.
This isolates the paper's core claim: clean benchmarks **overestimate** robustness
because their entity mentions match database values verbatim, so a model barely
needs to *ground* anything; perturbation exposes the gap, and value grounding
(CyANCHOR) recovers most of it.

> Scope: this is a **2-graph snapshot** (CypherBench `flight_accident`,
> Mind-the-Query `bloom50`), not the full benchmark tables. It illustrates the
> effect; the per-dataset/full numbers live in `report/`.

## Setup

- **Metric.** EA = execution accuracy (predicted Cypher's result set matches gold);
  PSJS = provenance-subgraph Jaccard. Denominator = **all examples**; any failure
  (agent error, broken gold, or per-example timeout) scores 0 — the harness makes
  no assumptions about dataset quality (see `eval/difficulty.py`).
- **LLMs.** gpt-4.1 for grounding and Cypher generation (all stages).
- **clean** = original un-augmented questions (entities verbatim); **perturbed** =
  entity-perturbed questions (casing / typo / partial name / abbreviation / alias).
- **CyANCHOR** here is `fuzzy+lev`, run at `SHARDS=1` so LLM rate-limit timeouts are
  not miscounted as failures (it is the most LLM-call-heavy method; see
  [memory: neweval-shards-timeout]).

## CypherBench — `flight_accident`  (clean n=189 · perturbed n=170)

| method | clean EA | pert EA | ΔEA | retained | clean PSJS | pert PSJS |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.799 | 0.106 | −0.693 | 13% | 0.934 | 0.116 |
| FCAV | 0.815 | 0.471 | −0.344 | 58% | 0.906 | 0.511 |
| ReAct (Node + Rel) | 0.836 | 0.406 | −0.430 | 49% | 0.865 | 0.410 |
| GraphRAG | 0.947 | 0.612 | −0.335 | 65% | 0.977 | 0.621 |
| **CyANCHOR (fuzzy+lev)** | **0.952** | **0.800** | **−0.152** | **84%** | **0.990** | **0.845** |

## Mind-the-Query — `bloom50`  (clean n=58 · perturbed n=40)

| method | clean EA | pert EA | ΔEA | retained | clean PSJS | pert PSJS |
|---|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.448 | 0.275 | −0.173 | 61% | 0.776 | 0.374 |
| FCAV | 0.414 | 0.300 | −0.114 | 72% | 0.741 | 0.399 |
| ReAct (Node + Rel) | 0.707 | 0.525 | −0.182 | 74% | 0.724 | 0.500 |
| GraphRAG | 0.741 | 0.525 | −0.216 | 71% | 0.786 | 0.649 |
| **CyANCHOR (fuzzy+lev)** | **0.741** | **0.550** | **−0.191** | **74%** | **0.793** | **0.620** |

(`retained` = pert EA / clean EA — fraction of clean accuracy surviving perturbation.)

## Findings

1. **Clean benchmarks overestimate robustness.** On `flight_accident`, entities are
   verbatim, so even **No Val Link reaches 0.799** and the grounding methods sit near
   the ceiling (CyANCHOR 0.952 ≈ GraphRAG 0.947). Grounding looks unnecessary — until
   you perturb.

2. **Perturbation collapses un-grounded methods.** No Val Link falls 0.799 → 0.106
   (−0.69) on `flight_accident`; FCAV / ReAct / GraphRAG each lose 0.33–0.43. The
   "clean" ranking is not the "robust" ranking.

3. **CyANCHOR's contribution is robustness, not clean-data accuracy.** It ties the
   best method on clean data (it cannot beat a near-ceiling score), but loses the
   least under perturbation (ΔEA −0.152 on flight, the smallest of any method) and is
   ≥ every method on both clean and perturbed, on both graphs.

4. **Perturbation sensitivity is dataset-dependent.** CypherBench `flight_accident`
   is an entity-lookup graph with a high clean ceiling (~0.95) and verbatim entities,
   so perturbation bites hard and grounding's payoff is large. Mind-the-Query
   `bloom50` is a harder, multi-hop graph with a **low clean ceiling (~0.74)** — much
   of its difficulty is query structure, not entity matching — so perturbation bites
   less in absolute terms and the methods cluster more tightly. This is why
   grounding's *lead* is wide on CypherBench and narrow on Mind-the-Query: not a
   method weakness, but less of the entity-grounding problem to solve.

## Caveats (for reviewers)

- A 2-graph snapshot, one graph per benchmark — illustrative, not the full table.
- `clean` and `perturbed` are different question sets of different sizes (the
  perturbed/augmented set is a derived subset), so this is an aggregate comparison,
  not a per-question paired difference.
- Mind-the-Query golds include some non-executing queries; under this eval they score
  0 for every method (curation is a dataset-audit task — see
  [docs/GOLD_ERROR_AUDIT.md](GOLD_ERROR_AUDIT.md)). `bloom50` here had 0 such cases.

## Reproduce

```bash
# clean (original) — note SHARDS=1 for CyANCHOR to avoid rate-limit timeouts
#   EVAL_PAIRS=[("cypherbench","flight_accident")]   (CYPHERBENCH_PATH)
#   EVAL_PAIRS=[("mindthequery","bloom50")]          (MINDTHEQUERY_PATH)
python eval_run.py            # per METHOD in eval_config.py (loop the 5)
# perturbed: same but EVAL_PAIRS with the *_augmented dataset key.
# render: python gen_graph_report.py <graph> <dir> <label> <dataset_key>
```

Records: `logs/runs/{cypherbench,cypherbench_augmented}__flight_accident__*/`,
`logs/runs/{mindthequery,mindthequery_augmented}__{bloom50,bloom}__*/`.

_Generated 2026-06-27 · gpt-4.1 · eval denominator = all examples (errors score 0)._
