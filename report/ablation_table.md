# CyANCHOR component ablation — gpt-4.1

Paired per question against the full-method reference on the same questions (runs restricted to questions verbatim in the current release; healthcare and pole use a fixed 400-question prefix). terrorist_attack is the CypherBench-train dev graph, not part of the release. Cells: Δ EA in points; **bold** = two-sided sign test p < 0.05; — = not run.

## Δ EA

| variant | switch | flight_accident | healthcare | pole | terrorist_attack |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | — | 0.838 | 0.701 | 0.332 | 0.762 |
| − escalation loop | `PLAN_EXEC_ESCALATE=0` | -3.0 | — | — | — |
| − select-or-abstain judge | `PLAN_EXEC_SELECT_JUDGE=0` | -1.2 | — | — | — |
| − semantic repair | `CYPHER_SEMANTIC_REPAIR=0` | -1.8 | — | — | — |
| − value-snap | `PLAN_EXEC_VALUE_SNAP=0` | +0.6 | -2.3 | **-12.8** | -0.2 |
| − relation tools | `TOOL_TYPE=node` | +1.8 | -1.5 | +0.8 | +2.0 |
| fuzzy arm only | `RETRIEVAL_LEVENSHTEIN=0` | — | — | — | — |
| lev arm only | `RETRIEVAL_FUZZY=0` | — | — | — | — |
| + vector arm | `RETRIEVAL_VECTOR=1` | — | — | — | — |
| − all correction (escalation, judge, repair, value-snap) | `—` | — | — | — | — |

n: flight_accident 167 · healthcare 398 · pole 391 · terrorist_attack 400

## Paired flips (gained / lost), sign-test p

| variant | flight_accident | healthcare | pole | terrorist_attack |
|---|---|---|---|---|
| − escalation loop | 4/9, p=0.27 | — | — | — |
| − select-or-abstain judge | 5/7, p=0.77 | — | — | — |
| − semantic repair | 4/7, p=0.55 | — | — | — |
| − value-snap | 5/4, p=1 | 10/19, p=0.14 | 7/57, p=7.6e-11 | 22/23, p=1 |
| − relation tools | 5/2, p=0.45 | 14/20, p=0.39 | 11/8, p=0.65 | 27/19, p=0.3 |
| fuzzy arm only | — | — | — | — |
| lev arm only | — | — | — | — |
| + vector arm | — | — | — | — |
| − all correction (escalation, judge, repair, value-snap) | — | — | — | — |

## Per-category Δ EA (points)

**flight_accident** — n per category: casing 15, typo 9, partial 18, abbrev 89, alias 36

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.933 | 0.889 | 0.944 | 0.854 | 0.694 |
| − escalation loop | +0.0 | -11.1 | +5.6 | -4.5 | -2.8 |
| − select-or-abstain judge | +6.7 | +0.0 | +0.0 | -4.5 | +2.8 |
| − semantic repair | +6.7 | -11.1 | -11.1 | -1.1 | +0.0 |
| − value-snap | +0.0 | -11.1 | +0.0 | +0.0 | +5.6 |
| − relation tools | +6.7 | +11.1 | +0.0 | +0.0 | +2.8 |

**healthcare** — n per category: casing 42, typo 72, partial 40, abbrev 123, alias 121

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.833 | 0.806 | 0.800 | 0.715 | 0.545 |
| − value-snap | -4.8 | -2.8 | +0.0 | -2.4 | -1.7 |
| − relation tools | -9.5 | -2.8 | +7.5 | -2.4 | +0.0 |

**pole** — n per category: casing 44, typo 238, partial 75, abbrev 34, alias 0

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.318 | 0.328 | 0.360 | 0.324 | — |
| − value-snap | +0.0 | -17.2 | -4.0 | -17.6 | — |
| − relation tools | +4.5 | +0.0 | +0.0 | +2.9 | — |

**terrorist_attack** — n per category: casing 40, typo 91, partial 90, abbrev 89, alias 90

| variant | casing | typo | partial | abbrev | alias |
|---|---|---|---|---|---|
| CyANCHOR full (EA) | 0.825 | 0.802 | 0.867 | 0.775 | 0.578 |
| − value-snap | +0.0 | +3.3 | -4.4 | -2.2 | +2.2 |
| − relation tools | -2.5 | -2.2 | +3.3 | +5.6 | +3.3 |

## Missing cells for the paper table (3 test graphs × 8 rows)

- − escalation loop: healthcare, pole
- − select-or-abstain judge: healthcare, pole
- − semantic repair: healthcare, pole
- fuzzy arm only: flight_accident, healthcare, pole
- lev arm only: flight_accident, healthcare, pole
- + vector arm: flight_accident, healthcare, pole

15 missing. `+ vector arm` needs per-graph embeddings first (archives have EMBEDDABLE_PROPERTIES=[]). Driver for the rest: `scripts/tuning/run_ablation_fill.py` (add `--with-joint` for the all-correction row).

Detection floor (paired sign test, 80% power, observed 4–8% discordance): ~5–6 points at n=167, ~3.5 at n≈400, ~2.4 pooled over the three test graphs.

## Sources

References: `logs/ablation/fa__full__full_20260823`, `logs/verify_cols/healthcare__full__v400`, `logs/verify_cols/pole__full__v400`, `logs/dev_sweep/ta__full__dev400`. Variants: `logs/ablation`, `logs/verify_cols`, `logs/dev_sweep`, `logs/ablation_fill`. Backbone gpt-4.1, SHARDS=1, errors score 0.
