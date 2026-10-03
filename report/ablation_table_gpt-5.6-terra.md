# CyANCHOR component ablation — gpt-5.6-terra

Paired per question against the full-method reference on the same questions (runs restricted to questions verbatim in the current release; every graph runs in full). Cells: Δ EA in points; **bold** = two-sided sign test p < 0.05; — = not run.

## Δ EA

| variant | switch | flight_accident | healthcare | pole | nba |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | — | 0.887 | 0.708 | 0.568 | 0.777 |
| − Adaptive Search Control | `PLAN_EXEC_ESCALATE=0` | **-8.9** | +0.7 | **-2.2** | -4.8 |
| − select-or-abstain judge | `PLAN_EXEC_SELECT_JUDGE=0` | — | — | -0.6 | — |
| − Result Aware Query Repair | `CYPHER_SEMANTIC_REPAIR=0` | -5.4 | **-3.1** | **-3.5** | -3.2 |
| − Value Existence Guard | `PLAN_EXEC_VALUE_SNAP=0` | -5.4 | **-10.3** | **-21.6** | **-5.2** |
| − Levenshtein Retrieval | `RETRIEVAL_LEVENSHTEIN=0` | -6.0 | -3.3 | **-3.6** | **-8.8** |
| − Token Level Fuzzy Match | `RETRIEVAL_FUZZY=0` | **-8.3** | +1.4 | -0.6 | -2.4 |

n: flight_accident 168 · healthcare 418 · pole 1283 · nba 251

## Paired flips (gained / lost), sign-test p

| variant | flight_accident | healthcare | pole | nba |
|---|---|---|---|---|
| − Adaptive Search Control | 6/21, p=0.0059 | 17/14, p=0.72 | 72/100, p=0.039 | 10/22, p=0.05 |
| − select-or-abstain judge | — | — | 77/85, p=0.58 | — |
| − Result Aware Query Repair | 7/16, p=0.093 | 12/25, p=0.047 | 59/104, p=0.00053 | 8/16, p=0.15 |
| − Value Existence Guard | 6/15, p=0.078 | 18/61, p=1.3e-06 | 46/323, p=2.3e-52 | 5/18, p=0.011 |
| − Levenshtein Retrieval | 10/20, p=0.099 | 23/37, p=0.092 | 77/123, p=0.0014 | 8/30, p=0.00047 |
| − Token Level Fuzzy Match | 5/19, p=0.0066 | 19/13, p=0.38 | 73/81, p=0.57 | 10/16, p=0.33 |

## Per-category Δ EA (points)

**flight_accident** — n per category: casing 15, typo 10, partial 18, abbrev 89, alias 36

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 1.000 | 1.000 | 0.889 | 0.854 | 0.889 |
| − Adaptive Search Control | +0.0 | -10.0 | +0.0 | -9.0 | -16.7 |
| − Result Aware Query Repair | +0.0 | -10.0 | -5.6 | -6.7 | -2.8 |
| − Value Existence Guard | +0.0 | -10.0 | +11.1 | -6.7 | -11.1 |
| − Levenshtein Retrieval | +0.0 | -10.0 | +11.1 | -9.0 | -8.3 |
| − Token Level Fuzzy Match | +0.0 | -20.0 | +5.6 | -9.0 | -13.9 |

**healthcare** — n per category: casing 44, typo 79, partial 42, abbrev 129, alias 124

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.818 | 0.797 | 0.905 | 0.705 | 0.548 |
| − Adaptive Search Control | -2.3 | -1.3 | +2.4 | +3.9 | -0.8 |
| − Result Aware Query Repair | -9.1 | -1.3 | -4.8 | -0.8 | -4.0 |
| − Value Existence Guard | -2.3 | -21.5 | -16.7 | -9.3 | -4.8 |
| − Levenshtein Retrieval | +0.0 | +2.5 | +2.4 | -7.0 | -6.5 |
| − Token Level Fuzzy Match | +2.3 | +0.0 | +0.0 | +0.0 | +4.0 |

**pole** — n per category: casing 143, typo 793, partial 234, abbrev 113, alias 0

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.531 | 0.512 | 0.748 | 0.637 | — |
| − Adaptive Search Control | +3.5 | -2.6 | -1.3 | -8.0 | — |
| − select-or-abstain judge | +3.5 | -1.1 | +2.6 | -8.8 | — |
| − Result Aware Query Repair | +2.1 | -2.1 | -5.6 | -15.9 | — |
| − Value Existence Guard | -0.7 | -30.5 | -10.7 | -8.0 | — |
| − Levenshtein Retrieval | +4.9 | +1.8 | -0.4 | -58.4 | — |
| − Token Level Fuzzy Match | +3.5 | -0.4 | -0.4 | -8.0 | — |

**nba** — n per category: casing 25, typo 7, partial 59, abbrev 65, alias 95

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.800 | 0.857 | 0.881 | 0.692 | 0.758 |
| − Adaptive Search Control | +0.0 | +14.3 | -5.1 | -1.5 | -9.5 |
| − Result Aware Query Repair | +0.0 | +0.0 | -1.7 | -1.5 | -6.3 |
| − Value Existence Guard | +0.0 | +14.3 | -3.4 | -1.5 | -11.6 |
| − Levenshtein Retrieval | +0.0 | +0.0 | +0.0 | -26.2 | -5.3 |
| − Token Level Fuzzy Match | +0.0 | +14.3 | -3.4 | -1.5 | -4.2 |

## Missing cells (4 graphs × 6 rows)

- − select-or-abstain judge: flight_accident, healthcare, nba

3 missing. Rerun `python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on --scope node --pole-full` to fill them.

Detection floor (paired sign test, 80% power, observed 4–8% discordance): ~5–6 points at n=167, ~3.5 at n≈400, ~2.4 pooled over the three test graphs.

## Sources

References: `logs/ablation_gpt-5.6-terra__judge-on-node/flight_accident__reference`, `logs/ablation_gpt-5.6-terra__judge-on-node/healthcare__reference`, `logs/ablation_gpt-5.6-terra__judge-on-node/pole_full__reference`, `logs/ablation_gpt-5.6-terra__judge-on-node/nba__reference`. Variants: `logs/ablation_gpt-5.6-terra__judge-on-node`. Backbone gpt-5.6-terra, SHARDS=1, errors score 0.
