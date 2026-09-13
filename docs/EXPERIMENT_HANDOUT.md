# Running the perturbed-benchmark experiments — start here

You are running a fixed evaluation harness over three entity-perturbed
text-to-Cypher benchmarks with **one generator LLM assigned to you**. You do
**not** need to understand the method: you set one line in one config file,
run three commands, and the result is a branch in this repository.

Everything below is a checklist. If a step does not print what it says it
should, stop and ask — a run that starts from a bad state produces a
plausible-looking score that is silently wrong, and we cannot tell afterwards.

Depth, troubleshooting and every config knob: [`RUNNING_EXPERIMENTS.md`](RUNNING_EXPERIMENTS.md).

---

## 0. Prerequisites

```bash
git clone <repo> && cd t2c          # main branch — do not check out anything else
python3.12 -m venv venv && source venv/bin/activate   # Python 3.12 exactly — the pins (torch, faiss) have no 3.13 wheels
python --version                    # must say 3.12.x
pip install -r requirements.txt     # pinned to the environment the reference runs used
cp .env.example .env                # then put the keys in (below)
```

- **Neo4j access.** The graphs live on a shared VM whose connection details are
  committed in `eval_config.py`. If your machine is on a corporate VPN the VM
  is usually unreachable — **disconnect the VPN** before running. `UNREACH` in
  the pre-flight means a network problem, not a broken setup. Quick probe:
  `nc -zv 34.9.85.21 15066` must say *succeeded*; if it does not, tell the
  coordinator (the VM firewall may need your IP).
  The same kind of corporate proxy also blocks `pip` wheel downloads
  (`403 MediaTypeBlocked`) — do the `pip install` off-VPN as well.
- **API keys.** `.env` holds keys and nothing else — the model is chosen in
  `eval_config.py` (step 2), never in `.env`. **Everyone needs
  `OPENAI_API_KEY`**, whatever model you run: at run time the tool router
  embeds every mention and the FCAV baseline embeds every question with OpenAI
  `text-embedding-3-small` (and the FCAV value index is built with it). On top
  of that you need the key for the provider of *your* model:

