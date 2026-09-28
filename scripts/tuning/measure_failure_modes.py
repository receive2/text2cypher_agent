#!/usr/bin/env python3
"""Failure-mode measurement for the select-or-abstain judge (no LLM calls).

Re-executes the predicted Cypher of two runs per graph (reference vs judge
removed) inside READ-ONLY transactions and classifies every question as
  correct | wrong-empty (0 rows) | wrong-nonempty (a confidently wrong answer) | error.
The judge's designed effect is to turn confident wrong answers into abstentions,
which EA cannot see; this is the quantity that can.
"""
import json, os, sys, collections
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent.parent; sys.path.insert(0, str(REPO)); os.chdir(REPO)
import eval_config as cfg
from neo4j import GraphDatabase, Query, READ_ACCESS

MODEL = "gpt-5.6-terra"
GRAPHS = {"flight_accident": ("cypherbench", "flight_accident"), "healthcare": ("mindthequery", "healthcare"),
          "pole": ("zograscope", "pole"), "nba": ("cypherbench", "nba")}
VARIANTS = {"reference": "reference", "no_judge": "no_select_judge"}
ROW_CAP = 5000

def load(d): return {r["qid"]: r for l in open(d + "/records.jsonl") if (r := json.loads(l))}

def classify(session, cypher):
    """Auto-commit query in a READ-access session (the server rejects writes in
    read mode), with a 60 s server-side timeout. Rows counted up to ROW_CAP."""
    if not (cypher or "").strip(): return "error"
    try:
        res = session.run(Query(cypher, timeout=60)); n = 0
        for _ in res:
            n += 1
            if n >= ROW_CAP: break
        res.consume()
        return "empty" if n == 0 else "nonempty"
    except Exception:
        return "error"

out = {}
for g, key in GRAPHS.items():
    conn = cfg.GRAPH_CONNS[key]
    drv = GraphDatabase.driver(conn.uri, auth=(conn.user, conn.password))
    runs = {v: load(f"logs/ablation_{MODEL}/{g}__{d}") for v, d in VARIANTS.items()}
    qids = [q for q in runs["reference"] if q in runs["no_judge"]]
    out[g] = {}
    with drv.session(database=conn.database, default_access_mode=READ_ACCESS) as s:
        for v, R in runs.items():
            c = collections.Counter()
            for q in qids:
                r = R[q]
                if r.get("ea"): c["correct"] += 1; continue
                if r.get("error"): c["error"] += 1; continue
                k = classify(s, r.get("pred_cypher"))
                cat = "wrong-empty" if k == "empty" else "wrong-nonempty" if k == "nonempty" else "error"
                c[cat] += 1; out.setdefault("_per_q", {}).setdefault(g, {}).setdefault(v, {})[q] = cat
            out[g][v] = dict(c); out[g]["n"] = len(qids)
            print(f"{g:16s} {v:10s} n={len(qids)}  " + "  ".join(f"{k}={c[k]}" for k in ("correct", "wrong-empty", "wrong-nonempty", "error")), flush=True)
    drv.close()
json.dump(out, open("report/judge_failure_modes.json", "w"), indent=1)

print("\n=== confident-wrong (non-empty wrong) rate, % of questions ===")
print(f"{'graph':16s} {'n':>5s} {'judge ON':>9s} {'judge OFF':>10s} {'Δ(OFF−ON)':>10s}")
T = collections.Counter()
for g, o in out.items():
    if g.startswith("_"): continue
    n = o["n"]; a = o["reference"].get("wrong-nonempty", 0); b = o["no_judge"].get("wrong-nonempty", 0)
    T["n"] += n; T["a"] += a; T["b"] += b
    print(f"{g:16s} {n:5d} {100*a/n:8.1f}% {100*b/n:9.1f}% {100*(b-a)/n:+9.1f}")
print(f"{'POOLED':16s} {T['n']:5d} {100*T['a']/T['n']:8.1f}% {100*T['b']/T['n']:9.1f}% {100*(T['b']-T['a'])/T['n']:+9.1f}")
print("MEASUREMENT DONE", flush=True)
