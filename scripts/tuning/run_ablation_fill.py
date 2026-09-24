#!/usr/bin/env python3
"""Fill the missing cells of the paper's component-ablation table (tab:ablation-components).

Cells (all gpt-4.1, SHARDS=1, sequential, idempotent — rerun to resume):
  healthcare, pole            : − escalation | − select-or-abstain judge | − semantic repair   (6)
  flight_accident, healthcare, pole : fuzzy arm only | lev arm only                          (6)
  --with-joint                : − all correction (escalation+judge+repair+value-snap off)    (3, optional)
  + vector arm is NOT here: the archives carry no embeddings (EMBEDDABLE_PROPERTIES=[]).

Pairing: every cell must be scored per question against the EXISTING reference runs
(logs/ablation/fa__full__full_20260823, logs/verify_cols/{healthcare,pole}__full__v400),
so this driver pins the same data files (~/datasets v2.1 copies) and the same LIMIT
prefixes, and uses the same reference configuration (every component on).
Score afterwards with scripts/tuning/score_ablation.py.
"""
import json, os, shutil, socket, subprocess, sys, time
from pathlib import Path

REPO = Path("/Users/q0w01lh/Documents/repo/t2c"); sys.path.insert(0, str(REPO)); os.chdir(REPO)
import eval_config as cfg, eval_run   # noqa: E402

H = os.path.expanduser
OUT = REPO / "logs" / "ablation_fill"; OUT.mkdir(parents=True, exist_ok=True)
WITH_JOINT = "--with-joint" in sys.argv

# Reference configuration = the configuration the existing reference cells were run with.
BASE = dict(METHOD="cyanchor", TOOL_TYPE="node_rel",
            RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
            CYPHER_SEMANTIC_REPAIR=True, CYPHER_EMPTY_IS_WRONG=True,
            PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=True, PLAN_EXEC_VALUE_SNAP=True,
            GENERATOR_LLM="gpt-4.1")

VARIANTS = {
    "no_escalate":        {"PLAN_EXEC_ESCALATE": False},
    "no_select_judge":    {"PLAN_EXEC_SELECT_JUDGE": False},
    "no_semantic_repair": {"CYPHER_SEMANTIC_REPAIR": False},
    "fuzzy_only":         {"RETRIEVAL_LEVENSHTEIN": False},
    "lev_only":           {"RETRIEVAL_FUZZY": False},
    "no_correction":      {"PLAN_EXEC_ESCALATE": False, "PLAN_EXEC_SELECT_JUDGE": False,
                           "CYPHER_SEMANTIC_REPAIR": False, "PLAN_EXEC_VALUE_SNAP": False},
}
# (tag, dataset, graph, path attr, pinned data file, LIMIT, port)
GRAPHS = {
    "flight_accident": ("cypherbench_augmented",  "flight_accident", "CYPHERBENCH_AUGMENTED_PATH",
                        H("~/datasets/cypherbench_augmented_v2/test.json"),  None, 15064),
    "healthcare":      ("mindthequery_augmented", "healthcare",      "MINDTHEQUERY_AUGMENTED_PATH",
                        H("~/datasets/mindthequery_augmented_v2/test.json"), 400,  15074),
    "pole":            ("zograscope_augmented",   "pole",            "ZOGRASCOPE_AUGMENTED_PATH",
                        H("~/datasets/zograscope_augmented_v2/test.json"),   400,  15076),
}
PLAN = [(g, v) for v in ("no_escalate", "no_select_judge", "no_semantic_repair") for g in ("healthcare", "pole")]
PLAN += [(g, v) for v in ("fuzzy_only", "lev_only") for g in ("flight_accident", "healthcare", "pole")]
if WITH_JOINT: PLAN += [(g, "no_correction") for g in ("flight_accident", "healthcare", "pole")]

# ── pre-flight: VM reachable, no other eval running from THIS checkout (single live tree) ──
def port_open(p):
    s = socket.socket(); s.settimeout(3)
    try: s.connect(("34.9.85.21", p)); return True
    except Exception: return False
    finally: s.close()
closed = [p for *_, p in GRAPHS.values() if not port_open(p)]
if closed:
    print(f"ABORT: VM ports closed {closed} — VPN on, or VM down. Nothing started.", flush=True); sys.exit(2)
for f in (v[3] for v in GRAPHS.values()):
    if not os.path.isfile(f): print(f"ABORT: pinned data file missing: {f}", flush=True); sys.exit(2)
try:
    pids = subprocess.run(["pgrep", "-f", "eval._worker"], capture_output=True, text=True).stdout.split()
    for pid in pids:
        cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if str(REPO) in cwd:
            print(f"ABORT: another eval worker (pid {pid}) is running from this checkout — the live tree is shared.", flush=True); sys.exit(2)
except FileNotFoundError:
    pass

def newest(ds, g):
    d = sorted((REPO / "logs/runs").glob(f"{ds}__{g}__cyanchor_*"), key=lambda p: p.stat().st_mtime)
    return d[-1] if d else None

print(f"PLAN {len(PLAN)} cells: " + ", ".join(f"{g}/{v}" for g, v in PLAN), flush=True)
for g, v in PLAN:
    ds, graph, attr, path, limit, _ = GRAPHS[g]
    dest = OUT / f"{g}__{v}__{'full' if limit is None else f'v{limit}'}"
    if dest.exists(): print(f"SKIP {g}/{v}", flush=True); continue
    for k, x in BASE.items(): setattr(cfg, k, x)
    for k, x in VARIANTS[v].items(): setattr(cfg, k, x)
    setattr(cfg, attr, path)
    cfg.EVAL_PAIRS = [(ds, graph)]; cfg.LIMIT = limit; cfg.VERBOSE = False; cfg.SHARDS = 1
    print(f"START {g}/{v} {VARIANTS[v]} data={path} limit={limit}", flush=True); t0 = time.time()
    try: rc = eval_run.main()
    except Exception as e: print(f"FAIL {g}/{v}: {e}", flush=True); continue
    d = newest(ds, graph)
    if rc != 0 or d is None: print(f"FAIL {g}/{v}: rc={rc} dir={d}", flush=True); continue
    s = json.load(open(d / "summary.json")); kn = s.get("run_config", {}).get("knobs", {})
    bad = [k for k, x in VARIANTS[v].items() if kn.get(k) != ("1" if x else "0")]
    if bad: print(f"FAIL {g}/{v}: knobs not applied {bad} — cell left in logs/runs, NOT moved", flush=True); continue
    shutil.move(str(d), str(dest))
    print(f"DONE {g}/{v} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} n={s['n']} err={s['n_errors']} t={(time.time()-t0)/60:.0f}m", flush=True)
print("ABLATION FILL COMPLETE", flush=True)
