# Gold-error audit (broken golds are a dataset job, not an eval job)

## Principle

The eval harness is **assumption-free about dataset quality**. A gold cypher that
fails to execute is scored exactly like any other failure: it counts as **0** and
stays in the denominator (`eval/difficulty.py`). The harness never decides "this
gold is broken, skip it" — that judgement, and any fix/removal, belongs to the
**dataset audit**. This keeps the metric honest and reproducible: numbers depend
only on what ran, not on eval-time opinions about the benchmark.

Consequence: if a benchmark ships golds that don't run on our Neo4j, every method
is (correctly) penalised on those examples. To recover them you fix the
**dataset**, not the eval code. Once a broken gold is fixed or removed from the
dataset source, that example re-scores (or disappears) on the next run — with no
change to the harness.

## What is a "gold error"?

When the harness scores an example it executes both the predicted cypher and the
**gold** cypher. If the gold cypher throws, the record is tagged
`error="gold: …"` (vs `agent: …` for the model's own query). Gold execution is
method-independent, so the same example errors identically under every method.

## The tool: `audit_gold_errors.py`

Read-only. Scans the per-run record dirs (`logs/runs/<dataset>__<graph>__<method>/
records.jsonl`), collects every `error="gold: …"` record, de-dupes by
`(dataset, graph, qid)`, and writes a list for the audit team. It **never** edits
the dataset or the metrics.

```bash
python audit_gold_errors.py                 # scan logs/runs → audit/gold_errors.jsonl + summary
python audit_gold_errors.py --csv           # also write audit/gold_errors.csv
python audit_gold_errors.py --graph covid   # filter to one graph
python audit_gold_errors.py --runs-root logs/runs --out audit/gold_errors.jsonl
```

Output per broken gold: `dataset, graph, qid, category, error, gold_cypher,
question, seen_in_methods`. Plus a stdout summary (counts by graph + by category).

The `category` is a **heuristic triage** — verify before acting:

| category | meaning | likely action |
|---|---|---|
| `undefined variable (genuine gold bug)` | references an unbound variable | genuine defect → fix or remove |
| `type error (genuine gold bug)` | e.g. AVG over a non-numeric | genuine defect → fix or remove |
| `deprecated function / version (dialect)` | e.g. `distance()` → `point.distance()` | **transpile** to our Neo4j dialect, re-verify → usually recoverable |
| `datetime parse (dialect/format)` | gold datetime literal our Neo4j can't parse | fix the literal format → usually recoverable |
| `missing function/procedure (version/APOC)` | e.g. `duration.seconds`, missing APOC | install/transpile → maybe recoverable |
| `other syntax error (mixed)` | bad arg count, `COUNT` subquery syntax, … | inspect — bug vs Neo4j 4→5 dialect |
| `missing property / label (possibly schema)` | gold references a label/prop not present | check the graph is the right one first |
| `timeout (likely OUR env)` | gold ran too long for the cap | **not the gold** — raise the timeout, re-run |

> Note `missing label/property` and `timeout` may be **our environment**, not the
> gold. Rule those out before blaming the dataset.

## Step-by-step: fixing / removing broken golds (dataset audit)

The goal is to make the dataset's golds executable on the deployed Neo4j, or to
remove the unsalvageable ones — **all edits happen in the dataset source files**,
never in eval code.

**1. Produce the list.**

```bash
python audit_gold_errors.py --csv
```

Open `audit/gold_errors.csv` (or `.jsonl`). Work graph by graph.

**2. Triage each entry by category.**

- **`timeout` / `missing label / missing property`** → suspect **our setup**, not
  the gold. Confirm the right graph is loaded (`python verify_setup.py`) and the
  per-example timeout is adequate; re-run that graph and re-audit before touching
  the dataset.
- **Dialect/version** (`deprecated function`, `datetime parse`, `missing
  function`) → the gold was likely valid on the authors' Neo4j. **Transpile** it
  to our deployed dialect and test it manually against the live graph, e.g.:
  - `distance(a, b)` → `point.distance(a, b)`
  - `datetime('2020-04-20T00:00:00 UTC')` → a parseable literal (drop/convert ` UTC`)
  - `duration.seconds(...)` → the APOC/5.x equivalent (or install APOC)
  Run the transpiled gold in Neo4j Browser / cypher-shell. If it now returns rows,
  it is **recoverable** — go to step 3a. If it still fails, treat as a genuine bug
  (step 3b).
- **Genuine bug** (`undefined variable`, `type error`, true malformed syntax) →
  step 3b.

**3. Edit the DATASET SOURCE (not eval).** The augmented test files are at the
paths configured in `eval_config.py`:
`CYPHERBENCH_AUGMENTED_PATH`, `MINDTHEQUERY_AUGMENTED_PATH`,
`ZOGRASCOPE_AUGMENTED_PATH` (the JSON/CSV the harness loads). Locate the example
by `qid` and edit its gold field (`gold_cypher` / `Cypher` / `mr`, per dataset).

- **3a. Recoverable** → replace the gold with the working transpiled query. Keep
  the example. (Preferred — you keep the question.)
- **3b. Unsalvageable** → either hand-write a correct gold for the question if the
  question is sound, or **remove the example** from the source file if the
  question itself is bad. Removing is legitimate (a benchmark item with no valid
  ground truth tests nothing) — but record it (step 5).

**4. Re-run and confirm.** Re-evaluate the affected graph(s) — `python orchestrate_sweep.py --graphs <graph>`
for a sweep model, `eval_run.py` for a development run — then re-audit:

```bash
python audit_gold_errors.py --graph <graph>
```

The count for that graph should drop toward 0. Regenerate the report; EA will rise
naturally for the recovered/removed examples — **with no change to the eval code**.

**5. Record it (reviewer transparency).** Log every fixed/removed `qid` and the
reason in the datasheet ([DATASHEET.md](DATASHEET.md)): how many golds were broken, how many
transpiled vs removed, and why. Dataset-track reviewers will expect this; silent
removal of inconvenient examples is not defensible, documented curation is.

## Current snapshot (for reference)

On the released v2.2 benchmark, executing every gold query against the
deployed graphs (`scripts/tuning/probe_empty_gold.py`, 2026-09-12;
`report/empty_gold_rates.md`) finds **36** golds that do not execute, all in
Mind-the-Query (covid 17, wwc 12, healthcare 4, er 3); CypherBench and
ZOGRASCOPE have **0**. These golds are kept as shipped and score 0 for every
method (the denominator is always all questions), so they lower every
method equally and do not affect the comparison; the count is reported with
the results.

## See also

- [RUNNING_EXPERIMENTS.md](RUNNING_EXPERIMENTS.md) — how to run the eval.
- [DATASHEET.md](DATASHEET.md) — where to record curation decisions.
- `eval/difficulty.py` — the assumption-free metric aggregator (denominator = all
  examples; every error scores 0).
