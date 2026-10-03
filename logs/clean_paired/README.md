# Clean-question runs — gpt-5.6-terra, CypherBench

Runs of **Multi-Agent GraphRAG** and **CyANCHOR** on the *original* wording of the 2,090 perturbed
CypherBench questions, made on 2026-10-02 at commit `108f499` with the released configuration
(the same settings as the sweep cells under `logs/runs/` on this branch). They pair one-to-one with
the perturbed cells: same question ids, same gold queries, only the question text differs.

| what | where |
|---|---|
| the clean questions | `cypherbench_clean_paired.json` — the released `benchmarks/cypherbench_augmented_v2/test.json`, rows unchanged except that `nl` holds `_aug_meta.original_nl` (2,090 rows, ids and `gold_cypher` identical) |
| the runs | `cypherbench_augmented__<graph>__<method>@gpt-5.6-terra__<stamp>/{records.jsonl,summary.json}` — 7 graphs x 2 methods |
| the perturbed counterparts | `logs/runs/cypherbench_augmented__<graph>__<method>@gpt-5.6-terra__*` on this branch |
| No Val Link on the clean questions | not re-run: branch `reference/gpt-5.6-terra-2026-09`, `logs/runs/cypherbench__<graph>__no_val_link@gpt-5.6-terra__20260919-*` (same model preset, prompt path and scoring; pair on `qid`) |

The runs were made through `eval_run` with the dataset key `cypherbench_augmented` pointed at the clean
file (that is why the folder names carry `cypherbench_augmented`), one worker per graph, the sweep's
per-question caps (60 s for the baseline, 900 s for CyANCHOR), under the same credit guard as the sweep.
Every graph has one record per question; no record holds a credit or rate-limit error (one question of
geography x Multi-Agent GraphRAG timed out and scores 0, as in the sweep).

Pairing: `records.jsonl` → `qid` = the perturbed row's `id` = `_source_row.qid`. Each clean question
weighs one; an errored question scores 0. Pooled over the 2,090 pairs (EA, %):

| method | clean | perturbed | change | retained |
|---|---:|---:|---:|---:|
| No Val Link | 60.8 | 9.7 | −51.1 | 15.9% |
| Multi-Agent GraphRAG | 83.5 | 48.5 | −35.0 | 58.1% |
| CyANCHOR | 85.4 | 70.6 | −14.8 | 82.7% |

Per graph and the per-question flips: `report/gpt-5.6-terra/CLEAN_VS_PERTURBED_cypherbench_3methods.md`.
