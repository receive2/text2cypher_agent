# Running the perturbed-benchmark experiments — start here

You are running a fixed evaluation harness over three entity-perturbed
text-to-Cypher benchmarks. You do **not** need to understand the method: you
pick a slice, run four commands, and send back the output directory.

Everything below is a checklist. If a step does not print what it says it
should, stop and ask — a run that starts from a bad state produces a
plausible-looking score that is silently wrong, and we cannot tell afterwards.

Depth, troubleshooting and every config knob: [`RUNNING_EXPERIMENTS.md`](RUNNING_EXPERIMENTS.md).

---

## 0. Prerequisites

- Python env with the repo's dependencies installed.
- **Neo4j access.** The graphs live on a shared VM. If your machine is on a
  corporate VPN, the VM is usually unreachable — **disconnect the VPN** before
  running. `UNREACH` in the pre-flight means a network problem, not a broken
  setup.
- An LLM API key configured as the repo expects.

```bash
git clone <repo> && cd t2c
git checkout dataset-curation-v2.1     # the branch these experiments run on
```

## 1. Verify the dataset — do this first, every time you pull

```bash
python benchmarks/verify.py
```

Must print **`VERIFIED — safe to run experiments and pool results.`**

This is not a formality. The benchmarks are the **v2.2 verified release,
4,611 questions** (the v2.1 freeze after applying the human-verification
verdicts); earlier checkouts carried the 4,641-row pre-verification v2.1 set or
the 4,875-row pre-curation set. Results from different copies **cannot be
pooled**, and nothing downstream will warn you. If it fails: `git pull`, run it again, and if it still fails, ask before
running anything.

## 2. Choose your slice — edit `eval_config.py`

Open `eval_config.py` and edit the boxed **`★ EXPERIMENT PARAMETERS ★`** block
at the top plus `EVAL_PAIRS` just below it:

```python
EVAL_PAIRS = [("cypherbench_augmented", "movie")]   # your assigned graph(s)
METHOD     = "cyanchor"                             # one of the five, see below
SHARDS     = 1                                      # keep 1 for cyanchor
LIMIT      = None                                   # None = all examples
```

**The values already in the file are the last person's scratch, not a default.**
Set them to your own slice. When you are done, `git checkout eval_config.py` —
do not commit these edits.

**The five methods** (run each one separately; results land in separate
directories, nothing is overwritten):

| `METHOD` | what it is |
|---|---|
| `no_val_link` | no grounding (floor) |
| `fcav` | retrieve-then-generate baseline |
| `react` | ReAct NER-agent baseline |
| `graphrag` | Multi-Agent GraphRAG baseline |
| `cyanchor` | our method |

Leave every other knob alone unless you were told otherwise — the defaults are
the shipped configuration.

> ⚠️ **`SHARDS = 1` for `cyanchor`.** It is the most LLM-call-heavy method;
> sharding it raises peak concurrency past provider rate limits and the
> resulting per-example timeouts are scored as failures, which silently
> understates it. The other four methods can use higher `SHARDS`.

## 3. One-time setup for each graph you were assigned

```bash
python scripts/setup_and_archive.py    # no arguments — it reads EVAL_PAIRS
python setup_fcav.py                   # only if you will run the fcav method
```

Both read `EVAL_PAIRS`, so set that first. Positional arguments are
deliberately rejected, so the CLI and the config can never disagree.

## 4. Pre-flight — must be green

```bash
python verify_setup.py
```

Every line must be green. A red line means that graph's artifacts do not match
the graph, and evaluating it would produce a near-zero score that looks like a
real result. Fix it (step 3, with `EVAL_PAIRS` shrunk to that pair) before
continuing.

## 5. Run

```bash
python eval_run.py        # one run per METHOD; re-edit METHOD and repeat
python eval_aggregate.py  # prints the summary table
```

Results land in a fresh timestamped directory per run:

```
logs/runs/<dataset>__<graph>__<method>__<YYYYMMDD-HHMMSS>/
    records.jsonl    one line per example  ← this is what we need back
    summary.json     aggregate + full run configuration
```

`<method>` in the directory name is `no_val_link` / `fcav` / `react` /
`graphrag`, and for our method `cyanchor_fl` (the active retrieval arms are part
of the name, so arm ablations never overwrite each other).

## 6. Send back

Send the whole `logs/runs/` directory (or just the run dirs you produced),
zipped. **`records.jsonl` is the important file** — it holds one record per
example, which lets us re-derive every table without re-running anything.

Also tell us: which graphs and methods you ran, and anything that looked odd
(hangs, rate-limit errors, red pre-flight lines you worked around).

Do **not** delete run directories that errored — a failed run is diagnostic.

---

## Work split

Setup is per-graph, so the natural unit of work is a **graph**: take a graph,
run all five methods on it. These 13 pairs are the full evaluation suite
(`_FULL_EVAL_PAIRS_13` in `eval_config.py`); question counts are v2.1:

| dataset | graph | questions | assigned to |
|---|---|--:|---|
| `cypherbench_augmented` | `movie` | 360 | |
| `cypherbench_augmented` | `politics` | 360 | |
| `cypherbench_augmented` | `geography` | 331 | |
| `cypherbench_augmented` | `fictional_character` | 324 | |
| `cypherbench_augmented` | `company` | 305 | |
| `cypherbench_augmented` | `nba` | 251 | |
| `cypherbench_augmented` | `flight_accident` | 168 | |
| `mindthequery_augmented` | `healthcare` | 419 | |
| `mindthequery_augmented` | `covid` | 327 | |
| `mindthequery_augmented` | `wwc` | 267 | |
| `mindthequery_augmented` | `er` | 185 | |
| `mindthequery_augmented` | `bloom` | 24 | |
| `zograscope_augmented` | `pole` | 1,290 | |
| | **total** | **4,611** | |

> `zograscope/pole` is one graph but 28% of the benchmark — budget for it, or
> split it by running with different `LIMIT`/shard settings and telling us how
> you split it.

> **Two names in `GRAPH_CONNS` that are not rows in this table.**
> `terrorist_attack` is a train-split graph kept for development and tuning —
> it is deliberately outside the 13-graph evaluation suite and has no perturbed
> questions. `bloom50` is the *same graph* as `bloom` (same connection; the
> dump is named `bloom50`, the test data's `graph` field says `bloom`) — for
> the perturbed set always use **`bloom`**.

Each graph × 5 methods. Every run writes its own directory, so two people never
overwrite each other **as long as they are on different machines**.

## Two things that will bite you

1. **One `eval_run.py` per machine/checkout at a time.** The harness keeps one
   live copy of each graph's artifacts and swaps the right one in before each
   pair. Two concurrent runs on the same checkout corrupt each other's scores
   without any error. Use `SHARDS` for parallelism inside a graph; use separate
   machines or separate checkouts for parallelism across people.
2. **Don't trust a low score.** If the grounding methods (`react`, `cyanchor`)
   collapse to roughly the `no_val_link` score while `fcav` still looks normal,
   that is the signature of contaminated artifacts, not a real result. Re-run
   `verify_setup.py`.

## Questions

Ask before improvising. A wrong-but-plausible number costs far more than a
delayed one, because we usually cannot tell from the output that it was wrong.
