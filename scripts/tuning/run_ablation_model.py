#!/usr/bin/env python3
"""Component ablation for one generator backbone on the v2.3 release (tab:ablation-components).

    python scripts/tuning/run_ablation_model.py --model gpt-5.6-luna [--graphs pole,healthcare] [--with-joint] [--skip-ref]

Per graph: reference (shipped configuration) → 5 component removals → 2 retrieval-arm
variants [→ joint removal]. Data = benchmarks/ (the release eval_config already points at);
flight_accident and healthcare run in full, pole on its first 400 questions (prefix is
category-balanced). Output logs/ablation_<model>/<graph>__<variant>. Idempotent — rerun to
resume; --graphs lets one checkout per graph run in parallel (the live tree is per checkout).
`+ vector arm` is not included: the archives carry no embeddings.
"""
import argparse, json, os, shutil, socket, subprocess, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent.parent; sys.path.insert(0, str(REPO)); os.chdir(REPO)
import eval_config as cfg, eval_run  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("--model", required=True)
ap.add_argument("--graphs", default="flight_accident,healthcare,pole"); ap.add_argument("--with-joint", action="store_true")
ap.add_argument("--skip-ref", action="store_true", help="reference cells come from the model sweep instead")
A = ap.parse_args()
OUT = REPO / "logs" / f"ablation_{A.model}"; OUT.mkdir(parents=True, exist_ok=True)

SHIPPED = dict(METHOD="cyanchor", TOOL_TYPE="node_rel", RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
               CYPHER_SEMANTIC_REPAIR=True, PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=True, PLAN_EXEC_VALUE_SNAP=True,
               GENERATOR_LLM=A.model)   # CYPHER_EMPTY_IS_WRONG stays at the panel's shipped default
VARIANTS = {"reference": {},
            "no_escalate": {"PLAN_EXEC_ESCALATE": False}, "no_select_judge": {"PLAN_EXEC_SELECT_JUDGE": False},
            "no_semantic_repair": {"CYPHER_SEMANTIC_REPAIR": False}, "no_value_snap": {"PLAN_EXEC_VALUE_SNAP": False},
            "node_tools_only": {"TOOL_TYPE": "node"},
            "fuzzy_only": {"RETRIEVAL_LEVENSHTEIN": False}, "lev_only": {"RETRIEVAL_FUZZY": False},
            "no_correction": {"PLAN_EXEC_ESCALATE": False, "PLAN_EXEC_SELECT_JUDGE": False, "CYPHER_SEMANTIC_REPAIR": False, "PLAN_EXEC_VALUE_SNAP": False}}
GRAPHS = {"flight_accident": ("cypherbench_augmented", "flight_accident", None, 15064),
          "healthcare":      ("mindthequery_augmented", "healthcare",     None, 15074),
          "pole":            ("zograscope_augmented",   "pole",           400,  15076)}
order = [v for v in VARIANTS if v != "no_correction" and not (A.skip_ref and v == "reference")] + (["no_correction"] if A.with_joint else [])
PLAN = [(g, v) for g in A.graphs.split(",") for v in order]

def port_open(p):
    s = socket.socket(); s.settimeout(3)
    try: s.connect(("34.9.85.21", p)); return True
    except Exception: return False
    finally: s.close()
closed = [GRAPHS[g][3] for g in A.graphs.split(",") if not port_open(GRAPHS[g][3])]
if closed: print(f"ABORT: VM ports closed {closed} — VPN on or VM down. Nothing started.", flush=True); sys.exit(2)
for pid in subprocess.run(["pgrep", "-f", "eval._worker"], capture_output=True, text=True).stdout.split():
    if str(REPO) in subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout:
        print(f"ABORT: eval worker pid {pid} already runs from this checkout (shared live tree).", flush=True); sys.exit(2)

def newest(ds, g):
    d = sorted((REPO / "logs/runs").glob(f"{ds}__{g}__cyanchor_*"), key=lambda p: p.stat().st_mtime); return d[-1] if d else None

print(f"PLAN model={A.model} {len(PLAN)} cells: " + ", ".join(f"{g}/{v}" for g, v in PLAN), flush=True)
for g, v in PLAN:
    ds, graph, limit, _ = GRAPHS[g]; dest = OUT / f"{g}__{v}"
    if dest.exists(): print(f"SKIP {g}/{v}", flush=True); continue
    for k, x in SHIPPED.items(): setattr(cfg, k, x)
    for k, x in VARIANTS[v].items(): setattr(cfg, k, x)
    cfg.EVAL_PAIRS = [(ds, graph)]; cfg.LIMIT = limit; cfg.VERBOSE = False; cfg.SHARDS = 1
    print(f"START {g}/{v} {VARIANTS[v]} limit={limit}", flush=True); t0 = time.time()
    try: rc = eval_run.main()
    except Exception as e: print(f"FAIL {g}/{v}: {e}", flush=True); continue
    d = newest(ds, graph)
    if rc != 0 or d is None: print(f"FAIL {g}/{v}: rc={rc}", flush=True); continue
    s = json.load(open(d / "summary.json")); kn = s.get("run_config", {}).get("knobs", {}); llm = s.get("run_config", {}).get("llm", {})
    want = {k: (x if isinstance(x, str) else ("1" if x else "0")) for k, x in VARIANTS[v].items()}
    bad = [k for k, x in want.items() if kn.get(k) != x] + ([] if llm.get("generator_llm") == A.model else ["GENERATOR_LLM"])
    if bad: print(f"FAIL {g}/{v}: not applied {bad} — left in logs/runs, NOT moved", flush=True); continue
    shutil.move(str(d), str(dest))
    print(f"DONE {g}/{v} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} n={s['n']} err={s['n_errors']} t={(time.time()-t0)/60:.0f}m", flush=True)
print("ABLATION COMPLETE", flush=True)
