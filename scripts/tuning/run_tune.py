#!/usr/bin/env python3
"""Stage-1 coordinate-descent screening on the dev graph (terrorist_attack).

One factor at a time around the shipped defaults, LIMIT=200 for speed.
Decisions are made ONLY here (CypherBench train split) — never on test graphs.
"""
import json, shutil, sys, time, os
from pathlib import Path

REPO = "/Users/q0w01lh/Documents/repo/t2c"
sys.path.insert(0, REPO)
os.chdir(REPO)
import eval_config as cfg
import eval_run

PAIR = ("cypherbench_augmented", "terrorist_attack")
DEV_PATH = os.path.expanduser("~/datasets/cypherbench_augmented_dev/train.json")
OUT = Path(REPO) / "logs" / "tune"; OUT.mkdir(parents=True, exist_ok=True)
LIMIT = int(os.getenv("TUNE_LIMIT", "200"))
SUF = os.getenv("TUNE_SUFFIX", f"s1_{LIMIT}")

BASE = dict(
    METHOD="cyanchor", TOOL_TYPE="node_rel",
    RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
    CYPHER_SEMANTIC_REPAIR=True, CYPHER_EMPTY_IS_WRONG=True,
    PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=True, PLAN_EXEC_VALUE_SNAP=True,
    PLAN_EXEC_TOOLS_PER_ENTITY=2, PLAN_EXEC_VALUES_PER_TOOL=10,
    RETRIEVAL_LEVENSHTEIN_K=10, PLAN_EXEC_ROUTE_FETCH=6,
    PLAN_EXEC_MAX_ITER=3, PLAN_EXEC_ESCALATE_BUDGET=(5,3,1),
)

VARIANTS = [("base", {})]
for k, vals in [
    ("PLAN_EXEC_VALUES_PER_TOOL",  [5, 20]),
    ("PLAN_EXEC_TOOLS_PER_ENTITY", [1, 3]),
    ("RETRIEVAL_LEVENSHTEIN_K",    [5, 20]),
    ("PLAN_EXEC_ROUTE_FETCH",      [3, 10]),
]:
    for v in vals:
        VARIANTS.append((f"{k.replace('PLAN_EXEC_','').replace('RETRIEVAL_','').lower()}{v}", {k: v}))

def newest():
    d = sorted(Path(REPO, "logs/runs").glob(f"{PAIR[0]}__{PAIR[1]}__cyanchor_*"),
               key=lambda p: p.stat().st_mtime)
    return d[-1] if d else None

for name, ov in VARIANTS:
    dest = OUT / f"ta__{name}__{SUF}"
    if dest.exists():
        print(f"SKIP {name}", flush=True); continue
    for k, v in BASE.items(): setattr(cfg, k, v)
    for k, v in ov.items():   setattr(cfg, k, v)
    cfg.EVAL_PAIRS = [PAIR]; cfg.CYPHERBENCH_AUGMENTED_PATH = DEV_PATH
    cfg.LIMIT = LIMIT; cfg.VERBOSE = False; cfg.SHARDS = 1
    print(f"START {name} {ov}", flush=True)
    t0 = time.time()
    try:
        rc = eval_run.main()
    except Exception as e:
        print(f"FAIL {name}: {e}", flush=True); continue
    d = newest()
    if rc != 0 or d is None:
        print(f"FAIL {name}: rc={rc}", flush=True); continue
    s = json.load(open(d / "summary.json"))
    knobs = s.get("run_config", {}).get("knobs", {})
    shutil.move(str(d), str(dest))
    import statistics
    recs = [json.loads(l) for l in open(dest / "records.jsonl")]
    lat = statistics.mean([r["elapsed_agent_sec"] for r in recs if r.get("elapsed_agent_sec")])
    print(f"DONE {name} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} lat={lat:.1f}s "
          f"t={(time.time()-t0)/60:.0f}m vpt={knobs.get('PLAN_EXEC_VALUES_PER_TOOL')} "
          f"tpe={knobs.get('PLAN_EXEC_TOOLS_PER_ENTITY')} levk={knobs.get('RETRIEVAL_LEVENSHTEIN_K')} "
          f"rf={knobs.get('PLAN_EXEC_ROUTE_FETCH')}", flush=True)

print("TUNE STAGE1 COMPLETE", flush=True)
