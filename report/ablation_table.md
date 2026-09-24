# CyANCHOR component ablation (gpt-4.1)

Every cell is paired per question against the full-method reference run on the same questions. Question sets are the v2.1 ablation runs restricted to questions that appear verbatim in the v2.3 release (flight_accident 167/169, healthcare 398/400, pole 391/400); healthcare and pole use a fixed 400-question prefix. terrorist_attack is the CypherBench-train dev graph (not in the release). Cells show Δ EA in points when the component is removed; **bold** = two-sided sign test p < 0.05.

## Components

| variant | switch | flight_accident (CB) | healthcare (MTQ) | pole (ZOG) | mean Δ (test) | terrorist_attack (dev) |
|---|---|---|---|---|---|---|
| CyANCHOR (reference, EA) | — | 0.838 | 0.701 | 0.332 | — | 0.762 |
| − escalation loop | `PLAN_EXEC_ESCALATE=0` | -3.0 | — | — | — | — |
| − select-or-abstain | `PLAN_EXEC_SELECT_JUDGE=0` | -1.2 | — | — | — | — |
| − semantic repair | `CYPHER_SEMANTIC_REPAIR=0` | -1.8 | — | — | — | — |
| − empty-is-wrong ‡ | `CYPHER_EMPTY_IS_WRONG=0` | +0.6 | -0.3 | +0.3 | +0.2 | +0.8 |
| − value-snap | `PLAN_EXEC_VALUE_SNAP=0` | +0.6 | -2.3 | **-12.8** | -4.8 | -0.2 |
| − relation tools | `TOOL_TYPE=node` | +1.8 | -1.5 | +0.8 | +0.4 | +2.0 |
| fuzzy arm only | `RETRIEVAL_LEVENSHTEIN=0` | — | — | — | — | — |
| lev arm only | `RETRIEVAL_FUZZY=0` | — | — | — | — | — |
| + vector arm | `RETRIEVAL_VECTOR=1` | — | — | — | — | — |

n: flight_accident 167 · healthcare 398 · pole 391 · terrorist_attack 400. — = not run.

‡ The reference enables every component. The shipped configuration disables the empty-result trigger (`CYPHER_EMPTY_IS_WRONG` default off), i.e. it is this row.

## Paired flips and significance

gained / lost = questions the ablated variant gets right / wrong that the reference gets wrong / right.

| variant | flight_accident | healthcare | pole | terrorist_attack |
|---|---|---|---|---|
| − escalation loop | 4/9 (p=0.27) | — | — | — |
| − select-or-abstain | 5/7 (p=0.77) | — | — | — |
| − semantic repair | 4/7 (p=0.55) | — | — | — |
| − empty-is-wrong ‡ | 6/5 (p=1) | 15/16 (p=1) | 10/9 (p=1) | 24/21 (p=0.77) |
| − value-snap | 5/4 (p=1) | 10/19 (p=0.14) | 7/57 (p=7.6e-11) | 22/23 (p=1) |
| − relation tools | 5/2 (p=0.45) | 14/20 (p=0.39) | 11/8 (p=0.65) | 27/19 (p=0.3) |

## Per-category Δ EA (points)

**flight_accident** — category n: casing 15, typo 9, partial 18, abbrev 89, alias 36

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| reference EA | 0.933 | 0.889 | 0.944 | 0.854 | 0.694 |
| − escalation loop | +0.0 | -11.1 | +5.6 | -4.5 | -2.8 |
| − select-or-abstain | +6.7 | +0.0 | +0.0 | -4.5 | +2.8 |
| − semantic repair | +6.7 | -11.1 | -11.1 | -1.1 | +0.0 |
| − empty-is-wrong ‡ | +0.0 | +11.1 | +5.6 | -2.2 | +2.8 |
| − value-snap | +0.0 | -11.1 | +0.0 | +0.0 | +5.6 |
| − relation tools | +6.7 | +11.1 | +0.0 | +0.0 | +2.8 |

**healthcare** — category n: casing 42, typo 72, partial 40, abbrev 123, alias 121

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| reference EA | 0.833 | 0.806 | 0.800 | 0.715 | 0.545 |
| − empty-is-wrong ‡ | +2.4 | -2.8 | +10.0 | -2.4 | -0.8 |
| − value-snap | -4.8 | -2.8 | +0.0 | -2.4 | -1.7 |
| − relation tools | -9.5 | -2.8 | +7.5 | -2.4 | +0.0 |

**pole** — category n: casing 44, typo 238, partial 75, abbrev 34, alias 0

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| reference EA | 0.318 | 0.328 | 0.360 | 0.324 | — |
| − empty-is-wrong ‡ | +2.3 | +0.8 | +1.3 | -8.8 | — |
| − value-snap | +0.0 | -17.2 | -4.0 | -17.6 | — |
| − relation tools | +4.5 | +0.0 | +0.0 | +2.9 | — |

**terrorist_attack** — category n: casing 40, typo 91, partial 90, abbrev 89, alias 90

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| reference EA | 0.825 | 0.802 | 0.867 | 0.775 | 0.578 |
| − empty-is-wrong ‡ | +0.0 | +3.3 | -4.4 | +1.1 | +3.3 |
| − value-snap | +0.0 | +3.3 | -4.4 | -2.2 | +2.2 |
| − relation tools | -2.5 | -2.2 | +3.3 | +5.6 | +3.3 |

## Sources

Reference and variant runs: `logs/ablation/fa__*` (flight_accident), `logs/verify_cols/{healthcare,pole}__*` , `logs/dev_sweep/ta__*` (terrorist_attack). Backbone gpt-4.1 for all stages, SHARDS=1. Evaluation denominator = all questions (errors score 0).
