# Running the perturbed-benchmark experiments — start here

You are running a fixed evaluation harness over three entity-perturbed
text-to-Cypher benchmarks with **one generator LLM assigned to you**. You do
**not** need to understand the method: you set a few lines in one config file,
run four commands, and send back the output directory.

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
  `text-embedding-3-small` (and `setup_fcav.py` embeds the graph's values with
  it). On top of that you need the key for the provider of *your* model:

| your model (`GENERATOR_LLM`) | provider | key in `.env` | where a key comes from |
|---|---|---|---|
| everyone (embeddings), and `gpt-5.6-terra` / `gpt-5.6-luna` | OpenAI | `OPENAI_API_KEY` | platform.openai.com → API keys |
| `claude-sonnet-5`, `claude-haiku-4.5` | Anthropic | `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `deepseek-v3.1`, `llama-3.3-70b` | DeepInfra | `DEEPINFRA_API_KEY` | deepinfra.com → Dashboard → API Keys |

  **Ask the coordinator for the lab key before creating your own** — the runs
  are billed centrally and each model has its own key so spend can be tracked.
  Never commit `.env`.
- **Disk, if you run `fcav`:** its value index is ~4 GB per large graph (~40 GB
  for the full suite). You either download the coordinator's bundle or build
  it with `setup_fcav.py` (step 3).

## 1. Verify the dataset — do this first, every time you pull

```bash
python benchmarks/verify.py
```

Must print **`VERIFIED — safe to run experiments and pool results.`**

This is not a formality. The benchmarks are the **v2.2 verified release,
4,611 questions**; earlier checkouts carried the 4,641-row pre-verification
v2.1 set or the 4,875-row pre-curation set, and results from different copies
**cannot be pooled** — nothing downstream will warn you. If it fails:
`git pull`, run it again, and if it still fails, ask before running anything.

## 2. Choose your model and slice — edit `eval_config.py`

Open `eval_config.py`. In the boxed **`★ EXPERIMENT PARAMETERS ★`** block at
the top set your model and method, and just below it set `EVAL_PAIRS`:

```python
GENERATOR_LLM = "gpt-5.6-terra"   # ← the model assigned to you (exact preset name, see table)
METHOD        = "cyanchor"        # one of the five below; run each separately
SHARDS        = 1                 # keep 1 for cyanchor (see warning)
LIMIT         = None              # None = all examples; 5 = smoke test

