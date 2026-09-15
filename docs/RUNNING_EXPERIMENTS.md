# Running experiments safely (multi-dataset, multi-graph)

This is the procedure for anyone running the t2c eval harness across
several datasets and graphs. You do **not** need to understand the
internals — edit `eval_config.py`, run the four commands, and read the
pre-flight table.

The whole run is driven by **one file, `eval_config.py`**. Everything you touch to
run an experiment or an ablation is in the boxed **`★ EXPERIMENT PARAMETERS — EDIT
THESE ★`** block at the top of that file — the method, the CyANCHOR sub-axes and
ablation toggles, the example cap, and the parallelism, each annotated inline.
`GRAPH_CONNS` / `EVAL_PAIRS` (just below) choose *which* graphs. No environment
variables in the normal flow.

## The one thing to understand

The harness keeps **one live copy** of each graph's setup artifacts
(node tools, schema, prompts, FAISS indexes, FCAV index) and **swaps**
the right archive into those same files before each `(dataset, graph)`
is evaluated. This is fast, but it means the live tree is shared global
state: if the wrong archive is live — because a setup was interrupted,
or someone re-archived by hand at the wrong moment — the eval runs
against the **wrong tools** and silently scores near zero (the
"no-value-linking" floor). Nothing in the *score* tells you it was wrong.

**Tell-tale sign of this bug:** the grounding methods (`react` / `cyanchor`)
collapse to roughly the `no_val_link` score, while **FCAV still scores
normally**. That asymmetry = contaminated tools (the schema and prompts
that FCAV uses were fine; the per-graph tools were not).

## Step 0: verify you have the right dataset

```bash
python benchmarks/verify.py     # must print VERIFIED
```

The perturbed benchmarks live in `benchmarks/` in this repo and
`eval_config.py` reads them from there, so a fresh clone is already correct
and everyone evaluates the same bytes — which is what makes separate people's
results poolable. The release is the **v2.2 verified freeze: 4,611 questions**
(cypherbench 2,099 · mindthequery 1,222 · zograscope 1,290) —
the v2.1 freeze (4,641) after applying the human-verification verdicts
(`docs/VERIFICATION_PROTOCOL.md` §9; every row's fate is in
`audit/verification/decisions.csv`).

> A checkout from before 2026-09 carried the *pre-curation* set (4,875 rows);
> one from 2026-08-22 … 2026-09-09 carried the *pre-verification* v2.1 set
> (4,641 rows). Numbers from those copies are not comparable with anything
> produced now — runs made on v2.1 can be re-derived on the released rows with
> `scripts/rescore_on_verified.py --decisions audit/verification/decisions.csv`.
> If `verify.py` does not print VERIFIED, `git pull` and check again before
> you run anything.

## Golden rule: verify before you evaluate

```bash
python verify_setup.py          # checks every pair in eval_config.EVAL_PAIRS
python verify_setup.py --all    # checks every pair in GRAPH_CONNS
```

This connects to each graph and confirms the archive's node tools search
labels that **actually have nodes** in that graph. Green = safe to run.
Red = contaminated; do not evaluate until fixed. Example red line:

```
✗ cypherbench__movie  CONTAM   ARTIFACT/GRAPH MISMATCH: the node tools search
  labels ['Airport', 'FlightAccident'] that have ZERO nodes in this graph …
  Re-run the setup for that pair (see "If a pair is contaminated").
```

> Network note: reaching the graphs requires the corporate **VPN
> disconnected** (see the env-vpn-proxy note). An `UNREACH` row means a
> connection problem, not a contaminated archive.

## First time on a fresh checkout (one-time, per graph)

`eval_config.py` is **already committed** (the eval Neo4j connection is public for
reviewers) — open and edit it, do **not** `cp eval_config_example.py` over it. The
harness needs each graph's artifacts archived before it can swap them in:

```bash
python scripts/setup_and_archive.py     # build + archive artifacts for the graphs you'll run
```

Without this, `verify_setup.py` and `eval_run.py` have nothing to swap in and every
pair fails the pre-flight. (The `fcav` baseline additionally needs `python
setup_fcav.py` once per graph.)

