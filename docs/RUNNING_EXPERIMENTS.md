# Evaluation harness — reference for developers and the coordinator

This page says how the harness works and what its knobs mean. It is **not** a
procedure for the model sweep: runners follow
[`EXPERIMENT_HANDOUT.md`](EXPERIMENT_HANDOUT.md) and nothing else. Everything
below is stated from the code (`orchestrate_sweep.py`, `eval_run.py`,
`eval_config.py`, `eval_paths.py`, `eval/artifact_swap.py`,
`scripts/artifact_manifest.py`).

## 1. The pieces

| piece | role |
|---|---|
| `orchestrate_sweep.py` | The sweep driver: one generator model over the 13-graph × 5-method suite, cell-level resume, completeness verdict (COMPLETE / NOT CLEAN), reports, `--publish`. The only path that produces sweep results. |
| `eval_run.py` | Evaluates the pairs in `eval_config.EVAL_PAIRS` with the method in `eval_config.METHOD`, one worker subprocess per pair (or per shard). The driver calls it once per cell after setting those fields itself; you call it directly only for a development run (§3). |
| `eval/_worker.py` | The subprocess: loads the benchmark file, runs the agent per question, writes `records.jsonl` + `summary.json`. |
| `eval_config.py` | The single configuration surface: the ★ block at the top (method, CyANCHOR arms, ablation toggles, run size) and the infrastructure below it (graph registry, benchmark paths, output dirs). There are no environment variables in the normal flow — `eval_run` injects the ★ values into the worker's environment and **overrides** anything set in the shell, so `METHOD=… python eval_run.py` does nothing. |
| `setup_artifacts/` + `MANIFEST.json` | The published per-graph artifact set (§4). |
| `verify_setup.py` | Pre-flight: each archive against its live graph and against the published set (§8). |
| `eval_aggregate.py` | Development view: re-aggregates whatever run dirs are under `OUT_DIR` into per-difficulty / per-strategy tables and writes `logs/runs/report_<stamp>.md`. Not a deliverable; it says so in its output. |
| `gen_ablation_report.py`, `gen_pooled_report.py` | The report renderers the driver calls (per graph, per dataset). |
| `scripts/clean_vs_perturbed.py` | Paired clean-vs-perturbed comparison for one model → `report/<model>/CLEAN_VS_PERTURBED.md` (§6). |
| `scripts/audit_runs.py` | Read-only audit of `logs/runs/`: which run directories the sweep can use and the exact `rm -rf` lines for the ones it cannot (§5). |

## 2. What happens when a cell runs

For each `(dataset, graph)` in `EVAL_PAIRS`, `eval_run.py`:

1. **Swaps in** that graph's archive from `setup_artifacts/<dataset>__<graph>/`
   into the live locations — `agent/prompts.py`, `generated/`, `schema_data/`
   and the `EMBEDDABLE_PROPERTIES` block of `vector_config.py`
   (`eval/artifact_swap.py` holds the list). The live tree is **one shared
   copy**: two evaluations in the same checkout at the same time overwrite each
   other's tools, so never run two drivers, or a driver and an `eval_run.py`,
   in one checkout.
2. **Published-set guard** — compares the archive with
   `setup_artifacts/MANIFEST.json`: `MISMATCH` or `MISSING` → the pair is
   refused; `UNPUBLISHED` (a graph the manifest does not cover) → a warning,
   then the run proceeds. Coordinator-only bypass: `EVAL_SKIP_MANIFEST_GUARD=1`.
3. `METHOD = "fcav"` needs `generated/fcav/` (the value index) in the archive
   and is refused otherwise; the driver builds the index on first use.
4. **Graph-identity guard** — asks the database whether the live node tools
   search labels that actually exist in this graph. A mismatch means a
   contaminated archive and fails the pair loudly; without the guard such a
   run would score near the no-value-linking floor with no error. Bypass:
   `EVAL_SKIP_GRAPH_GUARD=1`.
