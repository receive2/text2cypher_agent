# CyANCHOR component ablation — gpt-5.6-terra

Paired per question against the full-method reference on the same questions (runs restricted to questions verbatim in the current release; pole uses its first 400 questions). Cells: Δ EA in points; **bold** = two-sided sign test p < 0.05; — = not run.

## Δ EA

| variant | switch | flight_accident | healthcare | pole | nba |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | — | 0.863 | 0.701 | 0.357 | 0.785 |
| − escalation loop | `PLAN_EXEC_ESCALATE=0` | **-9.5** | +0.2 | -2.2 | **-8.8** |
| − select-or-abstain judge | `PLAN_EXEC_SELECT_JUDGE=0` | +0.6 | +0.7 | -2.0 | -0.4 |
| − semantic repair | `CYPHER_SEMANTIC_REPAIR=0` | -3.6 | -2.6 | **-4.5** | -4.4 |
| − value-snap | `PLAN_EXEC_VALUE_SNAP=0` | -2.4 | **-10.8** | **-18.0** | **-6.0** |
| − relation tools | `TOOL_TYPE=node` | +2.4 | +0.7 | -0.3 | -0.8 |
| fuzzy arm only | `RETRIEVAL_LEVENSHTEIN=0` | -4.8 | **-6.2** | **-4.5** | **-11.2** |
| lev arm only | `RETRIEVAL_FUZZY=0` | -0.6 | +0.0 | -1.7 | +0.0 |
| + vector arm | `RETRIEVAL_VECTOR=1` | — | — | — | — |
| − all correction (escalation, judge, repair, value-snap) | `—` | — | — | — | — |

n: flight_accident 168 · healthcare 418 · pole 400 · nba 251

## Paired flips (gained / lost), sign-test p

| variant | flight_accident | healthcare | pole | nba |
|---|---|---|---|---|
| − escalation loop | 2/18, p=0.0004 | 11/10, p=1 | 8/17, p=0.11 | 5/27, p=0.00011 |
| − select-or-abstain judge | 6/5, p=1 | 20/17, p=0.74 | 13/21, p=0.23 | 13/14, p=1 |
| − semantic repair | 4/10, p=0.18 | 13/24, p=0.099 | 7/25, p=0.0021 | 10/21, p=0.071 |
| − value-snap | 5/9, p=0.42 | 16/61, p=2.4e-07 | 4/76, p=2.8e-18 | 7/22, p=0.0081 |
| − relation tools | 12/8, p=0.5 | 12/9, p=0.66 | 15/16, p=1 | 11/13, p=0.84 |
| fuzzy arm only | 8/16, p=0.15 | 19/45, p=0.0016 | 6/24, p=0.0014 | 5/33, p=4.3e-06 |
| lev arm only | 9/10, p=1 | 12/12, p=1 | 12/19, p=0.28 | 13/13, p=1 |
| + vector arm | — | — | — | — |
| − all correction (escalation, judge, repair, value-snap) | — | — | — | — |

## Per-category Δ EA (points)

**flight_accident** — n per category: casing 15, typo 10, partial 18, abbrev 89, alias 36

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 1.000 | 1.000 | 0.889 | 0.831 | 0.833 |
| − escalation loop | +0.0 | -20.0 | +5.6 | -13.5 | -8.3 |
| − select-or-abstain judge | +0.0 | -10.0 | +5.6 | -1.1 | +5.6 |
| − semantic repair | +0.0 | -20.0 | +0.0 | -2.2 | -5.6 |
| − value-snap | +0.0 | +0.0 | +0.0 | -1.1 | -8.3 |
| − relation tools | +0.0 | +0.0 | +0.0 | +2.2 | +5.6 |
| fuzzy arm only | +0.0 | -10.0 | +5.6 | -6.7 | -5.6 |
| lev arm only | -13.3 | +0.0 | +5.6 | +1.1 | -2.8 |

**healthcare** — n per category: casing 44, typo 79, partial 42, abbrev 129, alias 124

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.773 | 0.759 | 0.952 | 0.690 | 0.565 |
| − escalation loop | +2.3 | -2.5 | -4.8 | +3.1 | +0.0 |
| − select-or-abstain judge | +0.0 | +3.8 | -7.1 | +0.0 | +2.4 |
| − semantic repair | -6.8 | -1.3 | -9.5 | +3.1 | -5.6 |
| − value-snap | -4.5 | -22.8 | -21.4 | -7.0 | -5.6 |
| − relation tools | +4.5 | +3.8 | -4.8 | +1.6 | -1.6 |
| fuzzy arm only | +2.3 | +2.5 | -4.8 | -10.9 | -10.5 |
| lev arm only | +4.5 | -2.5 | -2.4 | +2.3 | -1.6 |

**pole** — n per category: casing 44, typo 247, partial 75, abbrev 34, alias 0

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.409 | 0.344 | 0.400 | 0.294 | — |
| − escalation loop | -2.3 | -0.8 | -5.3 | -5.9 | — |
| − select-or-abstain judge | -4.5 | -2.4 | -2.7 | +5.9 | — |
| − semantic repair | -6.8 | -2.4 | -5.3 | -14.7 | — |
| − value-snap | -4.5 | -24.3 | -9.3 | -8.8 | — |
| − relation tools | -6.8 | +1.2 | -4.0 | +5.9 | — |
| fuzzy arm only | -2.3 | -2.0 | -5.3 | -23.5 | — |
| lev arm only | -2.3 | -1.6 | -1.3 | -2.9 | — |

**nba** — n per category: casing 25, typo 7, partial 59, abbrev 65, alias 95

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.880 | 1.000 | 0.898 | 0.708 | 0.726 |
| − escalation loop | -8.0 | -14.3 | -5.1 | -4.6 | -13.7 |
| − select-or-abstain judge | +0.0 | +0.0 | +0.0 | -4.6 | +2.1 |
| − semantic repair | -4.0 | +0.0 | -5.1 | -12.3 | +1.1 |
| − value-snap | +0.0 | +0.0 | -6.8 | -9.2 | -5.3 |
| − relation tools | -8.0 | -14.3 | -1.7 | -1.5 | +3.2 |
| fuzzy arm only | +0.0 | +0.0 | -1.7 | -30.8 | -7.4 |
| lev arm only | -4.0 | +0.0 | -1.7 | -1.5 | +3.2 |

## Missing cells for the paper table (3 test graphs × 8 rows)

- + vector arm: flight_accident, healthcare, pole, nba

4 missing. `+ vector arm` needs per-graph embeddings first (archives have EMBEDDABLE_PROPERTIES=[]). Driver for the rest: `scripts/tuning/run_ablation_model.py --model gpt-5.6-terra` (add `--with-joint` for the all-correction row).

Detection floor (paired sign test, 80% power, observed 4–8% discordance): ~5–6 points at n=167, ~3.5 at n≈400, ~2.4 pooled over the three test graphs.

## Sources

References: `logs/ablation_gpt-5.6-terra/flight_accident__reference`, `logs/ablation_gpt-5.6-terra/healthcare__reference`, `logs/ablation_gpt-5.6-terra/pole__reference`, `logs/ablation_gpt-5.6-terra/nba__reference`. Variants: `logs/ablation_gpt-5.6-terra`. Backbone gpt-5.6-terra, SHARDS=1, errors score 0.