EVAL_PAIRS = [("cypherbench_augmented", "movie")]   # your graph(s); full suite in "Work split"
```

**The values already in the file are the last person's scratch, not a default.**
Set them to your own assignment. When you are done, `git checkout eval_config.py`
— do not commit these edits.

**The model presets** (`config.MODEL_PRESETS`; the name is what you type and
what appears in the result directory). The six in the sweep:

| preset | what it is | key |
|---|---|---|
| `gpt-5.6-terra` | GPT workhorse (primary model) | `OPENAI_API_KEY` |
| `gpt-5.6-luna` | cheap tier — also for smoke tests | `OPENAI_API_KEY` |
| `claude-sonnet-5` | Claude strong tier, same price point as Terra (thinking switched off by the harness) | `ANTHROPIC_API_KEY` |
| `claude-haiku-4.5` | cheap tier (its NER-stage prompt is cached; its Cypher-stage prompt is just under Haiku's 4,096-token caching minimum, so that stage runs uncached) | `ANTHROPIC_API_KEY` |
| `deepseek-v3.1` | open-weights, strong tier (DeepInfra) | `DEEPINFRA_API_KEY` |
| `llama-3.3-70b` | open-weights baseline (DeepInfra) | `DEEPINFRA_API_KEY` |

Two more exist but are **not** part of the sweep — do not run them unless
asked: `gpt-4.1` (the baseline the reference runs used) and `claude-opus-5`
(about 2.5× the cost of Sonnet).

One name switches every stage of the pipeline (entity extraction, Cypher
generation, answer formatting). A wrong name fails immediately with the list
of valid ones — it never silently falls back to another model.

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
> understates it. The other four methods can use higher `SHARDS`. If you share
> a key with someone else running at the same time, keep it low.

**Smoke test first — all five methods, not just one.** Set your own
`GENERATOR_LLM`, `LIMIT = 3`, `EVAL_PAIRS = [("cypherbench_augmented",
"flight_accident")]` (the smallest graph), then run `python eval_run.py` once
per `METHOD` (about ten minutes and a few cents in total) and
`python eval_aggregate.py`. **Every method's block must show `err = 0`.** A
provider can reject one method and accept the other four — on 2026-09-11
GPT-5.6 refused every `react` example (function tools + reasoning) while
`no_val_link` / `cyanchor` / `fcav` / `graphrag` ran fine; a `no_val_link`-only
smoke test would have passed and the full `react` run would have scored every
question 0. If a block shows `err > 0`, stop and send the coordinator the
`error` field of one line of that run's `records.jsonl` — a rejected
parameter is a one-line fix in the harness, not something to work around.
The GPT-5.6 and Claude presets have been run through all five methods from a
fresh clone; the DeepInfra presets are registered from the provider's
published ids and your smoke test is their first live call.

## 3. Get the per-graph artifacts — do **not** run setup yourself

The prompts, generated tools, schema files and tool-routing index for every
graph were built **once** by the coordinator (`gpt-4.1` + OpenAI embeddings)
and ship in the repo: `setup_artifacts/<dataset>__<graph>/` (~7 MB for all
graphs), with `setup_artifacts/MANIFEST.json` holding a sha256 per file.
Everyone evaluates with byte-identical prompts and tools — that is what makes
the six models comparable. So **never run `scripts/setup_and_archive.py`**: it
would regenerate the prompts with an LLM call, give you a slightly different
set, and the pre-flight would (correctly) refuse to run on it.

What is *not* in git is the large value index of the `fcav` method,
`generated/fcav/` (3–4 GB per large graph, ~40 GB for all 13). You build it
yourself, once per graph — it is model-independent:

```bash
python setup_fcav.py     # reads EVAL_PAIRS; cents of OpenAI embeddings per graph;
                         # minutes on the small graphs, a few hours on movie / politics / geography / company
```

(If the coordinator has shared a pre-built bundle, unpacking it so that
`setup_artifacts/<dataset>__<graph>/generated/fcav/` exists is equivalent.)
You only need it for `METHOD = "fcav"`; the other four methods run without it,
and `eval_run.py` refuses to start an `fcav` run on a graph whose index is
missing, so you cannot accidentally score an empty index. If the pre-flight
prints `!` for a graph, the coordinator has not published that graph yet —
ask, don't build.

## 4. Pre-flight — must be green

```bash
python verify_setup.py
```

Every line must be ✓. It checks two things per graph:

- **tools match the graph** — a ✗ here means the archive's tools belong to a
  different graph; evaluating it would produce a near-zero score that looks
  like a real result. `git pull` and re-run; if it persists, tell the
  coordinator.
- **artifacts = published set** — `MISMATCH` means your copy of the archive
  differs from `MANIFEST.json` (edited, or regenerated by a setup run).
  `git checkout setup_artifacts/` and re-run. `MISSING` means you have not
  pulled the archive. `!` means not published yet — wait. `eval_run.py`
  applies the same check and refuses a `MISMATCH`/`MISSING` graph, so a run
  cannot start on the wrong prompts even if you skip the pre-flight.

`UNREACH` is a network problem (VPN), not a broken setup.

## 5. Run

```bash
python eval_run.py        # one run per METHOD; re-edit METHOD and repeat
python eval_aggregate.py  # prints the summary table (one block per method@model)
```

Results land in a fresh timestamped directory per run:

```
logs/runs/<dataset>__<graph>__<method>@<model>__<YYYYMMDD-HHMMSS>/
    records.jsonl    one line per example  ← this is what we need back
    summary.json     aggregate + full run configuration (incl. the model)
