# CyANCHOR component ablation — gpt-5.6-terra

Paired per question against the full-method reference on the same questions (runs restricted to questions verbatim in the current release; every graph runs in full). Cells: Δ EA in points; **bold** = two-sided sign test p < 0.05; — = not run.

## Δ EA

| variant | switch | pole |
|---|---|---|
| CyANCHOR full (EA) | — | 0.341 |
| − escalation loop | `PLAN_EXEC_ESCALATE=0` | — |
| − select-or-abstain judge | `PLAN_EXEC_SELECT_JUDGE=0` | -0.6 |
| − semantic repair | `CYPHER_SEMANTIC_REPAIR=0` | — |
| − value-snap | `PLAN_EXEC_VALUE_SNAP=0` | — |
| fuzzy arm only | `RETRIEVAL_LEVENSHTEIN=0` | — |
| lev arm only | `RETRIEVAL_FUZZY=0` | — |

n: pole 1283

## Paired flips (gained / lost), sign-test p

| variant | pole |
|---|---|
| − escalation loop | — |
| − select-or-abstain judge | 41/49, p=0.46 |
| − semantic repair | — |
| − value-snap | — |
| fuzzy arm only | — |
| lev arm only | — |

## Per-category Δ EA (points)

**pole** — n per category: casing 143, typo 793, partial 234, abbrev 113, alias 0

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.336 | 0.290 | 0.496 | 0.381 | — |
| − select-or-abstain judge | +0.0 | -0.9 | +1.7 | -4.4 | — |

## Missing cells (1 graphs × 6 rows)

- − escalation loop: pole
- − semantic repair: pole
- − value-snap: pole
- fuzzy arm only: pole
- lev arm only: pole

5 missing. Rerun `python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on --pole-full` to fill them.

Detection floor (paired sign test, 80% power, observed 4–8% discordance): ~5–6 points at n=167, ~3.5 at n≈400, ~2.4 pooled over the three test graphs.

## Sources

References: `logs/ablation_gpt-5.6-terra__judge-on-node/pole_full__reference`. Variants: `logs/ablation_gpt-5.6-terra__judge-on-node`. Backbone gpt-5.6-terra, SHARDS=1, errors score 0.