## Standard run procedure

```bash
# 1. Pick the slice + method — edit eval_config.py (EVAL_PAIRS + METHOD; see below).
#    These are YOUR per-run scratch — don't commit them (see "Multi-person" below).

# 2. Pre-flight. Stop here and fix anything that is not green.
python verify_setup.py

# 3. Run. Everything comes from eval_config.py — no env vars needed.
python eval_run.py

# 4. Aggregate.
python eval_aggregate.py
```

> **Multi-person discipline.** `eval_config.py` is committed and shared, but
> `EVAL_PAIRS` / `METHOD` / `LIMIT` / `SHARDS` are per-run scratch — the values you
> pull are just the last person's run, not a default. Set them to *your* slice
> before running and **don't commit those edits** (`git checkout eval_config.py`
> when done). Commit `eval_config.py` only to update the shared `GRAPH_CONNS`
> registry. Two people running `eval_run.py` on the **same checkout/machine** at
> once will corrupt each other's live tree — coordinate, or work on separate
> checkouts.

To run the **five methods** for a comparison, change `METHOD` in `eval_config.py`
and re-run `eval_run.py` once per method (the records land in separate dirs — see
"Where results land" — so nothing is overwritten). `eval_aggregate.py` then prints
one table block per `(dataset, method)`.

## Where the config lives (`eval_config.py`)

The `★ EXPERIMENT PARAMETERS ★` block at the top of `eval_config.py` is the single
source of truth for *what runs*. Every knob below is in that block; `EVAL_PAIRS`
(which graphs) sits just under it, next to `GRAPH_CONNS`.

**Method**

| Field | Values | Meaning |
|---|---|---|
| `METHOD` | `no_val_link` · `fcav` · `react` · `graphrag` · `cyanchor` | The method. `cyanchor` is the shipped grounder; the other four are baselines. |
| `TOOL_TYPE` | `node` · `node_rel` | Tool scope (applies to `react` / `cyanchor`). |

**CyANCHOR retrieval arms** (≥1 on; unioned per field; baselines ignore these)

| Field | Values | Meaning |
|---|---|---|
| `RETRIEVAL_FUZZY` / `RETRIEVAL_VECTOR` / `RETRIEVAL_LEVENSHTEIN` | `True`/`False` each | The three arms. Default `fuzzy+lev` (vector needs in-graph embeddings). |
| `RETRIEVAL_LEVENSHTEIN_K` | int | Candidates the Levenshtein arm returns (default `10`). |

**CyANCHOR result self-correction + ablation toggles** (default ON = shipped method)

| Field | Values | Meaning |
|---|---|---|
| `CYPHER_SEMANTIC_REPAIR` | `True`/`False` | Result-level evaluate → regenerate loop. |
| `CYPHER_REPAIR_MAX_ROUNDS` | int | Max semantic-repair rounds (default `4`). |
| `CYPHER_EMPTY_IS_WRONG` | `True`/`False` | Treat a 0-row result as a defect. |
| `PLAN_EXEC_ESCALATE` | `True`/`False` | Corrective LLM-judge retrieval loop. |
| `PLAN_EXEC_VALUE_SNAP` | `True`/`False` | Post-generation existence-gated value-snap guard. |
| `PLAN_EXEC_SKIP_GROUNDED` | `True`/`False` | Skip escalation for already-grounded mentions (latency). |
| `PLAN_EXEC_PARALLEL_MENTIONS` | `True`/`False` | Run mentions in parallel threads (latency; raises peak LLM concurrency). |
| `CYPHER_RETRY_MAX_ROUNDS` | int | Exec-error retry (react / when semantic repair off): `0` legacy · `1` no-repair control · `2` gen+CoT-repair. |

**GraphRAG baseline toggles** (leave as-is unless ablating GraphRAG)

| Field | Values | Meaning |
|---|---|---|
| `GRAPHRAG_EMPTY_IS_WRONG` | `True`/`False` | 0 rows counts as a defect. |
| `GRAPHRAG_LLM_EVALUATOR` | `True`/`False` | Use the LLM evaluator (else accept any non-empty). |

