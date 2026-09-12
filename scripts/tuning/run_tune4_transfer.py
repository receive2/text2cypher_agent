#!/usr/bin/env python3
"""Stage-3: transfer REPORT of the dev-selected config on two test graphs.

Protocol (pre-committed):
  * the config is chosen HERE from dev-graph results only (logs/tune/):
    whichever of `combo` / `tuned_bundle` has the higher dev EA; tie -> bundle
    (cheaper escalation budget). No test-graph result feeds back into this choice.
  * test graphs are run ONCE and reported as-is against the August baselines
    (logs/verify_cols/{healthcare,pole}__full__v400), which were run on the
    v2.1 copies under ~/datasets — so the dataset paths are pinned to those same
    files (same rows, same LIMIT=400 prefix) for an apples-to-apples pairing.
  * these are tuning-report numbers on v2.1; the paper's main table is re-run
    on the v2.2 release with whatever config is frozen.
"""
import json, shutil, sys, time, os, statistics
from pathlib import Path
REPO = "/Users/q0w01lh/Documents/repo/t2c"; sys.path.insert(0, REPO); os.chdir(REPO)
import eval_config as cfg, eval_run

H = os.path.expanduser
OUT = Path(REPO)/"logs"/"tune_transfer"; OUT.mkdir(parents=True, exist_ok=True)
LIMIT = 400

BASE = dict(METHOD="cyanchor", TOOL_TYPE="node_rel",
    RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
    CYPHER_SEMANTIC_REPAIR=True, CYPHER_EMPTY_IS_WRONG=True,
    PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=True, PLAN_EXEC_VALUE_SNAP=True,
    PLAN_EXEC_TOOLS_PER_ENTITY=2, PLAN_EXEC_VALUES_PER_TOOL=10,
    RETRIEVAL_LEVENSHTEIN_K=10, PLAN_EXEC_ROUTE_FETCH=6,
    PLAN_EXEC_MAX_ITER=3, PLAN_EXEC_ESCALATE_BUDGET=(5,3,1))

CANDIDATES = {
    "combo":        {"PLAN_EXEC_VALUES_PER_TOOL": 5, "RETRIEVAL_LEVENSHTEIN_K": 20},
    "tuned_bundle": {"PLAN_EXEC_VALUES_PER_TOOL": 5, "RETRIEVAL_LEVENSHTEIN_K": 20,
                     "PLAN_EXEC_ESCALATE_BUDGET": (3,2,1)},
}

def dev_ea(name):
    p = Path(REPO)/"logs"/"tune"/f"ta__{name}__s2_400"/"summary.json"
    return json.load(open(p))["ea"] if p.exists() else None

# ── dev-only selection ─────────────────────────────────────────────────────
scores = {k: dev_ea(k) for k in CANDIDATES}
print(f"DEV SCORES {scores}", flush=True)
avail = {k: v for k, v in scores.items() if v is not None}
if not avail:
    print("ABORT: no dev candidate results found", flush=True); sys.exit(1)
best = max(avail, key=lambda k: (avail[k], k == "tuned_bundle"))
CHOSEN = CANDIDATES[best]
print(f"SELECTED {best} {CHOSEN}", flush=True)

# (tag, dataset, graph, path-attr, v2.1 file)  — pinned to the baseline's data
PAIRS = [
    ("healthcare", "mindthequery_augmented", "healthcare",
     "MINDTHEQUERY_AUGMENTED_PATH", H("~/datasets/mindthequery_augmented_v2/test.json")),
    ("pole",       "zograscope_augmented",  "pole",
     "ZOGRASCOPE_AUGMENTED_PATH",   H("~/datasets/zograscope_augmented_v2/test.json")),
]

def newest(ds, g):
    d = sorted(Path(REPO,"logs/runs").glob(f"{ds}__{g}__cyanchor_*"), key=lambda p: p.stat().st_mtime)
    return d[-1] if d else None

for tag, ds, graph, attr, path in PAIRS:
    dest = OUT/f"{tag}__{best}__v400"
    if dest.exists(): print(f"SKIP {tag}", flush=True); continue
    for k,v in BASE.items():   setattr(cfg,k,v)
    for k,v in CHOSEN.items(): setattr(cfg,k,v)
    setattr(cfg, attr, path)
    cfg.EVAL_PAIRS=[(ds, graph)]; cfg.LIMIT=LIMIT; cfg.VERBOSE=False; cfg.SHARDS=1
    print(f"START {tag}/{best} data={path}", flush=True); t0=time.time()
    try: rc=eval_run.main()
    except Exception as e: print(f"FAIL {tag}: {e}", flush=True); continue
    d=newest(ds, graph)
    if rc!=0 or d is None: print(f"FAIL {tag}: rc={rc}", flush=True); continue
    s=json.load(open(d/"summary.json")); kn=s.get("run_config",{}).get("knobs",{})
    shutil.move(str(d), str(dest))
    recs=[json.loads(l) for l in open(dest/"records.jsonl")]
    _lv=[r.get("elapsed_agent_sec") for r in recs if r.get("elapsed_agent_sec")]
    # newer harness records carry no per-example timing; fall back to wall/n
    lat=statistics.mean(_lv) if _lv else s.get("elapsed_sec",0)/max(s.get("n",1),1)
    print(f"DONE {tag}/{best} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} lat={lat:.1f}s err={s['n_errors']} "
          f"t={(time.time()-t0)/60:.0f}m vpt={kn.get('PLAN_EXEC_VALUES_PER_TOOL')} "
          f"levk={kn.get('RETRIEVAL_LEVENSHTEIN_K')} budget={kn.get('PLAN_EXEC_ESCALATE_BUDGET')}", flush=True)
print("TRANSFER REPORT COMPLETE", flush=True)
