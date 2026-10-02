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

This branch is `main` @ 9e2c8bc plus these files. To copy the runs into
another checkout without switching branches:

    git fetch origin
    git checkout origin/reference/gpt-5.6-terra-2026-09 -- logs/runs
    git reset -q -- logs/runs

The reset un-stages the copied files; `logs/` is ignored, so they stay out of
later commits.
