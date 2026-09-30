# Select-or-abstain judge on the full pole graph — result

Date: 2026-09-29 · Backbone: gpt-5.6-terra · Graph: pole (ZOGRASCOPE), all 1,283 questions of release v2.3.
These are the two cells of the handoff's short plan (§5.5, pole in full): the judge-on reference and
`no_select_judge`. Configuration of both: CyANCHOR, node-property tools only, fuzzy + Levenshtein arms,
escalation loop, semantic repair and value-snap on, temperature 0. They differ only in PLAN_EXEC_SELECT_JUDGE.

| | judge on (`pole_full__reference`) | judge off (`pole_full__no_select_judge`) | difference |
|---|---:|---:|---:|
| EA | 34.1% | 33.4% | +0.6 points |
| PSJS | 0.436 | 0.429 | +0.007 |

Paired per question: the judge helped 49 questions and hurt 41 (7.0% discordant),
two-sided sign test p = 0.46. No effect detected.

By perturbation strategy (judge helped / hurt, p): typo 30/23, 0.41 · partial 7/11, 0.48 ·
casing 4/4, 1.0 · abbrev 8/3, 0.23.

Decision (2026-09-29): the judge is off in the released configuration (as committed on main since
f04a37c) and is dropped from the paper. The judge-off cell is also the reference of the
released-configuration ablation (`logs/ablation_gpt-5.6-terra__judge-off-node/pole_full__reference`,
byte-identical, not duplicated here).

## Files on this branch

| path | content |
|---|---|
| `pole_full__reference/` | judge on: `records.jsonl` (1,283 questions, 0 errors) + `summary.json` |
| `pole_full__no_select_judge/` | judge off: `records.jsonl` (1,283 questions, 0 errors) + `summary.json` |
| `parts/judge_on/`, `parts/judge_off/` | the two raw runs each cell was merged from (see Provenance) |
| `parts/scripts/run_pole_remainder.py` | runs the not-yet-run questions of one arm with the driver's exact switches |
| `parts/scripts/final_judge_score.py` | merges the parts, checks them against the release, scores |
| `../ablation_terra_judge-on-node_pole_*.log.gz` | driver / worker logs of the four runs |
| `report/ablation_table_gpt-5.6-terra__judge-on-node-polefull.md` | `score_ablation.py --model gpt-5.6-terra --ref judge-on --pole-full` |

The paper-table outputs (`--paper`, Markdown and .tex) were not produced: the judge is not in the paper.

## Provenance

Each cell was run in two parts, because the worker limit of that day (a flat 4 h, replaced on main in
542d7e4) stopped the first part. Every question ran exactly once, with identical switches and model in both
parts; the parts were merged by question id and checked against the release (no duplicate, none missing,
question text verbatim). Part 1 carries no `summary.json` because its worker was stopped.

| cell | part 1 | part 2 |
|---|---|---|
| judge on | `parts/judge_on/…__20260929-130139`, questions 1–1,092 | `parts/judge_on/…__20260929-170433`, questions 1,093–1,283 |
| judge off | `parts/judge_off/…__20260929-130145`, questions 1–1,171 | `parts/judge_off/…__20260929-170433`, questions 1,172–1,283 |

Code at run time: 102db5a (the base of this branch). Part 1 was started by
`scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on --pole-full --graphs pole --variants <cell>`,
the two cells in parallel from two checkouts on the same machine; part 2 by `parts/scripts/run_pole_remainder.py`.
