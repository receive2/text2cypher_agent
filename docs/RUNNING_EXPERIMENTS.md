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
  Re-run `python scripts/setup_and_archive.py <dataset> <graph> --force`.
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
| `EVAL_PAIRS` | `[(dataset, graph), …]` | Which pairs to run (below `GRAPH_CONNS`). |
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

## Where results land

Each invocation writes a **fresh, timestamped per-run directory** (see
`eval_paths.py`, the single source of truth for this layout):

```
logs/runs/<dataset>__<graph>__<method>__<YYYYMMDD-HHMMSS>/records.jsonl  # one record per example
logs/runs/<dataset>__<graph>__<method>__<YYYYMMDD-HHMMSS>/summary.json   # aggregate + run_meta + run_config
```

The method (`graphrag`, `cyanchor_fl`, …) is **part of the path** and every
invocation gets its **own timestamp**, so re-running — with a different
`METHOD`, a different LLM, or different knobs — never clobbers earlier
records. The dir name deliberately carries no model/config information;
what actually ran (LLM per stage, embedding backend, every ablation knob) is
recorded inside `summary.json` under `run_config`, making each run dir
self-describing. Readers resolve a triple's **newest** run via
`eval_paths.latest_run_dir` (pre-timestamp legacy dirs
`logs/runs/<dataset>__<graph>__<method>/` are still recognised as a
fallback). `eval_aggregate.py` aggregates only the newest run per
`(dataset, graph, method)` and groups by `(dataset, method)`.

## Producing the per-graph comparison reports

The committed `report/<dataset>/<graph>.md` tables (Overall + by perturbation
strategy + by difficulty, EA & PSJS, across all five methods) are rendered from
`logs/runs/` — no prefix map, locations resolved through `eval_paths`:

```bash
# One graph (args: <graph> <report_dir> <label> <dataset_key> [date]):
python gen_graph_report.py movie CypherBench CypherBench cypherbench_augmented

# Dataset-pooled summary across graphs:
python gen_pooled_report.py report/CypherBench/_summary.md CypherBench \
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
# Rebuild that one pair's artifacts from its schema and re-archive it.
python scripts/setup_and_archive.py <dataset> <graph> --force

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
