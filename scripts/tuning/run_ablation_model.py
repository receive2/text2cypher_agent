#!/usr/bin/env python3
"""Component ablation for one generator backbone on the v2.3 release (tab:ablation-components).

    python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --pole-full \
        [--graphs flight_accident,nba,healthcare,pole] [--variants a,b] [--with-joint] [--limit 3]

The reference cell is the released configuration: CyANCHOR routing on node-property tools
(relation tools off), fuzzy + Levenshtein arms, escalation, select-or-abstain judge, semantic
repair and value-snap on. --judge off / --scope node_rel give other references. Every other
cell flips exactly one switch; the five default cells are no_value_snap, fuzzy_only,
no_escalate, no_semantic_repair and lev_only. The judge cell (no_select_judge / select_judge)
and the tool-scope cell (rel_tools / node_tools_only) are not run by default — neither has a
measurable main effect and neither is a row of the paper table — but stay available through
--variants.
Data = benchmarks/ (the release eval_config already points at). flight_accident, healthcare
and nba run in full; pole runs its first 400 questions, or all of them with --pole-full
(cells are then named pole_full__*).

Output: logs/ablation_<model>__judge-<on|off>-<node|node_rel>/<graph>__<variant> — one root per
reference configuration, so cells of different references are never paired by mistake.
Idempotent: rerun the same command to resume (finished cells are skipped, an interrupted
cell starts over). --graphs lets one checkout per graph run in parallel (the live tree is
per checkout). --limit N is a smoke test and writes to a separate ...__smokeN root.
`+ vector arm` is not included: the archives carry no embeddings.
"""
import argparse, json, os, shutil, socket, subprocess, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent.parent; sys.path.insert(0, str(REPO)); os.chdir(REPO)
import eval_config as cfg, eval_run  # noqa: E402
# The same per-question cap the sweep driver gives CyANCHOR (orchestrate_sweep.CYANCHOR_PER_EXAMPLE_TIMEOUT):
# the slowest legitimate questions take 70-120 s. Cells before 2026-09-30 ran under the 60 s default,
# which cost at most one question per graph (0 on nba, flight_accident, politics; 1 on movie).
os.environ.setdefault("EVAL_PER_EXAMPLE_TIMEOUT", "900")

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--judge", default="on", choices=("on", "off"), help="select-or-abstain judge in the reference configuration (released: on)")
ap.add_argument("--scope", default="node", choices=("node", "node_rel"), help="CyANCHOR tool scope in the reference configuration (released: node)")
ap.add_argument("--graphs", default="flight_accident,nba,healthcare,pole")
ap.add_argument("--variants", default="", help="comma list; default = reference + the six single-switch cells")
ap.add_argument("--pole-full", action="store_true", help="run pole on all its questions instead of the first 400")
ap.add_argument("--limit", type=int, default=0, help="smoke test: first N questions of every graph, separate output root")
ap.add_argument("--with-joint", action="store_true", help="add the cell with every corrective stage off")
ap.add_argument("--skip-ref", action="store_true", help="reference cells come from the model sweep instead")
A = ap.parse_args()
OUT = REPO / "logs" / (f"ablation_{A.model}__judge-{A.judge}-{A.scope}" + (f"__smoke{A.limit}" if A.limit else ""))
OUT.mkdir(parents=True, exist_ok=True)

JUDGE_ON = A.judge == "on"
SHIPPED = dict(METHOD="cyanchor", CYANCHOR_TOOL_SCOPE=A.scope, RETRIEVAL_FUZZY=True, RETRIEVAL_VECTOR=False, RETRIEVAL_LEVENSHTEIN=True,
               CYPHER_SEMANTIC_REPAIR=True, PLAN_EXEC_ESCALATE=True, PLAN_EXEC_SELECT_JUDGE=JUDGE_ON, PLAN_EXEC_VALUE_SNAP=True,
               GENERATOR_LLM=A.model)   # CYPHER_EMPTY_IS_WRONG stays at the panel's shipped default
