# gpt-5.6-terra reference runs (September 2026)

The per-question records behind `report/gpt-5.6-terra/CLEAN_VS_PERTURBED.md`,
published here so they survive independently of any one machine. Method
`no_val_link` (no value grounding), generator `gpt-5.6-terra` for every stage,
run on 2026-09-19 at `SHARDS=4`; each `summary.json` carries the full
`run_config`.

* 13 clean runs, `<dataset>__<graph>__no_val_link@gpt-5.6-terra__<stamp>`:
  `cypherbench` (company, fictional_character, flight_accident, geography,
  movie, nba, politics), `mindthequery` (bloom50, covid, er, healthcare, wwc)
  and `zograscope` (pole) — the original benchmarks, 6,294 questions.
* 13 perturbed runs, `<dataset>_augmented__<graph>__no_val_link@gpt-5.6-terra__<stamp>`
  on the same graphs (Mind-the-Query's perturbed graph is named `bloom`):
  4,611 questions, the v2.2 benchmark files. The released v2.3 set is these
  rows minus the 21 listed in `benchmarks/removed_rows.jsonl`; the sweep driver
  and the report scripts drop those rows (`eval_paths.drop_retired`), so every
  perturbed run is complete on v2.3 (4,590 questions).

Each directory holds `records.jsonl` (one line per question: `qid`,
`question`, `gold_cypher`, `pred_cypher`, `ea`, `psjs`, `error`, …) and
`summary.json`. Every run has one record per question; errored questions are
recorded and score 0. Most errors on Mind-the-Query covid are syntax errors in
the generated Cypher (224 of 245 clean, 142 of 156 perturbed), not
infrastructure failures.

Regenerate the table from these runs (the output is byte-identical to the
committed report):

    python scripts/clean_vs_perturbed.py --model gpt-5.6-terra --methods no_val_link

`scripts/audit_runs.py` judges its rule 2 from the local `git reflog`. In the
checkout that made these runs (published artifact set since 2026-09-10 18:29)
it lists the 13 perturbed runs as `keep` and the 13 clean runs as `outside`.
Another checkout can list them as `DELETE`, and `--discard-all` deletes them;
that verdict comes from the other checkout's history, not from these runs.

`logs/ablation_terra.log.gz` and `logs/ablation_terra_nba.log.gz` are the
console logs of the first-generation gpt-5.6-terra component ablation
(2026-09-27/28). Its cells are on the branch
`ablation/gpt-5.6-terra-judge-on-node` under `logs/ablation_gpt-5.6-terra/`.
`logs/judge_failure_modes.log` is the console output of the select-or-abstain
judge failure-mode measurement on those cells (2026-09-28): the per-graph
counts, then a `KeyError` at the summary step; the complete table is
`report/judge_failure_modes.{md,json}` on `main`.

This branch is `main` @ 9e2c8bc plus these files. To copy the runs into
another checkout without switching branches:

    git fetch origin
    git checkout origin/reference/gpt-5.6-terra-2026-09 -- logs/runs
    git reset -q -- logs/runs

The reset un-stages the copied files; `logs/` is ignored, so they stay out of
later commits.

**Re-judged 2026-10-01 (node-set rule, main 2bffefe):** the four pole and bloom run folders
(`zograscope__pole__*`, `zograscope_augmented__pole__*`, `mindthequery__bloom50__*`,
`mindthequery_augmented__bloom__*`) were re-scored with `scripts/rejudge_node_returns.py`; their
records gained `ea_strict` (value comparison alone) and `ea` now also accepts a prediction that
selects exactly the gold nodes when the gold query returns a node. Pooled No Val Link EA moved
from 0.454 to 0.509 on the clean questions and from 0.117 to 0.120 on the perturbed ones
(`report/gpt-5.6-terra/CLEAN_VS_PERTURBED.md` on this branch is regenerated accordingly).
The other 22 folders are unchanged.

**Re-judged 2026-10-03 (full result rows, main 088039b):** all 26 run folders were re-scored with
`scripts/rejudge_full_rows.py`. The `no_val_link` method ends in LangChain's `GraphCypherQAChain`, which
keeps only the first 10 rows of a query's result; these runs were scored on those 10 rows, so a correct
query whose result has more than ten rows counted as wrong. Every record is now scored on the full
result of its stored query (`rows_rule = full-rows-v1`; the old verdict stays in `ea_capped`). Pooled
No Val Link EA moved from 0.509 to 0.629 on the clean questions and from 0.120 to 0.130 on the perturbed
ones (CypherBench clean 0.608 -> 0.737, perturbed 0.094 -> 0.110; Mind-the-Query clean 0.385 -> 0.617,
perturbed 0.246 -> 0.254; ZOGRASCOPE unchanged). One clean covid prediction no longer runs within the
evaluation executor's 30 s timeout and is now recorded as an execution error (it was scored wrong
before). `report/gpt-5.6-terra/CLEAN_VS_PERTURBED.md` on this branch is regenerated accordingly.

