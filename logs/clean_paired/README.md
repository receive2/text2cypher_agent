# Clean-question runs — gpt-5.6-terra, all three benchmarks

Runs of **MA GraphRAG** (Multi-Agent GraphRAG) and **CyANCHOR** on the *original* wording of the perturbed
questions of all three benchmarks: CypherBench (2,090 questions, run 2026-10-02) and Mind-the-Query (1,217) and
ZOGRASCOPE pole (1,283) (run 2026-10-03), at commit `108f499` with the released configuration (the same settings
as the sweep cells under `logs/runs/` on this branch). They pair one-to-one with the perturbed cells: same
question ids, same gold queries, only the question text differs.

| what | where |
|---|---|
| the clean questions | `<benchmark>_clean_paired.json` for `cypherbench`, `mindthequery`, `zograscope`: the released `benchmarks/<benchmark>_augmented_v2/test.json`, rows unchanged except that `nl` holds `_aug_meta.original_nl` (2,090 / 1,217 / 1,283 rows; ids and `gold_cypher` identical) |
| the runs | `<dataset>__<graph>__<method>@gpt-5.6-terra__<stamp>/{records.jsonl,summary.json}`: 13 graphs x 2 methods |
| the perturbed counterparts | `logs/runs/<dataset>__<graph>__<method>@gpt-5.6-terra__*` on this branch |
| No Val Link on the clean questions | not re-run: branch `reference/gpt-5.6-terra-2026-09` @ `dc8f5cc`, runs of 2026-09-19 `logs/runs/{cypherbench,mindthequery,zograscope}__<graph>__no_val_link@gpt-5.6-terra__20260919-*` (bloom is `bloom50`), same model preset, prompt path and scoring; pole and bloom re-judged with the node-set rule (`9e392f1`) and every verdict scored on the full result of its query (`dc8f5cc`, `eval/full_rows.py`), like the perturbed No Val Link cells on this branch |

The runs were made through `eval_run` with the dataset key (`cypherbench_augmented`, `mindthequery_augmented`,
`zograscope_augmented`) pointed at the clean file (that is why the folder names carry `_augmented`), one worker
per graph, the sweep's per-question caps (60 s for the baseline, 900 s for CyANCHOR), under the same credit
guard as the sweep. Every graph has one record per question; no record holds a credit, rate-limit or
infrastructure error. Errors that remain: one question of geography x MA GraphRAG timed out, and 71
Mind-the-Query gold queries fail to execute (covid 52, wwc 12, healthcare 4, er 3, syntax errors inherited
from the source benchmark); they fail on the same questions in the perturbed cells, so they score 0 on both
sides. The new pole and bloom records were scored with the node-set rule by the evaluator itself (`ea_strict`
present); MA GraphRAG and CyANCHOR execute their own queries, so the 10-row cap of the chain path never applied
to them.

Pairing: CypherBench and ZOGRASCOPE by `qid` (the perturbed row's `id`); Mind-the-Query by (graph, `qid`),
and with the No Val Link reference runs by `_source_row.unique_id`. Each question weighs one; an errored
question scores 0. EA (%), clean -> perturbed (share of the clean accuracy retained):

| benchmark | n | No Val Link | MA GraphRAG | CyANCHOR |
|---|---:|---|---|---|
| CypherBench | 2,090 | 73.7 -> 11.2 (15.2%) | 83.5 -> 48.5 (58.1%) | 85.4 -> 70.6 (82.7%) |
| Mind-the-Query | 1,217 | 61.7 -> 25.8 (41.8%) | 69.5 -> 60.0 (86.3%) | 68.1 -> 61.5 (90.3%) |
| ZOGRASCOPE (pole) | 1,283 | 46.5 -> 4.8 (10.4%) | 62.5 -> 43.6 (69.8%) | 61.5 -> 56.8 (92.4%) |
| **all** | **4,590** | **62.9 -> 13.3 (21.1%)** | **73.9 -> 50.2 (67.9%)** | **74.1 -> 64.4 (86.8%)** |

PSJS (%) over all 4,590: No Val Link 65.8 -> 14.3, MA GraphRAG 76.0 -> 54.0, CyANCHOR 76.3 -> 67.0.
CyANCHOR loses fewer points than MA GraphRAG (paired Wilcoxon signed-rank test on the per-question drops):
all 4,590 p = 2.4e-63 (PSJS 9.3e-74); CypherBench p = 5.7e-51; Mind-the-Query p = 0.014 (PSJS 0.12, not
significant); pole p = 7.2e-18.

Per graph (EA %, clean -> perturbed):

| benchmark | graph | n | No Val Link | MA GraphRAG | CyANCHOR |
|---|---|---:|---|---|---|
| CypherBench | company | 303 | 74.3 -> 13.5 | 85.8 -> 51.8 | 87.5 -> 72.3 |
| | fictional_character | 322 | 61.2 -> 9.0 | 83.5 -> 42.5 | 86.6 -> 68.3 |
| | flight_accident | 168 | 87.5 -> 19.0 | 94.6 -> 63.7 | 94.0 -> 88.7 |
| | geography | 331 | 71.6 -> 11.8 | 75.2 -> 43.5 | 84.3 -> 71.0 |
| | movie | 359 | 66.6 -> 6.4 | 79.9 -> 41.5 | 83.0 -> 64.6 |
| | nba | 251 | 77.7 -> 9.2 | 82.1 -> 61.8 | 80.9 -> 77.7 |
| | politics | 356 | 84.6 -> 13.5 | 88.5 -> 46.1 | 85.1 -> 63.5 |
| Mind-the-Query | bloom | 24 | 91.7 -> 25.0 | 95.8 -> 70.8 | 91.7 -> 75.0 |
| | covid | 326 | 30.4 -> 2.5 | 52.5 -> 43.9 | 50.3 -> 46.6 |
| | er | 184 | 70.7 -> 29.9 | 75.0 -> 72.3 | 75.0 -> 74.5 |
| | healthcare | 418 | 81.6 -> 50.2 | 86.1 -> 71.1 | 85.4 -> 70.8 |
| | wwc | 265 | 60.0 -> 13.2 | 58.1 -> 52.8 | 55.8 -> 55.1 |
| ZOGRASCOPE | pole | 1,283 | 46.5 -> 4.8 | 62.5 -> 43.6 | 61.5 -> 56.8 |

CypherBench alone, with the per-question flips: `report/gpt-5.6-terra/CLEAN_VS_PERTURBED_cypherbench_3methods.md`.