```

`<method>` is `no_val_link` / `fcav` / `react` / `graphrag`, and for our method
`cyanchor_fl`; `<model>` is your `GENERATOR_LLM`. Two models can never land in
the same directory, so re-running is always safe.

**If a run dies** (laptop asleep, rate-limit storm, network): there is no
resume — re-run with `EVAL_PAIRS` shrunk to the graphs that did not finish.
Each graph is its own run directory, so nothing already completed is touched;
just leave the dead run's directory in place (it is diagnostic, see step 6).

## 6. Send back

Send the whole `logs/runs/` directory (or just the run dirs you produced),
zipped. **`records.jsonl` is the important file** — it holds one record per
example, which lets us re-derive every table without re-running anything.

Also tell us: which model, graphs and methods you ran, and anything that looked
odd (hangs, rate-limit errors, red pre-flight lines you worked around).

Do **not** delete run directories that errored — a failed run is diagnostic.

---

## Work split — one person, one model

Each person owns **one model** and runs the **full suite** on it: 13 graphs ×
5 methods (~54 machine-hours at the shard settings above; leave it running).
To finish in a day or two instead, make two or three separate clones of the
repo on your machine and give each a different slice of `EVAL_PAIRS` — one
`eval_run.py` per clone is fine (it is one per *checkout* that matters, see
below). If you finish early, take a second model.

| model (`GENERATOR_LLM`) | owner | status |
|---|---|---|
| `gpt-5.6-terra` | | |
| `gpt-5.6-luna` | | |
| `claude-sonnet-5` | | |
| `claude-haiku-4.5` | | |
| `deepseek-v3.1` | | |
| `llama-3.3-70b` | | |

The full suite, ready to paste as `EVAL_PAIRS` (perturbed sets only; use
`bloom`, not `bloom50` — see the note below):

```python
EVAL_PAIRS = [
    ("cypherbench_augmented",  "movie"),
    ("cypherbench_augmented",  "politics"),
    ("cypherbench_augmented",  "geography"),
    ("cypherbench_augmented",  "fictional_character"),
    ("cypherbench_augmented",  "company"),
    ("cypherbench_augmented",  "nba"),
    ("cypherbench_augmented",  "flight_accident"),
    ("mindthequery_augmented", "healthcare"),
    ("mindthequery_augmented", "covid"),
    ("mindthequery_augmented", "wwc"),
    ("mindthequery_augmented", "er"),
    ("mindthequery_augmented", "bloom"),
    ("zograscope_augmented",   "pole"),
]
```

Question counts (v2.2), so you can budget and split:

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

> `zograscope/pole` is one graph but 28% of the benchmark — budget for it, or
> split it by running with different `LIMIT`/shard settings and telling us how
> you split it.

> **Two names in `GRAPH_CONNS` that are not rows in this table.**
> `terrorist_attack` is a train-split graph kept for development and tuning —
> it is deliberately outside the 13-graph evaluation suite and has no perturbed
> questions. `bloom50` is the *same graph* as `bloom` (same connection; the
> dump is named `bloom50`, the test data's `graph` field says `bloom`) — for
> the perturbed set always use **`bloom`**. In `setup_artifacts/` the `bloom`
> archive is a symlink to `mindthequery_augmented__bloom50` — git restores it on
> macOS / Linux / WSL; on native Windows enable symlinks or copy the directory.

Every run writes its own directory, so two people never overwrite each other
**as long as they are on different machines**.

## Three things that will bite you

1. **Never run `scripts/setup_and_archive.py` or edit anything under
   `setup_artifacts/`.** Results are only poolable if every generator saw the
   same prompts and tools; the pre-flight and `eval_run.py` both enforce this
   against `MANIFEST.json`.
2. **One `eval_run.py` per checkout at a time.** The harness keeps one live
   copy of each graph's artifacts and swaps the right one in before each pair.
   Two concurrent runs on the same checkout corrupt each other's scores
   without any error. Use `SHARDS` for parallelism inside a graph; use
   separate clones (on one machine or many) for parallelism across graphs or
   people.
3. **Don't trust a low score.** If the grounding methods (`react`, `cyanchor`)
   collapse to roughly the `no_val_link` score while `fcav` still looks normal,
   that is the signature of contaminated artifacts, not a real result. Re-run
   `verify_setup.py`. And a block with `err > 0` in `eval_aggregate.py` is not
   a result at all — every errored example is scored 0, so a rejected API
   parameter looks like a bad model. Check `err` before you read `EA`.

## Questions

Ask before improvising. A wrong-but-plausible number costs far more than a
delayed one, because we usually cannot tell from the output that it was wrong.