**Run size / parallelism**

| Field | Values | Meaning |
|---|---|---|
| `LIMIT` | int · `None` | Examples per pair (`None` = all; set e.g. `20` to smoke-test). |
| `SHARDS` | int | Intra-graph parallelism (see "Parallelism"). ⚠ keep `1` for CyANCHOR. |
| `VERBOSE` | `True`/`False` | Per-example log lines. |
| `EVAL_PAIRS` | `[(dataset, graph), …]` | Which pairs to run (below `GRAPH_CONNS`). ⚠ For the perturbed suite use the 13 pairs in `_FULL_EVAL_PAIRS_13`. `terrorist_attack` is a train-split/tuning graph (no perturbed questions); `bloom50` is the same graph as `bloom` — use `bloom`. |
| `OUT_DIR` | path | Run-dir root (infra section). Default `logs/runs`. |

The baselines (`no_val_link` / `fcav` / `react` / `graphrag`) ignore the
CyANCHOR sub-axes — set `METHOD` and go.

### Running CyANCHOR with the vector arm (embeddings)

`RETRIEVAL_VECTOR` spans three layers — flipping the toggle alone is the common
mistake (you get an empty arm). To run *with* embeddings:

1. **Build them into the graph:** `python setup_project.py` **without**
   `--skip-embeddings` (needs Neo4j 5.18+; auto-discovered props → `vector_config.EMBEDDABLE_PROPERTIES`).
2. **Model/backend** *(optional; defaults fine):* `vector_config.py`
   (`EMBEDDING_BACKEND` / `EMBEDDING_MODEL_NAME`) — the only home for the embedding model.
3. **Toggle the arm:** `eval_config.py` → `RETRIEVAL_VECTOR = True` → runs land in `…__cyanchor_fvl/`.

**Prerequisite:** step 3 is a no-op on a graph built with `--skip-embeddings`. For
the shipped `fuzzy+lev` default, build with `--skip-embeddings` and leave
`RETRIEVAL_VECTOR = False`.

> Not the same as `vector_config.TOOL_RETRIEVAL_MODE` (`fuzzy`/`vector`/`hybrid`) —
> that is the **ReAct baseline's** retrieval mode, unrelated to CyANCHOR's arm.

## One-command sweep: `orchestrate_sweep.py`

The model sweep is run one model per person with a single driver — the
participant-facing steps are in [`EXPERIMENT_HANDOUT.md`](EXPERIMENT_HANDOUT.md):

```bash
python orchestrate_sweep.py --smoke     # 5 methods x flight_accident x 3 questions -> logs/smoke/
python orchestrate_sweep.py             # 13 graphs x 5 methods for eval_config.GENERATOR_LLM; re-run to resume
python orchestrate_sweep.py --status    # completeness matrix + headline EA/PSJS, no runs
python orchestrate_sweep.py --publish   # branch sweep/<model>: run dirs + report/ + log, commit, push
```

It wraps the same pieces described below — `eval_run.py` per pair, the
graph / manifest / fcav guards, `gen_ablation_report.py` and
`gen_pooled_report.py` for the tables — and adds: a pre-flight over all 13
graphs; building a graph's FCAV index on first use; retry (3×) per cell; resume
from disk (a cell is complete when its newest run holds one record per
question — errored questions are allowed and score 0). Every driver invocation
ends by writing `report/<model>/SWEEP_<YYYYMMDD-HHMMSS>.md` — never
overwritten; `SWEEP.md` is a copy of the latest — holding the completeness
matrix and every table the paper needs: EA / PSJS per dataset and overall, by
perturbation strategy, by query difficulty. Pooling is over all questions of a
dataset (each question weighs one), identical to the committed gpt-4.1 tables.
`orchestrate_cyanchor.py` is the older CyANCHOR-only refresh driver; it now
writes under `report/<model>/` as well.

The deliverable of a sweep is the branch `sweep/<model>`; `main` keeps the
gpt-4.1 reference tables under `report/gpt-4.1/`.

## The published artifact set (coordinator only)

