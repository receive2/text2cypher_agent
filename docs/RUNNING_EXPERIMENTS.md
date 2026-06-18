# Running experiments safely (multi-dataset, multi-graph)

This is the procedure for anyone running the t2c eval harness across
several datasets and graphs. You do **not** need to understand the
internals — follow the steps and read the pre-flight table.

## The one thing to understand

The harness keeps **one live copy** of each graph's setup artifacts
(node tools, schema, prompts, FAISS indexes, FCAV index) and **swaps**
the right archive into those same files before each `(dataset, graph)`
is evaluated. This is fast, but it means the live tree is shared global
state: if the wrong archive is live — because a setup was interrupted,
or someone re-archived by hand at the wrong moment — the eval runs
against the **wrong tools** and silently scores near zero (the
"no-value-linking" floor). Nothing in the *score* tells you it was wrong.

**Tell-tale sign of this bug:** value-linking modes (ReAct / Plan&Exec)
collapse to roughly the no-val-link score, while **FCAV still scores
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

## Standard run procedure

```bash
# 1. Pick the slice to run — edit EVAL_PAIRS in eval_config.py.

# 2. Pre-flight. Stop here and fix anything that is not green.
python verify_setup.py

# 3. Run. Set the four value-linking axes via env; OUT_DIR is in eval_config.py.
VAL_LINK_MODE=val_link AGENT_TYPE=plan_exec RETRIEVAL_TYPE=fuzzy TOOL_TYPE=node_rel \
  python eval_run.py

# 4. Aggregate.
python eval_aggregate.py
```

The four axes (defaults in `config.py`):

| Axis             | Values                       |
|------------------|------------------------------|
| `VAL_LINK_MODE`  | `no_val_link` · `fcav` · `val_link` |
| `AGENT_TYPE`     | `react` · `plan_exec`        |
| `RETRIEVAL_TYPE` | `fuzzy` · `hybrid`           |
| `TOOL_TYPE`      | `node` · `node_rel`          |

`AGENT_TYPE` / `RETRIEVAL_TYPE` / `TOOL_TYPE` only apply when
`VAL_LINK_MODE=val_link` (they're ignored for `no_val_link` / `fcav`).

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
- **Do** run one `(dataset, graph)` at a time when unsure — the live
  tree is shared, so concurrent `eval_run.py` processes on different
  graphs will fight over it.
- **Don't** hand-edit or hand-copy archive files. Use
  `setup_and_archive.py`, which validates before writing.
- **Don't** trust a low score at face value. If value-linking looks dead
  but FCAV works, suspect contamination and run the pre-flight.
