# Running the perturbed-benchmark experiments — start here

Thank you for running one of the generator models in this sweep. This page is
the complete procedure. The evaluation harness is fixed so that every model is
measured under identical conditions; your part is to point it at your model
(one line in one config file), run four commands, and publish the result as a
branch in this repository. None of the steps require the method's internals —
[`RUNNING_EXPERIMENTS.md`](RUNNING_EXPERIMENTS.md) explains them if you are
interested.

Everything below is a checklist. If a step does not print what it says it
should, please stop and ask rather than work around it: a run that starts from
a bad state produces a plausible-looking score that is silently wrong, and we
cannot tell afterwards. We would much rather answer a question than lose a
week of your machine time.

How the harness works, every config knob and the pre-flight words: [`RUNNING_EXPERIMENTS.md`](RUNNING_EXPERIMENTS.md) — a reference; the sweep procedure is only here.

> **What you hand in:** the branch `sweep/<model>` **pushed to this repository**,
> plus its link (§6). A report sent as a file is not a deliverable — the
> per-question records we need exist only on the branch.

> **Set up before 2026-09-12, or ran `eval_run.py` / `eval_aggregate.py` by
> hand?** The procedure changed on 2026-09-12, when `orchestrate_sweep.py`
> arrived. The old steps — editing `EVAL_PAIRS` / `METHOD`, running
> `scripts/setup_and_archive.py` or `setup_fcav.py` yourself, `eval_run.py` +
> `eval_aggregate.py` once per method, zipping `logs/runs/` — are retired, and
> running setup yourself is now forbidden (§3). Do this once, then continue
> from §1:
>
> 1. `git checkout setup_artifacts/ eval_config.py && git pull` (this discards
>    your local edits to those files — you set the model again in §2). If
>    `git pull` refuses because untracked files under `setup_artifacts/` would
>    be overwritten: `mv setup_artifacts setup_artifacts.old && git pull &&
>    git checkout setup_artifacts/` — the `generated/fcav/` folders in
>    `setup_artifacts.old/<pair>/` can be copied back to skip the index rebuild.
> 2. **Unless the coordinator has told you by name to keep your existing
>    runs**, the clean slate — copy the line for the model you were assigned
>    (step 1 has just reset `eval_config.py`, so the script will not guess it,
>    and it refuses a name that is not a preset):
>
>    ```bash
>    python scripts/audit_runs.py --discard-all --model gpt-5.6-terra
>    python scripts/audit_runs.py --discard-all --model gpt-5.6-luna
>    python scripts/audit_runs.py --discard-all --model claude-sonnet-5
>    python scripts/audit_runs.py --discard-all --model claude-haiku-4.5
>    python scripts/audit_runs.py --discard-all --model deepseek-v3.1
>    python scripts/audit_runs.py --discard-all --model llama-3.3-70b
>    python scripts/audit_runs.py --discard-all --model qwen3-32b
>    ```
>
>    It lists every run directory of that model plus the driver's state files,
>    deletes them after you type the model name, and you start again from §1.
>    Runs made under the old procedure cannot be pooled with anyone else's, and
>    this is the one command that leaves nothing behind.
> 3. **Only if you were told to keep them:** the same line **without**
>    `--discard-all` (e.g. `python scripts/audit_runs.py --model gpt-5.6-luna`)
>    — one line per run directory with a verdict. A run can be used
>    only if it was scored on the released benchmark rows (checked from the
>    records themselves) **and** made after this checkout first had the shared
>    artifact set (read from `git reflog`; 2026-09-10 or later — which
>    artifacts a run saw is recorded nowhere else). For everything else it
>    prints the exact `rm -rf` lines: run those, and only those, then paste the
>    whole audit output to the coordinator. Usable runs are picked up by the
>    driver automatically (§5).

---

## 0. Prerequisites

