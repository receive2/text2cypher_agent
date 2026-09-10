#!/usr/bin/env python3
"""Cross-family verification of the two pending components.

healthcare (Mind-the-Query) and pole (ZOGRASCOPE) — different benchmark
families from the CypherBench graphs used so far. pole is typo-heavy
(value-snap's designed home turf); MTQ is a different family entirely.
Reports full reference + the two ablations per graph.
"""
import json, shutil, sys, time
from pathlib import Path

REPO = "/Users/q0w01lh/Documents/repo/t2c"
sys.path.insert(0, REPO)
import os
os.chdir(REPO)

import eval_config as cfg
import eval_run

OUT = Path(REPO) / "logs" / "verify_cols"
OUT.mkdir(parents=True, exist_ok=True)
LIMIT = 400

DEFAULTS = dict(
    METHOD="cyanchor", TOOL_TYPE="node_rel",
    RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
    CYPHER_SEMANTIC_REPAIR=True, CYPHER_EMPTY_IS_WRONG=True,
    PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=True, PLAN_EXEC_VALUE_SNAP=True,
)

VARIANTS = [
    ("full",            {}),
    ("empty_not_wrong", {"CYPHER_EMPTY_IS_WRONG": False}),
    ("no_value_snap",   {"PLAN_EXEC_VALUE_SNAP": False}),
    ("node_tools_only", {"TOOL_TYPE": "node"}),
]

# (tag, dataset, graph) — pole first: it is the decisive test for value-snap
PAIRS = [
    ("healthcare", "mindthequery_augmented", "healthcare"),
    ("pole",       "zograscope_augmented",  "pole"),
]

def newest_run_dir(ds, g):
    dirs = sorted(Path(REPO, "logs/runs").glob(f"{ds}__{g}__cyanchor_*"),
                  key=lambda p: p.stat().st_mtime)
    return dirs[-1] if dirs else None

for tag, ds, graph in PAIRS:
    for name, overrides in VARIANTS:
        dest = OUT / f"{tag}__{name}__v400"
        if dest.exists():
            print(f"SKIP {tag}/{name}", flush=True)
            continue
        for k, v in DEFAULTS.items():
            setattr(cfg, k, v)
        for k, v in overrides.items():
            setattr(cfg, k, v)
        cfg.EVAL_PAIRS = [(ds, graph)]
        cfg.LIMIT = LIMIT
        cfg.VERBOSE = False
        cfg.SHARDS = 1
        print(f"START {tag}/{name} overrides={overrides}", flush=True)
        t0 = time.time()
        try:
            rc = eval_run.main()
        except Exception as exc:
            print(f"FAIL {tag}/{name}: {exc}", flush=True)
            continue
        mins = (time.time() - t0) / 60
        d = newest_run_dir(ds, graph)
        if rc != 0 or d is None:
            print(f"FAIL {tag}/{name}: rc={rc} dir={d}", flush=True)
            continue
        s = json.load(open(d / "summary.json"))
        shutil.move(str(d), str(dest))
        print(f"DONE {tag}/{name} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} n={s['n']} err={s['n_errors']} t={mins:.0f}m", flush=True)

print("VERIFY COLS COMPLETE", flush=True)