JUDGE_CELL = ("no_select_judge", {"PLAN_EXEC_SELECT_JUDGE": False}) if JUDGE_ON else ("select_judge", {"PLAN_EXEC_SELECT_JUDGE": True})
SCOPE_CELL = ("node_tools_only", {"CYANCHOR_TOOL_SCOPE": "node"}) if A.scope == "node_rel" else ("rel_tools", {"CYANCHOR_TOOL_SCOPE": "node_rel"})
VARIANTS = {"reference": {},
            "no_value_snap": {"PLAN_EXEC_VALUE_SNAP": False}, "fuzzy_only": {"RETRIEVAL_LEVENSHTEIN": False},
            "no_escalate": {"PLAN_EXEC_ESCALATE": False}, "no_semantic_repair": {"CYPHER_SEMANTIC_REPAIR": False},
            JUDGE_CELL[0]: JUDGE_CELL[1], "lev_only": {"RETRIEVAL_FUZZY": False},
            SCOPE_CELL[0]: SCOPE_CELL[1],                                # not in the default plan, like the judge cell
            "no_correction": {"PLAN_EXEC_ESCALATE": False, "PLAN_EXEC_SELECT_JUDGE": False,
                              "CYPHER_SEMANTIC_REPAIR": False, "PLAN_EXEC_VALUE_SNAP": False}}
GRAPHS = {"flight_accident": ("cypherbench_augmented", "flight_accident", None, 15064),
          "healthcare":      ("mindthequery_augmented", "healthcare",     None, 15074),
          "pole":            ("zograscope_augmented",   "pole",           None if A.pole_full else 400, 15076),
          "nba":             ("cypherbench_augmented",  "nba",            None, 15067)}
CELL = lambda g: "pole_full" if (g == "pole" and A.pole_full) else g
order = [v.strip() for v in A.variants.split(",") if v.strip()] or [v for v in VARIANTS if v not in (SCOPE_CELL[0], "no_correction", JUDGE_CELL[0])]
order = [v for v in order if not (A.skip_ref and v == "reference")] + (["no_correction"] if A.with_joint and "no_correction" not in order else [])
unknown = [v for v in order if v not in VARIANTS] + [g for g in A.graphs.split(",") if g not in GRAPHS]
if unknown: print(f"ABORT: unknown variant/graph {unknown}; variants: {list(VARIANTS)}; graphs: {list(GRAPHS)}", flush=True); sys.exit(2)
PLAN = [(g, v) for g in A.graphs.split(",") for v in order]

def port_open(p):
    s = socket.socket(); s.settimeout(3)
    try: s.connect(("34.9.85.21", p)); return True
    except Exception: return False
    finally: s.close()
def bolt_ok(ds, graph):
    """A real query, not just an open port: behind a VPN or proxy the port can accept the TCP
    connection and still drop the Bolt traffic, and every cell would then fail one by one."""
    from neo4j import GraphDatabase
    c = cfg.GRAPH_CONNS[(ds.replace("_augmented", ""), graph)]
    try:
        with GraphDatabase.driver(c.uri, auth=(c.user, c.password), connection_timeout=8) as drv:
            with drv.session(database=c.database) as ses: ses.run("RETURN 1").consume()
        return True
    except Exception:
        return False
closed = [g for g in A.graphs.split(",") if not port_open(GRAPHS[g][3]) or not bolt_ok(*GRAPHS[g][:2])]
if closed: print(f"ABORT: graph database not answering for {closed} — VPN on or VM down. Nothing started.", flush=True); sys.exit(2)
def in_checkout(lsof_out, repo=REPO):
    """Is the working directory that `lsof -Fn` reports this checkout, or a folder inside it? Compared as paths:
    a substring test also matched a sibling checkout whose name starts the same (t2c and t2c_b)."""
    return any(Path(l[1:]) == repo or repo in Path(l[1:]).parents for l in lsof_out.splitlines() if l.startswith("n"))