Colleagues never run setup: the model-independent parts of every perturbed
graph's archive — `agent/prompts.py`, `generated/generated_{node,rel}_tools.py`,
`schema_data/`, the two `generated/faiss/tools_auto*` routing indexes and the
`vector_config` snippet — are committed under `setup_artifacts/` (the
`.gitignore` whitelists exactly these; `generated/fcav` and `generated/chess`
never enter git), and `setup_artifacts/MANIFEST.json` pins one sha256 per file.
`verify_setup.py` compares every checkout against it, so a run can only start
on byte-identical prompts and tools. To publish or re-publish:

```bash
# 1. rebuild whatever verify_setup.py --all flags (EVAL_PAIRS = that pair), then setup_fcav.py
python scripts/setup_and_archive.py && python setup_fcav.py
# 2. write the manifest — refuses any archive whose FAISS fingerprints are stamped for another pair
python scripts/artifact_manifest.py build --strict
# 3. commit the whitelisted files (~7 MB for 13 graphs) and push
git add setup_artifacts && git commit -m "artifacts: publish <graphs>" && git push
# 4. share generated/fcav/ out of band (one tar per graph); it is not in the manifest
```

`python scripts/artifact_manifest.py check --all` reports every published pair
as OK / MISMATCH / MISSING / UNPUBLISHED; `verify_setup.py` prints the same
verdict next to the graph check, and `eval_run.py` refuses to run a
MISMATCH / MISSING pair (UNPUBLISHED only warns, so the coordinator can
evaluate a rebuilt archive before publishing it; `EVAL_SKIP_MANIFEST_GUARD=1`
bypasses the guard). `eval_run.py` also refuses `METHOD = "fcav"` on a graph
whose archive has no `generated/fcav/` index.

## Where results land

Each invocation writes a **fresh, timestamped per-run directory** (see
`eval_paths.py`, the single source of truth for this layout):

```
logs/runs/<dataset>__<graph>__<method>__<YYYYMMDD-HHMMSS>/records.jsonl  # one record per example
logs/runs/<dataset>__<graph>__<method>__<YYYYMMDD-HHMMSS>/summary.json   # aggregate + run_meta + run_config
```

The method (`graphrag`, `cyanchor_fl`, …) is **part of the path**, the
generator model is appended to it (`cyanchor_fl@claude-sonnet-5`), and every
invocation gets its **own timestamp**. Ablation knobs stay out of the name:
what actually ran (LLM per stage, embedding backend, every knob) is recorded
inside `summary.json` under `run_meta` / `run_config`, so each run dir is
self-describing.

**Why the model is in the name.** Readers resolve a triple to *one* directory —
its newest run. Without the model in the path, a second model's run is simply a
newer stamp for the same triple, so every report would silently switch to it
and a sweep would end up comparing methods across mixed generators.
`eval_paths.latest_run_dir` therefore scopes to the model the current process is
configured for. Runs recorded before model tagging carry no `@` segment; they
stay resolvable, but only for the model that actually produced them (proven
against `run_meta`), so nothing on disk today is lost.
`eval_aggregate.py` aggregates only the newest run per
`(dataset, graph, method, model)` and groups by `(dataset, method)`. It reports
EA and PSJS; exact-match (EM) is recorded per example but not printed — it is
near zero by construction on perturbed questions and says nothing.

## Choosing the generator LLM

One field in the control panel selects the model for **all three stages**
(NER / Cypher / QA) and tags every run directory with it:

```python
GENERATOR_LLM = "claude-sonnet-5"   # eval_config.py, ★ EXPERIMENT PARAMETERS ★
```

The value is a **preset name** from `config.MODEL_PRESETS` (`gpt-4.1`,
`gpt-5.6-terra`, `gpt-5.6-luna`, `claude-sonnet-5`, `claude-haiku-4.5`,
`claude-opus-5`, `deepseek-v3.1`, `llama-3.3-70b`, `qwen3-32b`). A preset fixes the provider and the exact
model id; the two open-weights models route through DeepInfra's
OpenAI-compatible endpoint via `config.MODEL_REGISTRY`. An unknown name fails
at startup with the list of valid ones — there is no silent fallback. Adding a
model = one entry in `MODEL_PRESETS` (plus a `MODEL_REGISTRY` entry if it is an
OpenAI-compatible host).