```bash
git clone https://github.com/receive2/text2cypher_agent.git t2c && cd t2c   # main branch — do not check out anything else
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
- **Push access.** The deliverable is a branch pushed to this repository
  (§6), so you need **write access**. Ask the coordinator to add you as a
  collaborator on GitHub and accept the invitation **on day 1** — do not find
  out after the sweep has finished. Check it once with
  `git push --dry-run origin main` — `Everything up-to-date` means you can push; `403` /
  `denied` means you cannot (`rejected` / `fetch first` only means your `main` is
  behind: `git pull`, then check again). `--publish` runs the same check itself and
  stops with a clear message, so this is just to find out early.
- **Updating your checkout.** When the coordinator asks you to pull, git refuses
  to pull over your edited `eval_config.py`. Do this instead, then set
  `GENERATOR_LLM` again (§2):
  ```bash
  git checkout eval_config.py && git pull
  ```
  Runs under `logs/runs/` are untouched. Forgetting the second step cannot go
  unnoticed: the driver refuses to start while `GENERATOR_LLM` is still the
  committed value.
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
| `deepseek-v3.1`, `llama-3.3-70b`, `qwen3-32b` | DeepInfra | `DEEPINFRA_API_KEY` | deepinfra.com → Dashboard → API Keys |

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
same ones. The value already in the file is the coordinator's reference model,
not a default: the driver refuses to start while `GENERATOR_LLM` still holds
the committed value, so a skipped step 2 — or a `git checkout eval_config.py`
after a pull — is caught before anything runs.

**The model presets** (`config.MODEL_PRESETS`; the name is what you type and
what appears in every run directory). The seven in the sweep:

| preset | what it is | key |
|---|---|---|
| `gpt-5.6-terra` | GPT workhorse (primary model) | `OPENAI_API_KEY` |
| `gpt-5.6-luna` | cheap tier | `OPENAI_API_KEY` |
| `claude-sonnet-5` | Claude strong tier, same price point as Terra (thinking switched off by the harness) | `ANTHROPIC_API_KEY` |
| `claude-haiku-4.5` | cheap tier | `ANTHROPIC_API_KEY` |
| `deepseek-v3.1` | open-weights, strong tier (DeepInfra) | `DEEPINFRA_API_KEY` |
| `llama-3.3-70b` | open-weights baseline (DeepInfra) | `DEEPINFRA_API_KEY` |
| `qwen3-32b` | open-weights small tier (DeepInfra; thinking switched off by the harness) | `DEEPINFRA_API_KEY` |

Three more exist but are **not** part of the sweep — do not run them unless
asked: `gpt-4.1` (the baseline the reference runs used), `claude-opus-5`, and
`deepseek-v4.1-flash` (needs a separate DeepSeek key).

One name switches every stage of the pipeline (entity extraction, Cypher
generation, answer formatting). A wrong name fails immediately with the list
of valid ones — it never silently falls back to another model.

## 3. Artifacts — nothing to build, never run setup

The prompts, generated tools, schema files and tool-routing index for every
graph were built **once** by the coordinator and ship in the repo
(`setup_artifacts/`, ~8 MB, pinned file-by-file by
`setup_artifacts/MANIFEST.json`). Everyone evaluates with byte-identical
prompts and tools — that is what makes the seven models comparable — so
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

Runs all **five methods** on one small graph (`flight_accident`, 3
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

(`python verify_setup.py --suite` prints the same table for the 13 suite graphs
on its own if you want to look before running anything; without `--suite` it
checks `EVAL_PAIRS`, which is not the suite.)

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
**`report/<model>/SWEEP.md`**: the completeness matrix plus every table the
paper needs — EA / PSJS per dataset and overall, by perturbation strategy, by
query difficulty. Every report file is regenerated in place (`--status`
refreshes `SWEEP.md` too); every number in them is derived from the run
directories, which are never deleted, and every `--publish` is a commit, so the
branch history keeps each published version.

The `<method>` segment spells out CyANCHOR's active retrieval arms, so the
shipped default appears as `cyanchor_fl` (fuzzy + Levenshtein). If you ever see
`cyanchor_fvl`, the vector arm has been switched on and the run is not
comparable with everyone else's — restore the defaults and re-run.

**How to read the matrix.** Each cell shows `n/err`: records present / records
that errored. A cell is

- **✓** — one record per question and no infrastructure problem. Errors are
  allowed here: some questions error on every model because the benchmark's own
  gold query is broken (`gold`), and some because your model wrote invalid
  Cypher (`agent`). Both score 0 and are part of the result.
- **✗** — missing or truncated (fewer records than questions: the run did not
  finish), or `≠release`: the run was scored on an older copy of the benchmark.
  Either way the driver re-runs the cell.
- **⚠** — complete, but a large share of the errors are **timeouts or API
  failures** (`infra`): the model never actually answered those questions.
  Such a score measures the provider's rate limit, not the model. The driver
  detects this by classifying every error string, lists the cells under
  **Flagged cells** with the most common error text, and re-runs them
  automatically (at most twice). The report also has an *Errors by kind*
  table so `116 errors` reads as `71 model + 45 timeouts`.

**If it stops** (laptop asleep, rate-limit storm, network): run the same
command again. Completion is read from disk, so every ✓ cell is skipped and
only ✗ and ⚠ cells run; a re-run writes a new time-stamped directory and the
newest one wins, so there is nothing to delete by hand — the only runs that
must go are ones the driver cannot use: `python scripts/audit_runs.py --model
<preset>` names them, and `python scripts/audit_runs.py --discard-all --model
<preset>` wipes every run of that model when the coordinator says to start
clean (the box at the top has the line for each model). A cell that keeps
failing is tried three times, then reported and skipped so the rest of the
suite continues. To re-run a subset on purpose:

```bash
python orchestrate_sweep.py --graphs movie nba       # these graphs, all methods
python orchestrate_sweep.py --methods react          # this method, all graphs
python orchestrate_sweep.py --status                 # matrix + headline numbers, runs nothing
```

The run ends with **COMPLETE** or **NOT CLEAN** and prints the next command
to type. Do not report numbers from a sweep that is not COMPLETE.

**If the coordinator tells you a method does not apply to your model** (for
example `react` on a model whose API has no function calling), add
`--skip-methods react` to every `orchestrate_sweep.py` command. The method is
then left out of the run *and* of the completeness verdict, `--publish`
accepts the sweep, and the SWEEP file states which methods were skipped.
Please decide this together with the coordinator rather than on your own.

## 6. Deliver — run `--publish`, send what it prints

**The deliverable is the branch `sweep/<model>` on GitHub.** It holds every
run's per-question records (`logs/runs/…/records.jsonl` + `summary.json`) and
the report tables (`report/<model>/`). Every number in the paper is re-derived
from those records; a report file sent by email or chat cannot be used, and
does not count as delivered.

```bash
python orchestrate_sweep.py --publish
```

The command checks that you can push, builds the commit in a throw-away git
worktree (your own branch and working tree are never touched, so you can keep
`git pull`-ing `main`), pushes `sweep/<model>`, and ends with the lines to
send. It is done **only** when you see:

```
✓ published branch sweep/<model> @ <sha> (65/65 clean cells, N run dirs). Your branch and working tree were not touched.

  Send the coordinator exactly this:
    model:   <model>
    branch:  sweep/<model>
    report:  https://github.com/receive2/text2cypher_agent/blob/sweep/<model>/report/<model>/SWEEP.md