5. Launches the worker with the ★ values injected. With `SHARDS > 1` the
   graph's questions are split across that many workers and the records merged.
6. Writes a fresh run directory (§5) and stamps `summary.json` with the full
   `run_config`.

**Timeouts.** The worker enforces a per-question cap
(`EVAL_PER_EXAMPLE_TIMEOUT`, default 60 s; the driver sets 900 s for CyANCHOR,
whose slowest legitimate questions take 70–120 s); a question over the cap is
recorded as an error (`example timeout …`) and scores 0. `eval_run` also kills a
worker that exceeds *n × (cap + 5 s) + 120 s* (4 h when `LIMIT` is unset), or
`EVAL_WORKER_TIMEOUT_SEC` if set.

## 3. Developer run on one pair (not the sweep)

`eval_run.py` is the right tool for developing the agent: one graph, one
method, a handful of questions.

```bash
# eval_config.py — the ★ block and EVAL_PAIRS:
#   EVAL_PAIRS = [("cypherbench_augmented", "movie")]
#   METHOD     = "cyanchor"        # no_val_link | fcav | react | graphrag | cyanchor
#   LIMIT      = 20                # None = every question
python verify_setup.py             # pre-flight for EVAL_PAIRS (§8); --suite for the 13 sweep pairs
python eval_run.py
python eval_aggregate.py           # development table over everything under OUT_DIR
git checkout eval_config.py        # EVAL_PAIRS / METHOD / LIMIT / SHARDS are per-run scratch — never commit them
```

Two consequences of "newest run wins" (§5):

- A development run on a **suite pair** with the sweep's `GENERATOR_LLM`
  becomes that cell's newest run. If it was partial (`LIMIT`), the driver's
  `--status` then shows the cell as truncated (✗) and the next
  `orchestrate_sweep.py` re-runs it in full. For scratch work use another
  `OUT_DIR`, another model, or a graph outside the suite —
  `("cypherbench", "terrorist_attack")` and the clean (non-`_augmented`) graphs
  are in `GRAPH_CONNS` for exactly this.
- Everything under `OUT_DIR` is a candidate for `eval_aggregate.py`'s table;
  that table mixes whatever is there and is never a result.

The suite the driver runs is `eval_config.FULL_EVAL_PAIRS_13_AUGMENTED`
(question counts: `EXPERIMENT_HANDOUT.md`, "Question counts"); `bloom` and
`bloom50` are the same Mind-the-Query graph (`bloom50` is the dump name, `bloom`
the test-data name).

## 4. The published artifact set (coordinator only)

Results are poolable across models only if every model saw byte-identical
prompts and tools, so the model-independent artifacts of every suite graph are
built once and committed under `setup_artifacts/<dataset>__<graph>/`:
`agent/`, `schema_data/`, `generated/generated_node_tools.py`,
`generated/generated_rel_tools.py`, `generated/tool_descriptions.csv`,
`generated/faiss/` and `vector_config.embeddable_properties.snippet` (the
`.gitignore` whitelist). `setup_artifacts/MANIFEST.json` pins one sha256 per
file and carries a `set_id`. `generated/fcav/` (the FCAV value index, GBs per
large graph) never enters git: the driver builds it on first use, or the
coordinator shares it out of band.

`scripts/setup_and_archive.py` refuses to rebuild a published pair — a runner
who hits `MISMATCH` restores the published copy with `git checkout
setup_artifacts/`. Re-publishing a pair on purpose:

```bash
# eval_config.py: EVAL_PAIRS = [the pair]
python scripts/setup_and_archive.py --republish     # rebuild + archive (refuses without the flag)
python setup_fcav.py                                # FCAV value index into the archive (not in the manifest)
python scripts/artifact_manifest.py build --strict  # rewrite MANIFEST.json; fails if a pair trips the identity gate
git add setup_artifacts && git commit -m "artifacts: publish <graphs>" && git push
python scripts/artifact_manifest.py check --all     # every published pair: OK / MISMATCH / MISSING / UNPUBLISHED
```

