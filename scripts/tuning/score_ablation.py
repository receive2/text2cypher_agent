#!/usr/bin/env python3
"""Score the component ablation and write report/ablation_table.md.

Each variant cell is paired per question with its graph's reference run, restricted to
questions whose text is verbatim in the current release (benchmarks/). Existing cells
(logs/ablation, logs/verify_cols, logs/dev_sweep) and filled cells (logs/ablation_fill)
are picked up automatically; a missing cell prints as —.
"""
import json, math, collections, glob, os, sys
from pathlib import Path
REPO = Path("/Users/q0w01lh/Documents/repo/t2c"); os.chdir(REPO)
MODEL = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "gpt-4.1"

REL = {}
for ds in ("cypherbench", "mindthequery", "zograscope"):
    for r in json.load(open(f"benchmarks/{ds}_augmented_v2/test.json")): REL[(r["graph"], r["id"])] = r["nl"]

REF = {"flight_accident": "logs/ablation/fa__full__full_20260823",
       "healthcare": "logs/verify_cols/healthcare__full__v400",
       "pole": "logs/verify_cols/pole__full__v400",
       "terrorist_attack": "logs/dev_sweep/ta__full__dev400"}
CELLS = {  # variant -> {graph: dir}
  "escalation":      {"flight_accident": "logs/ablation/fa__no_escalate__full_20260823", "healthcare": "logs/ablation_fill/healthcare__no_escalate__v400", "pole": "logs/ablation_fill/pole__no_escalate__v400"},
  "select_judge":    {"flight_accident": "logs/ablation/fa__no_select_judge__full_20260823", "healthcare": "logs/ablation_fill/healthcare__no_select_judge__v400", "pole": "logs/ablation_fill/pole__no_select_judge__v400"},
  "semantic_repair": {"flight_accident": "logs/ablation/fa__no_semantic_repair__full_20260823", "healthcare": "logs/ablation_fill/healthcare__no_semantic_repair__v400", "pole": "logs/ablation_fill/pole__no_semantic_repair__v400"},
  "value_snap":      {"flight_accident": "logs/ablation/fa__no_value_snap__full_20260823", "healthcare": "logs/verify_cols/healthcare__no_value_snap__v400", "pole": "logs/verify_cols/pole__no_value_snap__v400", "terrorist_attack": "logs/dev_sweep/ta__no_value_snap__dev400"},
  "relation_tools":  {"flight_accident": "logs/ablation/fa__node_tools_only__full_20260823", "healthcare": "logs/verify_cols/healthcare__node_tools_only__v400", "pole": "logs/verify_cols/pole__node_tools_only__v400", "terrorist_attack": "logs/dev_sweep/ta__node_tools_only__dev400"},
  "fuzzy_only":      {g: f"logs/ablation_fill/{g}__fuzzy_only__{'full' if g=='flight_accident' else 'v400'}" for g in ("flight_accident","healthcare","pole")},
  "lev_only":        {g: f"logs/ablation_fill/{g}__lev_only__{'full' if g=='flight_accident' else 'v400'}" for g in ("flight_accident","healthcare","pole")},
  "no_correction":   {g: f"logs/ablation_fill/{g}__no_correction__{'full' if g=='flight_accident' else 'v400'}" for g in ("flight_accident","healthcare","pole")},
}
ROWS = [("escalation","− escalation loop","PLAN_EXEC_ESCALATE=0"), ("select_judge","− select-or-abstain judge","PLAN_EXEC_SELECT_JUDGE=0"),
        ("semantic_repair","− semantic repair","CYPHER_SEMANTIC_REPAIR=0"), ("value_snap","− value-snap","PLAN_EXEC_VALUE_SNAP=0"),
        ("relation_tools","− relation tools","TOOL_TYPE=node"), ("fuzzy_only","fuzzy arm only","RETRIEVAL_LEVENSHTEIN=0"),
        ("lev_only","lev arm only","RETRIEVAL_FUZZY=0"), ("plus_vector","+ vector arm","RETRIEVAL_VECTOR=1"),
        ("no_correction","− all correction (escalation, judge, repair, value-snap)","—")]
GRAPHS = ["flight_accident", "healthcare", "pole", "terrorist_attack"]; CATS = ["casing","typo","partial","abbrev","alias"]
if MODEL != "gpt-4.1":   # per-backbone tables: everything under logs/ablation_<model>/
    GRAPHS = ["flight_accident", "healthcare", "pole"]
    REF = {g: f"logs/ablation_{MODEL}/{g}__reference" for g in GRAPHS}
    _V = {"escalation":"no_escalate","select_judge":"no_select_judge","semantic_repair":"no_semantic_repair","value_snap":"no_value_snap",
          "relation_tools":"node_tools_only","fuzzy_only":"fuzzy_only","lev_only":"lev_only","no_correction":"no_correction"}
    CELLS = {v: {g: f"logs/ablation_{MODEL}/{g}__{d}" for g in GRAPHS} for v, d in _V.items()}

def load(d):
    p = Path(d) / "records.jsonl"
    return {r["qid"]: r for l in open(p) if (r := json.loads(l))} if p.is_file() else None
def p2(g, l):
    n = g + l; return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, k) for k in range(0, min(g, l) + 1)) / 2 ** n)