```

Copy those three lines into one message. That is the whole deliverable.

If instead it prints **`✗ publish refused — the sweep is not clean`**, it lists
the ✗ / ⚠ cells and the exact commands to run next — follow them:

1. `python orchestrate_sweep.py` — re-runs only those cells; everything else is
   kept.
2. `python orchestrate_sweep.py --status` — every cell should now show ✓.
3. If a cell *still* shows ✗ or ⚠ after step 1 (it was retried and keeps
   failing), publish anyway so the finished records reach the repository, and
   paste the report's matrix and **Flagged cells** section to the coordinator:
   `python orchestrate_sweep.py --publish --allow-incomplete`.
   The branch is labelled `PARTIAL` and lists the affected cells; nobody will
   mistake it for a finished sweep.

If it prints **`✗ you cannot push to this repository`**, you do not have write
access yet: ask the coordinator to add you as a collaborator on GitHub, accept
the invitation, and run `--publish` again. Nothing was changed. Do **not** send
files instead.

Publishing again later (a refreshed branch, or after filling ⚠ cells) is the
same command; it adds a commit on top of the existing branch. Do **not** delete
`logs/runs/` (only what `scripts/audit_runs.py` names, or everything with its `--discard-all` when the coordinator says so) and do **not** force-push.

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
| `qwen3-32b` | | `sweep/qwen3-32b` |

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

Please ask before improvising — a message to the coordinator is always
welcome. A wrong-but-plausible number costs far more than a delayed one,
because we usually cannot tell from the output that it was wrong.
