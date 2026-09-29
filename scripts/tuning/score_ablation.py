#!/usr/bin/env python3
"""Score the component ablation and write report/ablation_table*.md.

    python scripts/tuning/score_ablation.py                                   # gpt-4.1 cells
    python scripts/tuning/score_ablation.py --model gpt-5.6-terra [--paper]   # all-on reference (node+rel tools), 2026-09
    python scripts/tuning/score_ablation.py --model gpt-5.6-terra --ref judge-off [--pole-full] [--paper]
                                                                              # released reference (node tools), cells written by
                                                                              # run_ablation_model.py [--pole-full] (judge off = released)

With --paper, also write the paper-format tables: the main-text table (components whose
pooled effect is significant), the full table for the appendix, Δ in points, pooled column,
sign-test markers, and a component glossary (Markdown + LaTeX).

Each variant cell is paired per question with its graph's reference run, restricted to
questions whose text is verbatim in the current release (benchmarks/). Existing cells
(logs/ablation, logs/verify_cols, logs/dev_sweep) and filled cells (logs/ablation_fill)
are picked up automatically; a missing cell prints as —.
"""
import json, math, collections, glob, os, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent.parent; os.chdir(REPO)
MODEL = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "gpt-4.1"
REFNAME = sys.argv[sys.argv.index("--ref") + 1] if "--ref" in sys.argv else ""        # judge-on | judge-off: released-reference cells
POLE_FULL = "--pole-full" in sys.argv
ROOT = f"logs/ablation_{MODEL}" + (f"__{REFNAME}-node" if REFNAME else "")
if "--root" in sys.argv: ROOT = sys.argv[sys.argv.index("--root") + 1].rstrip("/")  # any other cell root (e.g. a smoke run)
SUFFIX = ("" if ROOT == f"logs/ablation_{MODEL}" else "__" + Path(ROOT).name.split("__", 1)[-1]) + ("-polefull" if POLE_FULL else "")
DIRKEY = lambda g: "pole_full" if (g == "pole" and POLE_FULL) else g
ADDED = set()   # rows whose cell ADDS the component to the reference (shown with "+")

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
    GRAPHS = ["flight_accident", "healthcare", "pole", "nba"]
    REF = {g: f"{ROOT}/{DIRKEY(g)}__reference" for g in GRAPHS}
    # dir names: runs made before 2026-09-28 removed judge / relation tools from an all-on reference
    # (no_select_judge, node_tools_only); later runs ADD them to the shipped defaults (select_judge, rel_tools).
    _V = {"escalation":["no_escalate"],"select_judge":["no_select_judge","select_judge"],"semantic_repair":["no_semantic_repair"],
          "value_snap":["no_value_snap"],"relation_tools":["node_tools_only","rel_tools"],"fuzzy_only":["fuzzy_only"],
          "lev_only":["lev_only"],"no_correction":["no_correction"]}
    def _first(g, names):
        for d in names:
            if Path(f"{ROOT}/{DIRKEY(g)}__{d}").is_dir(): return f"{ROOT}/{DIRKEY(g)}__{d}"
        return f"{ROOT}/{DIRKEY(g)}__{names[0]}"
    CELLS = {v: {g: _first(g, ds) for g in GRAPHS} for v, ds in _V.items()}
    ADDED = {v for v, dirs in CELLS.items() if any(d.endswith(("__select_judge", "__rel_tools")) and Path(d).is_dir() for d in dirs.values())}
    ROWS = [(v, "+" + n[1:] if v in ADDED else n, sw.replace("=0", "=1") if v == "select_judge" and v in ADDED else sw) for v, n, sw in ROWS]
    if ROOT != f"logs/ablation_{MODEL}":   # released-reference runs: five single-switch rows (the judge was dropped from the paper); other rows only if they were run
        DESIGN = ("escalation", "semantic_repair", "value_snap", "fuzzy_only", "lev_only")
        ROWS = [r for r in ROWS if r[0] in DESIGN or any(Path(d).is_dir() for d in CELLS.get(r[0], {}).values())]

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

GRAPHS = [g for g in GRAPHS if g in RES]
if not GRAPHS: print("no reference cells yet"); sys.exit(0)

def cell(g, v):
    x = RES[g]["var"].get(v); s = f"{100*x['d']:+.1f}" if x else "—"
    return f"**{s}**" if x and x["p"] < 0.05 else s