| your model (`GENERATOR_LLM`) | provider | key in `.env` | where a key comes from |
|---|---|---|---|
| everyone (embeddings), and `gpt-5.6-terra` / `gpt-5.6-luna` | OpenAI | `OPENAI_API_KEY` | platform.openai.com → API keys |
| `claude-sonnet-5`, `claude-haiku-4.5` | Anthropic | `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `deepseek-v3.1`, `llama-3.3-70b` | DeepInfra | `DEEPINFRA_API_KEY` | deepinfra.com → Dashboard → API Keys |

  **Ask the coordinator for the lab key before creating your own** — the runs
  are billed centrally and each model has its own key so spend can be tracked.
  Never commit `.env`.
- **Disk:** the `fcav` baseline's value index is ~4 GB per large graph (~40 GB
  for the full suite); the driver builds it on first use (step 3).

## 1. Verify the dataset — do this first, every time you pull

```bash
python benchmarks/verify.py
```

Must print **`VERIFIED — safe to run experiments and pool results.`**

The benchmark itself ships in the repo — `benchmarks/<dataset>_augmented_v2/test.json`
for `cypherbench`, `mindthequery` and `zograscope` — and `eval_run.py` reads it
from there (`eval_config._BENCHMARKS_DIR`, repo-relative). Nothing to download,
nothing to configure.

This is not a formality. The benchmarks are the **v2.2 verified release,
4,611 questions**; earlier checkouts carried the 4,641-row pre-verification
v2.1 set or the 4,875-row pre-curation set, and results from different copies
**cannot be pooled** — nothing downstream will warn you. If it fails:
`git pull`, run it again, and if it still fails, ask before running anything.

## 2. Choose your model — one line in `eval_config.py`

Open `eval_config.py` and, in the boxed **`★ EXPERIMENT PARAMETERS ★`** block
at the top, set the model assigned to you:

```python
GENERATOR_LLM = "gpt-5.6-terra"   # ← exact preset name from the table below
```

**Nothing else.** `METHOD`, `EVAL_PAIRS`, `LIMIT` and `SHARDS` are set by the
sweep driver (step 5); leave every other knob at its committed value — the
defaults are the shipped configuration and every model must run under the
same ones. The value already in the file is the last person's scratch, not a
default.

**The model presets** (`config.MODEL_PRESETS`; the name is what you type and
what appears in every run directory). The six in the sweep:

| preset | what it is | key |
|---|---|---|
| `gpt-5.6-terra` | GPT workhorse (primary model) | `OPENAI_API_KEY` |
| `gpt-5.6-luna` | cheap tier | `OPENAI_API_KEY` |
| `claude-sonnet-5` | Claude strong tier, same price point as Terra (thinking switched off by the harness) | `ANTHROPIC_API_KEY` |
| `claude-haiku-4.5` | cheap tier | `ANTHROPIC_API_KEY` |
| `deepseek-v3.1` | open-weights, strong tier (DeepInfra) | `DEEPINFRA_API_KEY` |
| `llama-3.3-70b` | open-weights baseline (DeepInfra) | `DEEPINFRA_API_KEY` |

Two more exist but are **not** part of the sweep — do not run them unless
asked: `gpt-4.1` (the baseline the reference runs used) and `claude-opus-5`.

One name switches every stage of the pipeline (entity extraction, Cypher
generation, answer formatting). A wrong name fails immediately with the list
of valid ones — it never silently falls back to another model.

## 3. Artifacts — nothing to build, never run setup

The prompts, generated tools, schema files and tool-routing index for every
graph were built **once** by the coordinator and ship in the repo
(`setup_artifacts/`, ~8 MB, pinned file-by-file by
`setup_artifacts/MANIFEST.json`). Everyone evaluates with byte-identical
prompts and tools — that is what makes the six models comparable — so
**never run `scripts/setup_and_archive.py` and never edit anything under
`setup_artifacts/`**; the driver refuses to start on an archive that differs
from the published set.

The one large index (the `fcav` baseline's value index, 3–4 GB per large
graph) is not in git: the driver builds it for each graph on first use (OpenAI
embeddings of the graph's values — cents per graph, minutes on the small
graphs, a few hours on the large ones) and stores it under
`setup_artifacts/<dataset>__<graph>/generated/fcav/`. If the coordinator has
shared a pre-built bundle, unpack it there first and that step is skipped.

## 4. Smoke test — ten minutes, a few cents

```bash
python orchestrate_sweep.py --smoke
```

Runs all **five methods** on the smallest graph (`flight_accident`, 3
questions each) into `logs/smoke/` and prints a 1×5 matrix. It passes when
every method produced its 3 records. A method whose **every** example errored
is a systematic rejection (bad key, unsupported parameter — on 2026-09-11
GPT-5.6 refused every `react` call until the harness was fixed) and the driver
stops with the error text: **send that text to the coordinator, do not work
around it.** A single errored question is fine (see step 5).

The driver runs the pre-flight itself first: every graph's archive is checked
against the live graph and against the published set, and it stops on any ✗:

- `UNREACH` — network problem (VPN, firewall), not a broken setup;
- `CONTAM` — the archive's tools do not match the graph: `git pull`, retry, then ask;
- artifacts `MISMATCH` — your copy differs from `MANIFEST.json` (edited or
  regenerated): `git checkout setup_artifacts/` and retry;
- artifacts `MISSING` — you have not pulled the archives: `git pull`.

(`python verify_setup.py` prints the same table on its own if you want to look
before running anything.)

## 5. The full run — one command, leave it running

```bash
python orchestrate_sweep.py
```

13 graphs × 5 methods for your model, graph by graph. Roughly 50 machine-hours
for the whole suite at the shipped settings; leave it running. Every
`(graph, method)` cell writes its own directory

```
logs/runs/<dataset>__<graph>__<method>@<model>__<YYYYMMDD-HHMMSS>/
    records.jsonl    one line per question
    summary.json     aggregate + the full run configuration
