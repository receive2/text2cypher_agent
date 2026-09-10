#!/usr/bin/env python3
"""Stage-2b: interaction check for the bundled tuned config on the dev graph.

Stage-2 tested each candidate in isolation. levk20 (+1.3) and budget_lean (+1.0)
were never run together, so their combination could interact. This cell runs the
full bundle on the same dev slice before any test-graph spend.
"""
import json, shutil, sys, time, os, statistics
from pathlib import Path
REPO = "/Users/q0w01lh/Documents/repo/t2c"; sys.path.insert(0, REPO); os.chdir(REPO)
import eval_config as cfg, eval_run

PAIR = ("cypherbench_augmented", "terrorist_attack")
DEV = os.path.expanduser("~/datasets/cypherbench_augmented_dev/train.json")
OUT = Path(REPO)/"logs"/"tune"; OUT.mkdir(parents=True, exist_ok=True)

BASE = dict(METHOD="cyanchor", TOOL_TYPE="node_rel",
    RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
    CYPHER_SEMANTIC_REPAIR=True, CYPHER_EMPTY_IS_WRONG=True,
    PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=True, PLAN_EXEC_VALUE_SNAP=True,
    PLAN_EXEC_TOOLS_PER_ENTITY=2, PLAN_EXEC_VALUES_PER_TOOL=10,
    RETRIEVAL_LEVENSHTEIN_K=10, PLAN_EXEC_ROUTE_FETCH=6,
    PLAN_EXEC_MAX_ITER=3, PLAN_EXEC_ESCALATE_BUDGET=(5,3,1))

# the full candidate bundle: fuzzy candidates trimmed, lev arm deepened,
# escalation budget leaned
TUNED = {"PLAN_EXEC_VALUES_PER_TOOL": 5, "RETRIEVAL_LEVENSHTEIN_K": 20,
         "PLAN_EXEC_ESCALATE_BUDGET": (3,2,1)}

def newest():
    d=sorted(Path(REPO,"logs/runs").glob(f"{PAIR[0]}__{PAIR[1]}__cyanchor_*"), key=lambda p:p.stat().st_mtime)
    return d[-1] if d else None

for name, ov in [("tuned_bundle", TUNED)]:
    dest = OUT/f"ta__{name}__s2_400"
    if dest.exists(): print(f"SKIP {name}", flush=True); continue
    for k,v in BASE.items(): setattr(cfg,k,v)
    for k,v in ov.items():   setattr(cfg,k,v)
    cfg.EVAL_PAIRS=[PAIR]; cfg.CYPHERBENCH_AUGMENTED_PATH=DEV
    cfg.LIMIT=400; cfg.VERBOSE=False; cfg.SHARDS=1
    print(f"START {name} {ov}", flush=True); t0=time.time()
    try: rc=eval_run.main()
    except Exception as e: print(f"FAIL {name}: {e}", flush=True); continue
    d=newest()
    if rc!=0 or d is None: print(f"FAIL {name}: rc={rc}", flush=True); continue
    s=json.load(open(d/"summary.json")); kn=s.get("run_config",{}).get("knobs",{})
    shutil.move(str(d),str(dest))
    recs=[json.loads(l) for l in open(dest/"records.jsonl")]
    lat=statistics.mean([r["elapsed_agent_sec"] for r in recs if r.get("elapsed_agent_sec")])
    print(f"DONE {name} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} lat={lat:.1f}s t={(time.time()-t0)/60:.0f}m "
          f"vpt={kn.get('PLAN_EXEC_VALUES_PER_TOOL')} levk={kn.get('RETRIEVAL_LEVENSHTEIN_K')} "
          f"budget={kn.get('PLAN_EXEC_ESCALATE_BUDGET')}", flush=True)
print("BUNDLE CHECK COMPLETE", flush=True)