`eval_run.py` has enforced the published set since 2026-09-10 (`be36c26`).
Run directories do not record the set id, so a run made on an older checkout
cannot be verified after the fact — a run's provenance is the checkout it was
made on.

## 5. Where results land

```
logs/runs/<dataset>__<graph>__<method_seg>@<model>__<YYYYMMDD-HHMMSS>/
    records.jsonl    one line per question: gold and generated Cypher, ea, psjs, error, strategy, difficulty
    summary.json     aggregate + run_config (stamp, dataset, graph, method, LLM per stage,
                     embedding backend, every ★ knob, shards, limit) + run_meta
```

- `method_seg` is the method plus CyANCHOR's active retrieval arms:
  `cyanchor_fl` = fuzzy + Levenshtein (the shipped default), `cyanchor_fvl` =
  vector arm on. `<model>` is `GENERATOR_LLM` with unsafe characters replaced.
- **Newest wins.** Readers (`eval_paths.latest_run_dir`) take the lexically
  newest stamp *for the model the process is configured for*; a directory from
  before model tagging (no `@` segment) counts only if its `run_meta` names that
  model. Re-running never deletes anything.
- `SHARDS` (`eval_config.py`) is intra-graph parallelism. The driver forces
  `SHARDS = 1` for CyANCHOR: rate-limit back-off trips the per-question cap and
  those timeouts score 0.
- `--smoke` writes to `logs/smoke/` and keeps its own state file
  (`logs/sweep_<model>_smoke.json`); the full run's state is
  `logs/sweep_<model>.json`, its log `logs/sweep_<model>.log`.

**Which runs count, and deleting the ones that cannot.** Per cell the driver
uses the newest run directory of the configured model, and accepts it only if
it holds one record per question **and** every record was scored on the
released benchmark rows — its `qid` is a release id of that graph and its
`question` is the release text. A run made on an older copy of the benchmark
(rows removed or rewritten since) shows `≠release` in the matrix, counts as ✗
and is re-run. What the driver cannot see is which artifacts a run used:
nothing in a run directory records the artifact set, so on that axis a run is
trusted only if it was made from a checkout that already enforced the published
set (`be36c26`, 2026-09-10). `python scripts/audit_runs.py` applies both rules
to every directory under `logs/runs/` for one model (`--all-models` for all) —
the second by reading `git reflog` for the first moment this checkout contained
`be36c26` — and prints a verdict per directory plus the `rm -rf` lines for the
ones to delete; it never deletes anything itself, and with no reflog evidence
it says `CHECK` rather than guessing. Its other mode, `--discard-all`, is the
clean slate the coordinator prescribes for runs made under the old procedure:
it lists every run directory of the model (suite, clean and development
graphs alike), the driver's state files and old `logs/runs/report_*.md`, and
deletes them after the runner types the model name (`--yes` for scripts).
Everything else can stay: a run
superseded by a newer one is never published (only the newest per cell is
mirrored); a truncated newest run is simply re-run (delete it only to fall back
to an older complete run, which the audit names); `logs/runs/report_*.md` from
`eval_aggregate.py` is ignored; `logs/sweep_<model>.json` holds the automatic
⚠ re-run budgets and can be deleted to reset them — completeness is always
read from the run directories, never from that file.

```bash
python scripts/audit_runs.py --model gpt-5.6-luna                 # verdict per run dir of that model; prints rm -rf lines for the unusable ones
python scripts/audit_runs.py --all-models                         # the same for every model's run dirs
python scripts/audit_runs.py --discard-all --model gpt-5.6-luna   # clean slate: every run dir of that model + its state files, after you type the name
```