RES = {}
for g in GRAPHS:
    F = load(REF[g])
    if not F: print(f"reference missing for {g}: {REF[g]}"); continue
    Q = list(F) if g == "terrorist_attack" else [q for q, r in F.items() if REL.get((g, q)) == r["question"]]
    ea = lambda X: sum(bool(X[q]["ea"]) for q in Q) / len(Q)
    cat_ea = lambda X: {c: sum(bool(X[q]["ea"]) for q in Q if F[q]["strategy"] == c) / n for c, n in collections.Counter(F[q]["strategy"] for q in Q).items()}
    RES[g] = {"n": len(Q), "full": ea(F), "cats_n": dict(collections.Counter(F[q]["strategy"] for q in Q)), "full_cats": cat_ea(F), "var": {}}
    for v, dirs in CELLS.items():
        X = load(dirs[g]) if g in dirs else None
        if not X or any(q not in X for q in Q): continue
        gn = sum(1 for q in Q if X[q]["ea"] and not F[q]["ea"]); ls = sum(1 for q in Q if F[q]["ea"] and not X[q]["ea"])
        RES[g]["var"][v] = {"ea": ea(X), "d": ea(X) - RES[g]["full"], "g": gn, "l": ls, "p": p2(gn, ls),
                            "cat_d": {c: cat_ea(X)[c] - RES[g]["full_cats"][c] for c in RES[g]["full_cats"]}}

def cell(g, v):
    x = RES[g]["var"].get(v); s = f"{100*x['d']:+.1f}" if x else "—"
    return f"**{s}**" if x and x["p"] < 0.05 else s
L = [f"# CyANCHOR component ablation — {MODEL}\n",
     "Paired per question against the full-method reference on the same questions (runs restricted to questions verbatim in the current release; healthcare and pole use a fixed 400-question prefix). "
     "terrorist_attack is the CypherBench-train dev graph, not part of the release. Cells: Δ EA in points; **bold** = two-sided sign test p < 0.05; — = not run.\n",
     "## Δ EA\n", "| variant | switch | " + " | ".join(GRAPHS) + " |", "|---|---|" + "---|" * len(GRAPHS),
     "| CyANCHOR full (EA) | — | " + " | ".join(f"{RES[g]['full']:.3f}" for g in GRAPHS) + " |"]
for v, name, sw in ROWS: L.append(f"| {name} | `{sw}` | " + " | ".join(cell(g, v) for g in GRAPHS) + " |")
L += ["", "n: " + " · ".join(f"{g} {RES[g]['n']}" for g in GRAPHS) + "\n", "## Paired flips (gained / lost), sign-test p\n",
      "| variant | " + " | ".join(GRAPHS) + " |", "|---|" + "---|" * len(GRAPHS)]
for v, name, _ in ROWS:
    L.append(f"| {name} | " + " | ".join((lambda x: "—" if not x else f"{x['g']}/{x['l']}, p={x['p']:.2g}")(RES[g]["var"].get(v)) for g in GRAPHS) + " |")
L += ["", "## Per-category Δ EA (points)\n"]
for g in GRAPHS:
    L += [f"**{g}** — n per category: " + ", ".join(f"{c} {RES[g]['cats_n'].get(c,0)}" for c in CATS) + "\n",
          "| variant | " + " | ".join(CATS) + " |", "|---|" + "---|" * len(CATS),
          "| CyANCHOR full (EA) | " + " | ".join(f"{RES[g]['full_cats'][c]:.3f}" if c in RES[g]["full_cats"] else "—" for c in CATS) + " |"]
    for v, name, _ in ROWS:
        x = RES[g]["var"].get(v)
        if x: L.append(f"| {name} | " + " | ".join(f"{100*x['cat_d'][c]:+.1f}" if c in x["cat_d"] else "—" for c in CATS) + " |")
    L.append("")
GRAPHS = [g for g in GRAPHS if g in RES]
missing = [(name, g) for v, name, _ in ROWS if v != "no_correction" for g in GRAPHS[:3] if v not in RES[g]["var"]]
L += ["## Missing cells for the paper table (3 test graphs × 8 rows)\n"]
L += [f"- {name}: " + ", ".join(g for n2, g in missing if n2 == name) for name in dict.fromkeys(n for n, _ in missing)]
L += ["", f"{len(missing)} missing. `+ vector arm` needs per-graph embeddings first (archives have EMBEDDABLE_PROPERTIES=[]). "
      "Driver for the rest: `scripts/tuning/run_ablation_fill.py` (add `--with-joint` for the all-correction row).\n",
      "Detection floor (paired sign test, 80% power, observed 4–8% discordance): ~5–6 points at n=167, ~3.5 at n≈400, ~2.4 pooled over the three test graphs.\n",
      "## Sources\n", "References: " + ", ".join(f"`{d}`" for d in REF.values()) + ". Variants: `logs/ablation`, `logs/verify_cols`, `logs/dev_sweep`, `logs/ablation_fill`. Backbone gpt-4.1, SHARDS=1, errors score 0."]
Path("report/ablation_table.md" if MODEL == "gpt-4.1" else f"report/ablation_table_{MODEL}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L[3:16])); print(f"\n{len(missing)} cells missing")
