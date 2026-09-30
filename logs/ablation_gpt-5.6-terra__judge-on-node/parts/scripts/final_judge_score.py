"""Merge the timed-out run + remainder run of each arm, verify 1,283 pole questions, score exactly like
scripts/tuning/score_ablation.py (paired per question, two-sided sign test), and write merged cells."""
import json, math, glob, os, collections, shutil, sys
from pathlib import Path
os.chdir("/Users/receive/Documents/repo/t2c")
REL = {r["id"]: r for r in json.load(open("benchmarks/zograscope_augmented_v2/test.json")) if r.get("graph") == "pole"}
ORDER = list(REL)
p2 = lambda g, l: 1.0 if g + l == 0 else min(1.0, 2 * sum(math.comb(g + l, k) for k in range(0, min(g, l) + 1)) / 2 ** (g + l))
ARMS = {"on": ("/Users/receive/Documents/repo/t2c", "pole_full__reference"), "off": ("/Users/receive/Documents/repo/t2c_b", "pole_full__no_select_judge")}
R = {}
for arm, (root, cell) in ARMS.items():
    dirs = sorted(glob.glob(f"{root}/logs/runs/zograscope_augmented__pole__cyanchor_*"), key=os.path.getmtime)
    recs, src = {}, {}
    for d in dirs:
        for l in open(f"{d}/records.jsonl"):
            try: r = json.loads(l)
            except Exception: continue
            assert r["qid"] not in recs, f"duplicate qid {r['qid']} in {arm}"
            recs[r["qid"]] = r; src[r["qid"]] = os.path.basename(d)
    assert set(recs) == set(REL), f"{arm}: {len(recs)} records, missing {len(set(REL)-set(recs))}, extra {len(set(recs)-set(REL))}"
    assert all(recs[q]["question"] == REL[q]["nl"] for q in REL), f"{arm}: question text mismatch"
    summ = [json.load(open(f"{d}/summary.json")) for d in dirs if os.path.exists(f"{d}/summary.json")]
    kn = {json.dumps(s["run_config"]["knobs"], sort_keys=True) for s in summ}
    assert len(kn) == 1, f"{arm}: knob sets differ across run dirs"
    knobs = summ[0]["run_config"]["knobs"]
    assert knobs["PLAN_EXEC_SELECT_JUDGE"] == ("1" if arm == "on" else "0") and knobs["CYANCHOR_TOOL_SCOPE"] == "node"
    assert summ[0]["run_config"]["llm"]["generator_llm"] == "gpt-5.6-terra"
    R[arm] = recs
    errs = sum(1 for r in recs.values() if r.get("error"))
    print(f"judge {arm:3s}: {len(recs)} records from {len(dirs)} run dirs {dict(collections.Counter(src.values()))}, errors {errs}, judge={knobs['PLAN_EXEC_SELECT_JUDGE']} scope={knobs['CYANCHOR_TOOL_SCOPE']}")
    # merged cell for the ablation scorer (records.jsonl is what it reads; summary.json for the handoff's deliverable)
    dest = Path(root) / "logs/ablation_gpt-5.6-terra__judge-on-node" / cell
    dest.mkdir(parents=True, exist_ok=True)
    with open(dest / "records.jsonl", "w") as f:
        for q in ORDER: f.write(json.dumps(recs[q], ensure_ascii=False) + "\n")
    ea = sum(bool(recs[q]["ea"]) for q in ORDER) / len(ORDER); psjs = sum((recs[q]["psjs"] or 0) for q in ORDER) / len(ORDER)
    s = {**summ[0], "n": len(ORDER), "ea": ea, "psjs": psjs, "n_errors": errs,
         "merged_from": sorted(set(src.values())), "note": "merged: 4 h worker timeout split the cell into two runs; every question ran once with identical knobs"}
    json.dump(s, open(dest / "summary.json", "w"), indent=1, ensure_ascii=False)
    print(f"   merged cell written: {dest}")
F, X = R["on"], R["off"]
def report(Q, label):
    eaF = sum(bool(F[q]["ea"]) for q in Q) / len(Q); eaX = sum(bool(X[q]["ea"]) for q in Q) / len(Q)
    h = sum(1 for q in Q if F[q]["ea"] and not X[q]["ea"]); u = sum(1 for q in Q if X[q]["ea"] and not F[q]["ea"])
    print(f"{label:34s} n={len(Q):4d}  EA on {100*eaF:5.1f}%  off {100*eaX:5.1f}%  delta {100*(eaF-eaX):+5.1f}  helped/hurt {h:3d}/{u:3d}  discordant {100*(h+u)/len(Q):4.1f}%  p={p2(h,u):.3g}")
print()
report(ORDER, "ALL pole (final)")
report(ORDER[:400], "first 400 (first-run subset)")
report(ORDER[400:], "questions 401-1283")
by = collections.defaultdict(list)
for q in ORDER: by[F[q].get("strategy")].append(q)
for s, Q in sorted(by.items(), key=lambda kv: -len(kv[1])): report(Q, f"  strategy {s}")
# PSJS as a secondary metric
psF = sum((F[q]["psjs"] or 0) for q in ORDER) / len(ORDER); psX = sum((X[q]["psjs"] or 0) for q in ORDER) / len(ORDER)
print(f"\nPSJS on {psF:.3f}  off {psX:.3f}  delta {psF-psX:+.3f}")