The model must be a preset name (`config.MODEL_PRESETS`); the script refuses
anything else and lists the presets. `EXPERIMENT_HANDOUT.md` (the box at the
top) has the `--discard-all` line ready for each of the seven sweep models.

## 6. Reports

The driver regenerates, in place: `report/<model>/<Dataset>/<graph>.md` after
each graph (`gen_ablation_report.py`), `report/<model>/<Dataset>/_summary.md`
after each dataset (`gen_pooled_report.py`), and `report/<model>/SWEEP.md` —
completeness matrix, errors by kind, headline EA / PSJS, breakdowns by
perturbation strategy and by query difficulty — at the end of every run and on
every `--status` / `--publish`. History is not kept in stamped copies: every
`--publish` is a commit on `sweep/<model>`, and `logs/sweep_<model>.log` gets
one verdict line per driver invocation.

Pooling arithmetic: every question weighs one; an errored question scores 0 on
EA and PSJS; `err` counts records whose `ea` is null. Errors are classified by
their text — `gold` (the benchmark's own gold Cypher failed), `agent` (the
model's Cypher failed), `infra` (timeout / API / rate limit — never evaluated),
`other` — and a complete cell dominated by `infra` errors is marked ⚠, re-run
automatically at most twice, and blocks `--publish` unless
`--allow-incomplete` (details: the driver's module docstring).

`report/gpt-4.1/` holds the committed reference tables.

Clean vs perturbed for one model:

```bash
python scripts/clean_vs_perturbed.py --model gpt-5.6-terra [--methods no_val_link cyanchor]
```

pairs every perturbed question with its clean original (the perturbed set is a
subset of the clean one) and scores both runs on exactly those pairs, reading
the newest run per (pair, method, model) for both the bare and the
`_augmented` dataset names; it writes `report/<model>/CLEAN_VS_PERTURBED.md`.
The clean runs are made with `eval_run.py` on the bare graph names
(`cypherbench/<graph>`, `mindthequery/bloom50`, `zograscope/pole`).

## 7. The generator model

`eval_config.GENERATOR_LLM` names a preset from `config.MODEL_PRESETS`; it
selects the LLM for all three stages (entity extraction, Cypher generation,
answer formatting), tags every run directory, and is recorded in
`summary.json`. An unknown name fails at once with the list of valid presets,
and `orchestrate_sweep.py` refuses to start while the value is still the one
committed on `main` — nobody has chosen a model on that checkout (a fresh clone,
or `git checkout eval_config.py` after a pull); `--committed-model` runs the
committed value on purpose (the coordinator's reference runs).
The presets in the sweep, and which key each needs in `.env`, are in
`EXPERIMENT_HANDOUT.md` §0 and §2.

## 8. Pre-flight words and what to do

`python verify_setup.py` checks every pair in `EVAL_PAIRS`; `--suite` checks
the 13 sweep pairs (`FULL_EVAL_PAIRS_13_AUGMENTED`); `--all` checks every pair
in `GRAPH_CONNS`; `--live` checks the live tree instead of the archives. The driver runs the same checks for the whole suite before a run.

| word | meaning | do |
|---|---|---|
| `UNREACH` | the graph's Neo4j is not reachable (usually a corporate VPN) | disconnect the VPN; `nc -zv 34.9.85.21 15066` must succeed |
| `CONTAM` | the archive's node tools search labels that have no nodes in this graph | runner: `git checkout setup_artifacts/ && git pull`; coordinator: §4 |
| artifacts `MISMATCH` | your copy of the archive differs from `MANIFEST.json` | `git checkout setup_artifacts/` |
| artifacts `MISSING` | the archive is not on disk | `git pull` |
| artifacts `UNPUBLISHED` | a graph outside the published set (development graphs) | expected for those graphs only |

A whole method erroring on every question of a graph is a rejected API call
(bad key, unsupported parameter), not a bad model — the smoke test is there to
catch it before the full run.