L = [f"# CyANCHOR component ablation — {MODEL}\n",
     "Paired per question against the full-method reference on the same questions (runs restricted to questions verbatim in the current release; "
     + ("healthcare and pole use a fixed 400-question prefix). terrorist_attack is the CypherBench-train dev graph, not part of the release. " if MODEL == "gpt-4.1"
        else ("every graph runs in full). " if POLE_FULL else "pole uses its first 400 questions). "))
     + "Cells: Δ EA in points; **bold** = two-sided sign test p < 0.05; — = not run.\n",
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
LEGACY = ROOT == f"logs/ablation_{MODEL}"
missing = [(name, g) for v, name, _ in ROWS if v != "no_correction" for g in (GRAPHS[:3] if MODEL == "gpt-4.1" else GRAPHS) if v not in RES[g]["var"]]
JUDGE_REF = "off" if "judge-off" in ROOT else "on"
if LEGACY:
    L += ["## Missing cells for the paper table (3 test graphs × 8 rows)\n"]
    DRV = "`scripts/tuning/run_ablation_fill.py` (add `--with-joint` for the all-correction row)" if MODEL == "gpt-4.1" else f"`scripts/tuning/run_ablation_model.py --model {MODEL}` (add `--with-joint` for the all-correction row)"
    NOTE = f"{len(missing)} missing. `+ vector arm` needs per-graph embeddings first (archives have EMBEDDABLE_PROPERTIES=[]). Driver for the rest: {DRV}.\n"
else:
    L += [f"## Missing cells ({len(GRAPHS)} graphs × {len(ROWS)} rows)\n"]
    NOTE = f"{len(missing)} missing. Rerun `python scripts/tuning/run_ablation_model.py --model {MODEL} --judge {JUDGE_REF}{' --pole-full' if POLE_FULL else ''}` to fill them.\n"
L += [f"- {name}: " + ", ".join(g for n2, g in missing if n2 == name) for name in dict.fromkeys(n for n, _ in missing)]
L += ["", NOTE,
      "Detection floor (paired sign test, 80% power, observed 4–8% discordance): ~5–6 points at n=167, ~3.5 at n≈400, ~2.4 pooled over the three test graphs.\n",
      "## Sources\n", "References: " + ", ".join(f"`{REF[g]}`" for g in GRAPHS) + ". Variants: " + ("`logs/ablation`, `logs/verify_cols`, `logs/dev_sweep`, `logs/ablation_fill`" if MODEL == "gpt-4.1" else f"`{ROOT}`") + f". Backbone {MODEL}, SHARDS=1, errors score 0."]
Path("report/ablation_table.md" if MODEL == "gpt-4.1" else f"report/ablation_table_{MODEL}{SUFFIX}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L[3:16])); print(f"\n{len(missing)} cells missing")

# ── --paper: ACL-style tables (Markdown + LaTeX) from the same cells ────────────
if "--paper" in sys.argv:
    PBASE = "report/ablation_paper_table" if LEGACY else f"report/ablation_paper_table_{MODEL}{SUFFIX}"
    PROWS = [  # variant key, component, group — rows in pipeline order
        ("escalation",      "escalation loop",          "Grounding loop"),
        ("select_judge",    "select-or-abstain judge",  "Grounding loop"),
        ("relation_tools",  "relation tools",           "Grounding loop"),
        ("fuzzy_only",      "Levenshtein arm",          "Retrieval arms"),
        ("lev_only",        "fuzzy arm",                "Retrieval arms"),
        ("semantic_repair", "semantic repair",          "Post-generation correction"),
        ("value_snap",      "value-snap guard",         "Post-generation correction"),
    ]
    PROWS = [r for r in PROWS if any(r[0] in RES[g]["var"] for g in GRAPHS)]        # only rows that were run
    N = sum(RES[g]["n"] for g in GRAPHS)
    def pooled(v):
        if any(v not in RES[g]["var"] for g in GRAPHS): return None
        xs = [RES[g]["var"][v] for g in GRAPHS]; gn = sum(x["g"] for x in xs); ls = sum(x["l"] for x in xs)
        return {"d": sum(RES[g]["var"][v]["d"] * RES[g]["n"] for g in GRAPHS) / N, "g": gn, "l": ls, "p": p2(gn, ls),
                "macro": sum(x["d"] for x in xs) / len(xs)}
    full_pooled = sum(RES[g]["full"] * RES[g]["n"] for g in GRAPHS) / N
    sgn   = lambda v: "+" if v in ADDED else "−"
    mark  = lambda p: "‡" if p < 0.01 else ("†" if p < 0.05 else "")
    dcell = lambda x: "—" if x is None else f"{100*x['d']:+.1f}".replace("-", "−") + mark(x["p"])     # Markdown: real minus sign
    lcell = lambda x: "—" if x is None else f"${100*x['d']:+.1f}" + (r"^{\ddagger}" if x["p"] < 0.01 else (r"^{\dagger}" if x["p"] < 0.05 else "")) + "$"  # LaTeX: math-mode minus
    fcell = lambda x: "—" if x is None else f"{x['g']}/{x['l']}, p={x['p']:.2g}"
    hdr = [f"{g} (n={RES[g]['n']})" for g in GRAPHS] + [f"pooled (n={N:,})"]
    P = RES["_pooled"] = {v: pooled(v) for v, _, _ in PROWS}
    MAIN = [r for r in PROWS if P[r[0]] and P[r[0]]["p"] < 0.05]
    POLE = "every graph runs in full" if POLE_FULL else "pole uses its first 400 questions in release order (the prefix has the category mix of the whole graph), the other graphs run in full"
    REFDESC = ("The full-system run has every component on (select-or-abstain judge on, node + relation tools); the released default routes on "
               "node-property tools only, which is the `− relation tools` row." if LEGACY else
               f"The full row is the released configuration: routing on node-property tools, fuzzy + Levenshtein arms, escalation loop, "
               f"semantic repair and value-snap on" + (" (select-or-abstain judge on: the pre-freeze reference)." if JUDGE_REF == "on" else "."))

    def md_table(rows):
        T = ["| | " + " | ".join(hdr) + " |", "|---|" + "---:|" * len(hdr),
             "| **CyANCHOR (full)** | " + " | ".join(f"{100*RES[g]['full']:.1f}" for g in GRAPHS) + f" | {100*full_pooled:.1f} |"]
        grp = None
        for v, name, group in rows:
            if group != grp: T.append(f"| *{group}* |" + " |" * len(hdr)); grp = group
            T.append(f"| {sgn(v)} {name} | " + " | ".join(dcell(RES[g]["var"].get(v)) for g in GRAPHS) + f" | {dcell(P[v])} |")
        return T
    GLOSS = {
      "escalation": "| escalation loop | For a mention that no candidate cleanly matches, an LLM judge inspects the evidence for up to 3 rounds and returns one action: *done*, *deepen* (fetch more values from the searched fields, budget 5/3/1) or *switch to* a not-yet-searched name-like field. Mentions that already pass the clean-grounding check skip the loop. | initial retrieval only, no corrective rounds (`PLAN_EXEC_ESCALATE=0`) | recovery of routing misses and shallow retrieval; pays off where the alias/abbreviation still shares tokens with the canonical value (flight_accident, nba), not where it does not (healthcare medical synonyms). |",
      "select_judge": "| select-or-abstain judge | One closed-list LLM call on mentions that fail the clean-grounding check: *select* the one candidate the mention denotes (evidence narrowed to it), *abstain* (evidence for that mention suppressed, generator writes the predicate unaided) or *keep* on a transient failure. It can only narrow or remove evidence, never add a value. | judge skipped, evidence passes through unchanged (`PLAN_EXEC_SELECT_JUDGE=0`) | filtering of long candidate lists in the abbreviation/alias region. |",
      "relation_tools": "| relation tools | Relationship-type tools in the routing index. In CyANCHOR a relation mention retrieves no values; it only contributes its traversal pattern `(:A)-[:rel]->(:B)` as a hint to the generator. | routing over node-property tools only, no pattern hint (`CYANCHOR_TOOL_SCOPE=node`) | value of the relation-pattern hint; the perturbed entities never live on relationship properties, and the hint repeats what the schema block already states. |",
      "fuzzy_only": "| Levenshtein arm | Server-side normalized edit-distance scan over the field's full value set (top 10), array-valued alias lists unwound and matched element-wise. | fuzzy arm is the only retrieval arm (`RETRIEVAL_LEVENSHTEIN=0`) | character-level recall for dense typos and abbreviation-like codes that BM25 tokenization misses. |",
      "lev_only": "| fuzzy arm | Lucene/BM25 full-text search on the routed (label, property) field (top 10); index-backed, so its cost does not grow with the field. | Levenshtein arm is the only retrieval arm (`RETRIEVAL_FUZZY=0`) | token-level recall for casing, mild typos and partial names; largely subsumed by the Levenshtein arm at these top-k. |",
      "semantic_repair": "| semantic repair | After a query executes, an LLM evaluator classifies its result against the question; any non-accept verdict triggers regeneration that keeps the full evidence block and adds the evaluator's feedback (≤4 rounds, anti-oscillation: first accepted attempt, else first executable one). | error-message retry only (`CYPHER_SEMANTIC_REPAIR=0`) | correction of executable-but-wrong queries with the grounding evidence still in the prompt. |",
      "value_snap": "| value-snap guard | Final guard on the generated query: (label, property, value) literals in `=` and property-map predicates that do not exist in the database are mapped, by one closed-list LLM call over a fresh retrieval on that field, to an existing value; the substitution is adopted only if the query still runs. Existing values are never touched. | generated literals left as written (`PLAN_EXEC_VALUE_SNAP=0`) | the residual failure where the generator retrieved the right value but copied the question's corrupted surface form into the predicate. |",
    }
    M = [f"# Component ablation of CyANCHOR — paper tables ({MODEL})\n",
         "Execution accuracy (EA, %) of the full system, and the change in EA points when one component is removed"
         + (" (a row marked + adds the component to the reference instead)" if ADDED else "") + ". Each cell is a single run at temperature 0, "
         "paired per question with the full-system run on the same questions; † / ‡ = two-sided paired sign test p < 0.05 / p < 0.01. "
         f"Pooled = all questions of the {len(GRAPHS)} graphs, paired the same way. `− Levenshtein arm` and `− fuzzy arm` leave the other arm as the only retrieval arm. "
         + REFDESC + "\n",
         "## Main-text table\n", "Rows of the full table whose pooled effect is significant (p < 0.05).\n"]
    M += md_table(MAIN) if MAIN else ["No row reaches p < 0.05 on the pooled questions."]
    M += ["", "## Full table (appendix)\n"] + md_table(PROWS)
    M += ["", "## Paired flips behind each cell (questions gained / lost relative to the full run, sign-test p)\n",
          "| | " + " | ".join(hdr) + " |", "|---|" + "---|" * len(hdr)]
    for v, name, _ in PROWS:
        M.append(f"| {sgn(v)} {name} | " + " | ".join(fcell(RES[g]["var"].get(v)) for g in GRAPHS) + f" | {fcell(P[v])} |")
    M += ["", f"Macro-mean Δ over the {len(GRAPHS)} graphs (unweighted): " + "; ".join(f"{sgn(v)} {name} {100*P[v]['macro']:+.1f}" for v, name, _ in PROWS if P[v]) + ".",
          "Detection floor of the paired sign test (80% power at the observed 4–8% discordance): ≈5–6 points at n≈170, ≈3.5 at n≈400, ≈2 at n≈1,300, ≈2.4 pooled over 1,237.\n",
          "## What each component is\n",
          "Pipeline order: PLAN (one LLM call extracts every entity mention verbatim) → EXECUTE per mention (route the mention to schema fields, "
          "retrieve candidate values, verify) → GENERATE (evidence block injected into the shared Cypher prompt) → execution-guided correction. "
          "The rows below are the toggleable components; mention extraction, tool routing, evidence injection and the error-message retry are not "
          "ablated (removing the evidence block recovers the No Val Link baseline exactly).\n",
          "| component | what it does | removing it (`switch`) | mechanism the ablation isolates |", "|---|---|---|---|"]
    M += [GLOSS[v] for v, _, _ in PROWS]
    M += ["", "## Provenance\n",
          f"Backbone {MODEL} for every LLM stage; benchmark release v2.3 (questions restricted to those verbatim in `benchmarks/`); {POLE}; "
          "SHARDS=1; errored questions score 0. " + REFDESC + " Runs: " + ", ".join(f"`{REF[g]}`" for g in GRAPHS) + f" and the variant cells under `{ROOT}/`. "
          "Regenerate with `python scripts/tuning/score_ablation.py " + " ".join(a for a in sys.argv[1:]) + f"`; per-category breakdowns are in `report/ablation_table_{MODEL}{SUFFIX}.md`.\n",
          "## Format conventions applied (ACL-style ablation table)\n",
          "- One backbone, one metric (EA), the full system as the first row and one `− component` row per switch, grouped by pipeline stage in the order the method section introduces them.",
          "- Δ in points relative to the full row; the full row carries the absolute score so readers can recover every variant's absolute EA.",
          "- n per column in the header; a pooled column paired over all questions (micro); the macro-mean is stated in the text.",
          "- Paired significance per cell (two-sided sign test on per-question flips), marked † / ‡, with the test and the detection floor stated in the caption or text.",
          "- The main text carries the components with a significant pooled effect; the full table, including components without a measurable effect, goes to the appendix and is referenced from the main text.",
          "- booktabs rules only (no vertical rules), `table*` width, `\\small`; component definitions live in the method section, the table's first column only names them.",
          "- The caption states data version, question counts, decoding (temperature 0, single run), the pairing, and which configuration the full row is."]
    Path(PBASE + ".md").write_text("\n".join(M) + "\n", encoding="utf-8")

    esc = lambda t: t.replace("_", r"\_")
    def tex_table(rows, caption, label):
        T = [r"% Generated by scripts/tuning/score_ablation.py " + " ".join(sys.argv[1:]) + " — do not edit by hand.",
             r"\begin{table*}[t]", r"\centering", r"\small",
             r"\begin{tabular}{l" + " r" * len(GRAPHS) + " r}", r"\toprule",
             " & " + " & ".join(esc(g) for g in GRAPHS) + r" & pooled \\",
             " & " + " & ".join(f"($n={RES[g]['n']:,}$)".replace(",", "{,}") for g in GRAPHS) + f" & ($n={N:,}$) \\\\".replace(",", "{,}"),
             r"\midrule",
             r"\method\ (full) & " + " & ".join(f"{100*RES[g]['full']:.1f}" for g in GRAPHS) + f" & {100*full_pooled:.1f} \\\\"]
        grp = None
        for v, name, group in rows:
            if group != grp:
                T.append(r"\addlinespace[2pt]" + f"\\multicolumn{{{len(GRAPHS)+2}}}{{l}}{{\\emph{{{group}}}}} \\\\"); grp = group
            T.append(f"\\quad ${'+' if v in ADDED else '-'}$ {name} & " + " & ".join(lcell(RES[g]["var"].get(v)) for g in GRAPHS) + f" & {lcell(P[v])} \\\\")
        return T + [r"\bottomrule", r"\end{tabular}", r"\caption{" + caption + "}", r"\label{" + label + "}", r"\end{table*}"]
    CAP = (r"of \method\ (" + esc(MODEL) + r"): \ea\ (\%) of the full system and the change in points when one component is removed, on one graph "
           r"per benchmark plus nba (the alias-richest \cypherbench\ graph); " + ("every graph runs in full" if POLE_FULL else "pole uses its first 400 questions")
           + r". Pooled $=$ all " + f"{N:,}".replace(",", "{,}") + r" questions. Every cell is one run at temperature~0, paired per question with the full run; "
           r"$^{\dagger}$/$^{\ddagger}$: two-sided sign test $p<0.05$/$p<0.01$. ``$-$ Levenshtein arm'' and ``$-$ fuzzy arm'' leave the other arm as the sole retrieval arm. "
           + (r"The released default routes on node-property tools only (the $-$ relation tools row)." if LEGACY else r"The full row is the released configuration."))
    Path(PBASE + "_main.tex").write_text("\n".join(tex_table(MAIN, "Component ablation " + CAP + r" Components without a measurable effect are in Table~\ref{tab:ablation-full}.", "tab:ablation-components")) + "\n", encoding="utf-8")
    Path(PBASE + ".tex").write_text("\n".join(tex_table(PROWS, "Full component ablation " + CAP, "tab:ablation-full")) + "\n", encoding="utf-8")
    print("\n".join(M[3:4] + md_table(MAIN))); print(f"\nwrote {PBASE}.md, {PBASE}_main.tex, {PBASE}.tex")