```

and after each graph the driver regenerates `report/<model>/<Dataset>/<graph>.md`,
after each dataset `report/<model>/<Dataset>/_summary.md`, and at the end
**`report/<model>/SWEEP_<YYYYMMDD-HHMMSS>.md`** — one file per run, never
overwritten (`SWEEP.md` is a copy of the latest): the completeness matrix plus
every table the paper needs — EA / PSJS per dataset and overall, by
perturbation strategy, by query difficulty.

**Completeness, not perfection.** A cell is complete when it holds one record
per question (`n` equals the graph's question count). Some questions **will**
error — broken gold queries, the odd timeout — and that is expected: the
evaluation scores an errored question 0 (the denominator is always all
questions) and reports the count in the `err` column. A cell with a few errors
is a result. A missing or truncated cell is not, and the matrix marks it ✗.

**If it stops** (laptop asleep, rate-limit storm, network): run the same
command again. Completion is read from disk, so every complete cell is
skipped and only the missing ones run; a cell that keeps failing is retried
three times, then reported and skipped so the rest of the suite continues.
To re-run a subset on purpose:

```bash
python orchestrate_sweep.py --graphs movie nba       # these graphs, all methods
python orchestrate_sweep.py --methods react          # this method, all graphs
python orchestrate_sweep.py --status                 # matrix + headline numbers, runs nothing
```

The run ends with **COMPLETE** or **INCOMPLETE** and the matrix. Do not
report numbers from an INCOMPLETE sweep.

## 6. Publish — the deliverable is a branch

```bash
python orchestrate_sweep.py --publish
```

Creates the branch **`sweep/<model>`** (e.g. `sweep/gpt-5.6-terra`) from
`main`, commits your model's run directories (`records.jsonl` + `summary.json`
for all 65 cells), `report/<model>/` (the per-graph tables and every
`SWEEP_*.md`), the sweep log and your `eval_config.py`, and pushes it.

Then send the coordinator **two things**:

1. the branch name (`sweep/<model>`), and
2. the results file **`report/<model>/SWEEP.md`** attached to the message — it
   is the completeness matrix plus every table the paper needs (EA / PSJS per
   dataset and overall, by perturbation strategy, by query difficulty). It is
   also in the branch; attaching it just saves a checkout.

That is all we need: the tables are in `report/<model>/`, and the per-question
records let us re-derive anything without re-running.

`--publish` refuses an INCOMPLETE sweep; if the coordinator explicitly accepts
a partial result, `--publish --allow-incomplete`.

Do **not** delete `logs/runs/` afterwards, and do not force-push.

---

## Work split — one person, one model

| model (`GENERATOR_LLM`) | owner | branch |
|---|---|---|
| `gpt-5.6-terra` | | `sweep/gpt-5.6-terra` |
| `gpt-5.6-luna` | | `sweep/gpt-5.6-luna` |
| `claude-sonnet-5` | | `sweep/claude-sonnet-5` |
| `claude-haiku-4.5` | | `sweep/claude-haiku-4.5` |
| `deepseek-v3.1` | | `sweep/deepseek-v3.1` |
| `llama-3.3-70b` | | `sweep/llama-3.3-70b` |

Question counts (v2.2), so you know what `n` must be:

| dataset | graph | questions |
|---|---|--:|
| `cypherbench_augmented` | `movie` | 360 |
| `cypherbench_augmented` | `politics` | 360 |
| `cypherbench_augmented` | `geography` | 331 |
| `cypherbench_augmented` | `fictional_character` | 324 |
| `cypherbench_augmented` | `company` | 305 |
| `cypherbench_augmented` | `nba` | 251 |
| `cypherbench_augmented` | `flight_accident` | 168 |
| `mindthequery_augmented` | `healthcare` | 419 |
| `mindthequery_augmented` | `covid` | 327 |
| `mindthequery_augmented` | `wwc` | 267 |
| `mindthequery_augmented` | `er` | 185 |
| `mindthequery_augmented` | `bloom` | 24 |
| `zograscope_augmented` | `pole` | 1,290 |
| | **total** | **4,611** |

> `bloom50` in `GRAPH_CONNS` is the *same graph* as `bloom` (the dump is named
> `bloom50`; the test data says `bloom`), and `terrorist_attack` is a
> development graph outside the suite. The driver uses the 13 graphs above and
> nothing else.

## Three things that will bite you

1. **Never run `scripts/setup_and_archive.py` or edit anything under
   `setup_artifacts/`.** Results are only poolable if every generator saw the
   same prompts and tools; the driver enforces this against `MANIFEST.json`.
2. **One driver per checkout at a time.** The harness keeps one live copy of
   each graph's artifacts and swaps the right one in before each graph. Two
   drivers in the same checkout corrupt each other's scores without any error.
3. **Read `err` before `EA`.** A few errors per graph are normal. A whole
   method erroring (every question of a graph) is a rejected API call scored
   as zeros — it looks like a terrible model. The smoke test catches this
   before the full run; if it shows up later, stop and send the `error` field
   of one line of that cell's `records.jsonl`.

## Questions

Ask before improvising. A wrong-but-plausible number costs far more than a
delayed one, because we usually cannot tell from the output that it was wrong.