for pid in subprocess.run(["pgrep", "-f", "eval._worker"], capture_output=True, text=True).stdout.split():
    if in_checkout(subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout):
        print(f"ABORT: eval worker pid {pid} already runs from this checkout (shared live tree).", flush=True); sys.exit(2)

def newest(ds, g):
    d = sorted((REPO / "logs/runs").glob(f"{ds}__{g}__cyanchor_*"), key=lambda p: p.stat().st_mtime); return d[-1] if d else None
def expected_n(ds, graph, limit):
    """Question count the cell must have: the limit, else the graph's size in the release."""
    try: full = sum(1 for r in json.load(open(REPO / "benchmarks" / f"{ds}_v2" / "test.json")) if r.get("graph") == graph)
    except Exception: return limit or None
    return min(limit, full) if limit else full
norm = lambda x: x if isinstance(x, str) else ("1" if x else "0")

print(f"PLAN model={A.model} reference: judge {A.judge}, {'node + relation' if A.scope == 'node_rel' else 'node'} tools | out={OUT.relative_to(REPO)} | {len(PLAN)} cells: "
      + ", ".join(f"{CELL(g)}/{v}" for g, v in PLAN), flush=True)
n_fail = 0
for g, v in PLAN:
    ds, graph, limit, _ = GRAPHS[g]; limit = A.limit or limit; dest = OUT / f"{CELL(g)}__{v}"
    if dest.exists(): print(f"SKIP {CELL(g)}/{v}", flush=True); continue
    knobs = {**SHIPPED, **VARIANTS[v]}
    for k, x in knobs.items(): setattr(cfg, k, x)
    cfg.EVAL_PAIRS = [(ds, graph)]; cfg.LIMIT = limit; cfg.VERBOSE = False; cfg.SHARDS = 1
    print(f"START {CELL(g)}/{v} {VARIANTS[v]} limit={limit}", flush=True); t0 = time.time()
    try: rc = eval_run.main()
    except Exception as e: print(f"FAIL {CELL(g)}/{v}: {e}", flush=True); n_fail += 1; continue
    d = newest(ds, graph)
    if rc != 0 or d is None: print(f"FAIL {CELL(g)}/{v}: rc={rc}", flush=True); n_fail += 1; continue
    s = json.load(open(d / "summary.json")); kn = s.get("run_config", {}).get("knobs", {}); llm = s.get("run_config", {}).get("llm", {})
    # every switch of the cell must be what the run recorded; the flipped switch and the two that define the reference must be recorded
    must = set(VARIANTS[v]) | {"CYANCHOR_TOOL_SCOPE", "PLAN_EXEC_SELECT_JUDGE"}
    bad = [k for k, x in knobs.items() if k != "GENERATOR_LLM" and ((k in kn and kn[k] != norm(x)) or (k not in kn and k in must))]
    bad += [] if llm.get("generator_llm") == A.model else ["GENERATOR_LLM"]
    want_n = expected_n(ds, graph, limit)
    if want_n is not None and s.get("n") != want_n: bad.append(f"n={s.get('n')} (expected {want_n})")
    if bad: print(f"FAIL {CELL(g)}/{v}: not as planned {bad} — left in logs/runs, NOT moved", flush=True); n_fail += 1; continue
    shutil.move(str(d), str(dest))
    warn = "  ⚠ errors above 2% — check for rate-limit timeouts before trusting this cell" if s["n_errors"] > 0.02 * s["n"] else ""
    print(f"DONE {CELL(g)}/{v} EA={s['ea']:.3f} PSJS={s['psjs']:.3f} n={s['n']} err={s['n_errors']} t={(time.time()-t0)/60:.0f}m{warn}", flush=True)
print("ABLATION COMPLETE" if not n_fail else f"ABLATION INCOMPLETE — {n_fail} cell(s) failed; rerun the same command to retry them", flush=True)