`.env` holds **API keys only** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`DEEPINFRA_API_KEY`; see `.env.example`) — never a model choice. Note that
`OPENAI_API_KEY` is required for every generator: setup's schema-metadata step
runs on `gpt-4.1`, and the tool router and FCAV embed with OpenAI
`text-embedding-3-small` (`vector_config.py`). `eval_run`
hands the preset to the worker the same way it hands `METHOD` (an injected
`GENERATOR_LLM` env var that `config.py` receives), so the worker's model and
the directory name always come from the one value you edited. Readers (report
generators, `eval_aggregate`, `latest_run_dir`) scope to
`eval_config.GENERATOR_LLM` too, so a report never mixes models; set it to the
model you want to read before regenerating reports.

Model-specific handling lives in one place, `agent_helper`: the Claude 4.6+/5
line rejects sampling parameters and thinks by default, so those models are
called without `temperature` and with thinking switched off; OpenAI's
reasoning line likewise gets no `temperature`: gpt-5.1+ and gpt-6 run with
`reasoning_effort="none"` — the value the chat-completions endpoint *requires*
once function tools are bound (the react agent binds ~50; measured 2026-09-11:
`"low"` is rejected with a 400 on every react example) **and keep
`temperature=0`**, which non-reasoning mode accepts again — so they are as
deterministic as gpt-4.1 was; the original gpt-5 and the o-series, which do
not accept `"none"` (nor a temperature), keep `"low"`. Every generator
therefore runs as a plain, terse text model, which is what the comparison
needs. To change a model's
parameters, add a `"params"` dict to its entry in `config.MODEL_PRESETS`
(passed to the chat-model constructor verbatim) — never edit `.env`.

**Sampling, per preset** (what the builders send; verified live 2026-09-12):

| preset | sampling |
|---|---|
| `gpt-4.1`, `claude-haiku-4.5`, `deepseek-v3.1`, `llama-3.3-70b`, `qwen3-32b` | `temperature=0` (Qwen3 additionally `enable_thinking=false`) |
| `gpt-5.6-terra`, `gpt-5.6-luna` | `reasoning_effort="none"` + `temperature=0` |
| `claude-sonnet-5`, `claude-opus-5` | thinking disabled; **no temperature — the API refuses it** (`"temperature is deprecated for this model"`), so these run at Anthropic's default sampling and a re-run of the same question can differ. There is no seed either; report them as single-sample runs. |

**What has been exercised live (2026-09-09).** `gpt-5.6-terra`,
`gpt-5.6-luna`, `claude-sonnet-5`, `claude-opus-5` and `claude-haiku-4.5` were
all called through the real builders: no parameter errors, plain-text replies,
zero reasoning tokens on the GPT-5.6 presets (`reasoning_effort="none"`), and
prompt caching confirmed on both vendors (a second identical call reported
`cache_read` 2,446 of 2,449 input tokens on GPT-5.6, 4,202 on Opus 5 and
5,545 / 11,854 on Sonnet 5 for the Cypher / NER stage prompts). The DeepInfra
presets await a key: **your first run is their smoke test** — a rejected
parameter fails on the first call with the parameter named, and the fix is
one line in `MODEL_PRESETS`.

**Prompt caching is automatic and applies to every model.** The Cypher prompt is
laid out static-first (task text → schema → *then* retrieved values → question),
so OpenAI caches the ~2.8k-token prefix on its own, and a `CACHE_BREAK` marker at
that boundary makes Anthropic cache it too (`agent/prompt_cache.py`). Providers
that cannot use the marker have it stripped, so **the model sees byte-identical
text either way** — caching changes cost, never results. One measured exception:
Claude Haiku 4.5 only caches prefixes of ≥ 4,096 tokens. Measured on the real
prompts (2026-09-09): the NER-agent prefix (system prompt + tool schemas,
5–12k Haiku tokens) **is** cached on 12 of the 13 graphs (`er` is 3,977 tokens,
just under), while the Cypher-stage prefix (3.4–3.8k tokens; only `bloom` clears
4,096) is **not** — so budget Haiku with roughly 40% of its input tokens
cached rather than 60% (Sonnet/Opus/GPT), which puts it at about 85% of its
uncached cost. Note also that the Claude 5 tokenizer counts ~1.5–1.9× the
tokens GPT's does on these prompts (Haiku 4.5: ~1.2×); price Claude runs on
their own token counts, not GPT's.

