# gpt-4.1 reference runs (June–July 2026)

The per-question records behind the committed `report/gpt-4.1/` tables and the
MindTheQuery error baseline, published here so they survive independently of
any one machine. Generator `gpt-4.1`; everything else at the shipped defaults
of the time.

* 77 directories named `<dataset>__<graph>__<method>` (no time stamp, no
  `@<model>` tag — the layout before run tagging): the 13-graph × 5-method
  reference sweep on the entity-perturbed benchmarks (`*_augmented`) plus the
  matching runs on the clean graphs (`cypherbench__*`, `mindthequery__*`,
  `zograscope__*`) used for the paired clean-vs-perturbed comparison.
* 8 stamped directories `…__chess_adapted*__2026070[78]-*` and
  `…__cyanchor_skeleton__20260707-*`: the chess-baseline adaptation
  experiments of 2026-07-07/08 on three graphs.

Each directory holds `records.jsonl` (one line per question: `qid`, `question`,
`gold_cypher`, `pred_cypher`, `ea`, `em`, `psjs`, `error`, timings) and, where
the run finished, `summary.json`.

These runs were scored on the pre-verification benchmark files (v2.1,
4,641 rows, and the earlier 4,875-row set), not on the released v2.2 set of
4,611 rows. They are the paper's reference, not a sweep result: they cannot be
pooled with the `sweep/<model>` branches, and the sweep driver marks them
`≠release` on purpose. Do not delete them from a coordinator checkout.

This branch is `main` @ 3962558 plus this directory; the sweep branches
`sweep/<model>` follow the same layout for the v2.2 runs.
