#!/usr/bin/env python3
"""Dev-graph decision sweep: (cypherbench_augmented, terrorist_attack), train-split dev set."""
import json, shutil, sys, time
from pathlib import Path

REPO = "/Users/q0w01lh/Documents/repo/t2c"
sys.path.insert(0, REPO)
import os
os.chdir(REPO)

import eval_config as cfg
import eval_run

PAIR = ("cypherbench_augmented", "terrorist_attack")
DEV_PATH = os.path.expanduser("~/datasets/cypherbench_augmented_dev/train.json")
OUT = Path(REPO) / "logs" / "dev_sweep"
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

def newest_run_dir():
    dirs = sorted(Path(REPO, "logs/runs").glob(f"{PAIR[0]}__{PAIR[1]}__cyanchor_*"),
                  key=lambda p: p.stat().st_mtime)
    return dirs[-1] if dirs else None

for name, overrides in VARIANTS:
    dest = OUT / f"ta__{name}__dev400"
    if dest.exists():
        print(f"SKIP {name} (already at {dest})", flush=True)
        continue
    for k, v in DEFAULTS.items():
        setattr(cfg, k, v)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    cfg.EVAL_PAIRS = [PAIR]
    cfg.CYPHERBENCH_AUGMENTED_PATH = DEV_PATH
    cfg.LIMIT = LIMIT
    cfg.VERBOSE = False
    cfg.SHARDS = 1
    print(f"START {name} overrides={overrides}", flush=True)
    t0 = time.time()
    try:
        rc = eval_run.main()
    except Exception as exc:
        print(f"FAIL {name}: {exc}", flush=True)
        continue
    mins = (time.time() - t0) / 60
    d = newest_run_dir()
    if rc != 0 or d is None:
        print(f"FAIL {name}: rc={rc} dir={d}", flush=True)
        continue
    s = json.load(open(d / "summary.json"))
    shutil.move(str(d), str(dest))
    print(f"DONE {name} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} n={s['n']} err={s['n_errors']} t={mins:.0f}m -> {dest.name}", flush=True)

print("DEV SWEEP COMPLETE", flush=True)