## Producing the per-graph comparison reports

The committed `report/<model>/<dataset>/<graph>.md` tables (Overall + by
perturbation strategy + by difficulty, EA & PSJS, across all five methods) are
rendered from `logs/runs/` — one folder per generator model (`report/gpt-4.1/`
holds the June reference tables); locations resolved through `eval_paths`:

```bash
# One graph (args: <graph> <report_dir> <label> <dataset_key> [date]):
python gen_graph_report.py movie CypherBench CypherBench cypherbench_augmented

# Dataset-pooled summary across graphs:
python gen_pooled_report.py report/<model>/CypherBench/_summary.md CypherBench \
  "Report — CypherBench (all graphs pooled)" cypherbench_augmented movie nba geography …

# Full CyANCHOR refresh across all 13 graphs (re-runs CyANCHOR, regenerates every
# report; baselines are read from their existing run dirs, not re-run):
python orchestrate_cyanchor.py
```

## Parallelism (`SHARDS`)

`SHARDS=N` splits one graph's examples into N stride-shards run as N parallel
worker processes against the same container, then merges them — wall-clock ≈ 1/N.
`SHARDS=1` is the original single-process coverage (byte-identical). **Graphs still
run sequentially** (the live artifact tree is swapped per graph), so only the
examples *within* a graph parallelise. Lower it if you hit LLM rate limits; raise it
for a big graph on a fast box. Heavily contended single containers can deadlock at
high `SHARDS` — if a run hangs, drop to `SHARDS=1`.

## `eval_config.py` is authoritative — there is no second surface

There are **no environment variables in the normal flow**. `eval_config.py` is the
one document you edit before a run; `eval_run` propagates its settings to the
worker and they **override anything inherited from the shell**, so a stale
`export METHOD=…` left over from some earlier session can *not* silently change
what you run — the file you edited always wins. (A field you leave unset in
eval_config falls through to `config.py`'s shipped default, which is CyANCHOR
`fuzzy+lev`.)

The batch driver `orchestrate_cyanchor.py` sweeps methods/arms by setting
`cfg.METHOD` / `cfg.RETRIEVAL_*` **in-process** — the same single surface, not a
parallel env channel.

## Safety nets already in place (you don't have to do anything)

- **`eval_run.py` runs the same check automatically** before each pair
  (Step 2.5). A contaminated pair is **skipped with a loud reason**
  instead of producing a misleading score. Override only if you know
  what you're doing: `EVAL_SKIP_GRAPH_GUARD=1`.
- **`setup_and_archive.py` refuses to archive** a live tree whose tools
  don't match the graph — so a poisoned archive can't be created in the
  first place.

## If a pair is contaminated

```bash
# Shrink EVAL_PAIRS in eval_config.py to just that one pair, then:
python scripts/setup_and_archive.py     # no arguments — it reads EVAL_PAIRS
# (positional args are intentionally rejected, so the CLI and eval_config
#  can never disagree about what was set up.)

# Confirm it's green, then run.
python verify_setup.py
```

## Do / don't

- **Do** run `verify_setup.py` after any manual fiddling with
  `generated/`, `schema_data/`, or the `setup_artifacts/` archives.
- **Do** use `SHARDS` for intra-graph parallelism instead of launching
  concurrent `eval_run.py` processes — the live tree is shared, so two
  `eval_run.py` runs (different graphs, **or two people on the same
  checkout/machine**) will fight over it and corrupt each other's scores.
- **Don't** hand-edit or hand-copy archive files. Use
  `setup_and_archive.py`, which validates before writing.
- **Don't** trust a low score at face value. If value-linking looks dead
  but FCAV works, suspect contamination and run the pre-flight.
