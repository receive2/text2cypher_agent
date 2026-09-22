#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_datasheet_tables.py
==========================
Single source of truth for every number in docs/DATASHEET.md: recompute all
figure/table blocks from the released datasets and splice them into the
AUTOGEN-marked regions. **Never hand-edit those regions** — rerun this script
after any data change (and after post-annotation adjudication).

Blocks: HEADLINE (exact-match-defeat rate), COMPOSITION, STRATEGY (targets vs
released shares), PROVENANCE (where edits come from, what was verified),
GROUNDING (surface-relation classes), TIERS (query-difficulty tiers), REALIZED
(per-graph mix), VERIFICATION (human-verification outcome), GOLD (gold queries
that do not execute).

    python scripts/render_datasheet_tables.py           # rewrite the blocks in place
    python scripts/render_datasheet_tables.py --check   # exit 1 if the file is out of date (used by the tests)
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import eval_config as cfg  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
SYN = {"pole", "er", "bloom"}
STRATS = ["casing", "typo", "partial", "abbrev", "alias"]
DATASHEET = _REPO / "docs" / "DATASHEET.md"


def load():
    rows = []
    for ds, path in _DATASETS.items():
        probed = json.load(open(Path(path).with_name("test.probed.json"),
                                encoding="utf-8"))
        for x in probed:
            m = x["_aug_meta"]
            e = (m.get("edits") or [{}])[0]
            src = e.get("source", "")
            rows.append({
                "dataset": ds, "graph": m.get("graph", ""),
                "strategy": e.get("strategy"),
                "prov": ("llm" if src == "llm"
                         else "attested" if src.startswith("kb") else "algorithmic"),
                "gclass": (e.get("grounding_probe") or {}).get("class")
                          if isinstance(e.get("grounding_probe"), dict)
                          else e.get("grounding_probe"),
            })
    return rows


def block_headline(rows):
    n = len(rows)
    ci = sum(1 for r in rows if r["gclass"] == "exact_ci")
    per_ds = {}
    for ds in _DATASETS:
        sub = [r for r in rows if r["dataset"] == ds]
        per_ds[ds] = 100 - 100 * sum(1 for r in sub if r["gclass"] == "exact_ci") / len(sub)
    return (f"**Headline:** across {n:,} perturbed examples, a baseline "
            f"case-insensitive exact-match no longer recovers the canonical "
            f"entity on **{100-100*ci/n:.1f}%** of them "
            f"({' / '.join(f'{per_ds[d]:.1f}' for d in _DATASETS)}% on the "
            f"three datasets independently).")


def block_composition(rows):
    n = len(rows)
    by = defaultdict(lambda: {"graphs": set(), "n": 0})
    for r in rows:
        by[r["dataset"]]["graphs"].add(r["graph"])
        by[r["dataset"]]["n"] += 1
    graphs = sum(len(v["graphs"]) for v in by.values())
    L = [f"{len(by)} source datasets, {graphs} property graphs, **{n:,}** perturbed questions.", "",
         "| dataset | graphs | examples |", "|---|---|--:|"]
    names = {"cypherbench": "CypherBench", "mindthequery": "Mind-the-Query",
             "zograscope": "ZOGRASCOPE"}
    for ds, v in by.items():
        L.append(f"| {names[ds]} | {', '.join(sorted(v['graphs']))} | {v['n']:,} |")
    return "\n".join(L)


def block_difficulty(rows):
    meaning = {"exact_ci": "case-insensitive exact still matches (trivial)",
               "edit_distance": "within Damerau ≤2 (fuzzy-recoverable)",
               "substring": "perturbed ⊆ canonical (fulltext-recoverable)",
               "semantic": "no surface overlap (needs world knowledge / vector)"}
    L = ["| class | relation of the perturbed mention to the database value | all | CypherBench | Mind-the-Query | ZOGRASCOPE |",
         "|---|---|--:|--:|--:|--:|"]
    def pct(sub, c):
        return 100 * sum(1 for r in sub if r["gclass"] == c) / len(sub)
    for c in ("exact_ci", "edit_distance", "substring", "semantic"):
        cells = [f"{pct(rows, c):.1f}%"] + \
                [f"{pct([r for r in rows if r['dataset']==d], c):.1f}%" for d in _DATASETS]
        L.append(f"| `{c}` | {meaning[c]} | " + " | ".join(cells) + " |")
    return "\n".join(L)



STRATEGY_INFO = [
    ("casing",  "re-case the mention (lower / UPPER)",                    "`Sacramento Kings` → `SACRAMENTO KINGS`", 10.0),
    ("typo",    "one keyboard slip, transposition, deletion or doubling", "`Barletta` → `Balretta`",               22.5),
    ("partial", "drop words, keep a fragment that still identifies it",  "`Los Angeles Lakers` → `Lakers`",       22.5),
    ("abbrev",  "acronym or standard short form",                        "`Golden State Warriors` → `GSW`",       22.5),
    ("alias",   "a different name for the same referent",                "`Tocilizumab` → `Actemra`",             22.5),
]


def block_strategy(rows):
    n = len(rows)
    c = Counter(r["strategy"] for r in rows)
    L = ["| strategy | what changes | example | design share | released share |",
         "|---|---|---|--:|--:|"]
    for s_, what, ex, target in STRATEGY_INFO:
        L.append(f"| `{s_}` | {what} | {ex} | {target:.1f}% | {100*c[s_]/n:.1f}% |")
    return "\n".join(L)


PROV_LABEL = {"algorithmic": "algorithmic (rules for casing / typo / partial)",
              "attested":    "attested (Wikidata aliases shipped with CypherBench, curated tables, RxNorm)",
              "llm":         "LLM-proposed (abstention-first proposer, evidence required)"}


def block_provenance(rows):
    """Rows per provenance tier: in the pre-verification set, queued for human
    verification, measured (after calibration exclusion), and in the release."""
    import csv
    dec = list(csv.DictReader((VERIF_DIR / "decisions.csv").open(encoding="utf-8-sig")))
    st = json.loads((VERIF_DIR / "stats.json").read_text(encoding="utf-8"))
    tier = lambda t: "llm" if t == "llm" else "algorithmic" if t == "algorithmic" else "attested"
    v21 = Counter(tier(d["tier"]) for d in dec)
    queued = Counter(tier(d["tier"]) for d in dec if d["in_queue"].strip().lower() in ("1", "true", "yes"))
    measured = {r["stratum"]: r["n"] for r in st["by_provenance"]}
    v22 = Counter(r["prov"] for r in rows)
    L = ["| provenance | pre-verification rows | queued for verification | measured | released rows |",
         "|---|--:|--:|--:|--:|"]
    for t in ("algorithmic", "attested", "llm"):
        L.append(f"| {PROV_LABEL[t]} | {v21[t]:,} | {queued[t]:,} | {measured.get(t, 0):,} | {v22[t]:,} |")
    L.append(f"| **all** | {sum(v21.values()):,} | {sum(queued.values()):,} | {sum(measured.values()):,} | {sum(v22.values()):,} |")
    return "\n".join(L)


def block_tiers():
    """Query-difficulty tiers of the released questions, from eval.difficulty
    (a rule-based classifier over the gold Cypher; model- and database-free)."""
    from eval.difficulty import classify
    L = ["| dataset | n | easy | medium | hard |", "|---|--:|--:|--:|--:|"]
    pooled = Counter(); total = 0
    names = {"cypherbench": "CypherBench", "mindthequery": "Mind-the-Query", "zograscope": "ZOGRASCOPE"}
    for ds, path in _DATASETS.items():
        c = Counter(classify(x["gold_cypher"]) for x in json.load(open(path, encoding="utf-8")))
        n = sum(c.values()); pooled.update(c); total += n
        L.append(f"| {names[ds]} | {n:,} | " + " | ".join(f"{100*c[t]/n:.1f}%" for t in ("easy", "medium", "hard")) + " |")
    L.append(f"| **all** | {total:,} | " + " | ".join(f"**{100*pooled[t]/total:.1f}%**" for t in ("easy", "medium", "hard")) + " |")
    return "\n".join(L)


def block_gold():
    p = _REPO / "audit" / "gold_executability.json"
    if not p.exists():
        return "_`audit/gold_executability.json` missing — run `scripts/gold_executability.py`._"
    d = json.loads(p.read_text(encoding="utf-8"))
    bad = [g for g in d["graphs"] if g["gold_error"] + g["gold_timeout"]]
    tot = sum(g["gold_error"] + g["gold_timeout"] for g in d["graphs"])
    n = sum(g["n"] for g in d["graphs"])
    head = (f"{tot} of the {n:,} released gold queries ({100*tot/n:.1f}%) do not execute "
            f"({d['method']}; {d['date']}). They are kept as shipped and score 0 for every "
            f"system, so they lower every method equally.")
    if not bad:
        return head
    L = [head, "", "| dataset | graph | questions | non-executing golds |", "|---|---|--:|--:|"]
    for g in bad:
        L.append(f"| {g['dataset']} | {g['graph']} | {g['n']} | {g['gold_error'] + g['gold_timeout']} |")
    return "\n".join(L)


def block_realized(rows):
    n = len(rows)
    L = ["Strategy shares per graph (%); `LLM+attested` counts the edits whose surface form came "
         "from a knowledge base or a language model rather than a rule.", "",
         "| dataset | graph | n | casing | typo | partial | abbrev | alias | LLM+attested |",
         "|---|---|--:|--:|--:|--:|--:|--:|--:|"]
    by = defaultdict(list)
    for r in rows:
        by[(r["dataset"], r["graph"])].append(r)
    for (ds, g), sub in sorted(by.items()):
        c = Counter(r["strategy"] for r in sub)
        census = sum(1 for r in sub if r["prov"] in ("llm", "attested"))
        syn = " *(synthetic)*" if g in SYN else ""
        L.append(f"| {ds} | {g}{syn} | {len(sub)} | " +
                 " | ".join(f"{100*c[s]/len(sub):.1f}" for s in STRATS) +
                 f" | {census} |")
    tot = Counter(r["strategy"] for r in rows)
    census = sum(1 for r in rows if r["prov"] in ("llm", "attested"))
    L.append(f"| **ALL** | | {n} | " +
             " | ".join(f"**{100*tot[s]/n:.1f}**" for s in STRATS) +
             f" | {census} |")
    nonsyn = [r for r in rows if r["graph"] not in SYN]
    al = 100 * sum(1 for r in nonsyn if r["strategy"] == "alias") / len(nonsyn)
    L.append("")
    L.append(f"Within the alias-applicable stratum ({100*len(nonsyn)/n:.1f}% of "
             f"rows; synthetic graphs are alias-zero by design) alias = "
             f"**{al:.1f}%**. Where a graph's mix departs from the design shares, the cause is "
             f"the measured supply of attested forms (`audit/APPLICABILITY_CEILING.md`), not allocation.")
    return "\n".join(L)


VERIF_DIR = _REPO / "audit" / "verification"


def block_verification():
    """Human-verification outcome, from the release freeze's artifacts. Every
    number here is produced by scripts (verification_stats.py --json and
    freeze_verified_release.py); nothing is typed in by hand."""
    stats_p, summ_p = VERIF_DIR / "stats.json", VERIF_DIR / "summary.json"
    if not (stats_p.exists() and summ_p.exists()):
        return ("_Verification results not yet frozen — run "
                "`scripts/freeze_verified_release.py` after adjudication._")
    st = json.loads(stats_p.read_text(encoding="utf-8"))
    sm = json.loads(summ_p.read_text(encoding="utf-8"))
    f = lambda x: "—" if x is None else f"{x:.3f}"
    # how many measured items carry two labels / one label (from the verdicts themselves)
    import csv
    per_item = Counter()
    for r in csv.DictReader((VERIF_DIR / "verdicts_long.csv").open(encoding="utf-8-sig")):
        if r.get("calibration_item", "no") != "yes":
            per_item[r["id"]] += 1
    n_two = sum(1 for n in per_item.values() if n == 2)
    n_one = sum(1 for n in per_item.values() if n == 1)
    L = [f"**Release {sm['version']}** — {sm['rows_in']:,} rows in → "
         f"**{sm['rows_out']:,}** released "
         f"({sm['actions'].get('remove_total', 0)} removed, "
         f"{sm['actions'].get('revert_total', 0)} reverted to a certified prior "
         f"algorithmic form, {sm['actions'].get('pending', 0)} pending). "
         f"Naturalness policy: `{sm['naturalness_policy']}`. "
         f"Verdicts from {len(st['annotators'])} annotators over {st['items']:,} "
         f"measured items: {n_two:,} labelled by two annotators and {n_one:,} by one; "
         f"{st['calibration_ids_in_queue']} calibration items excluded.", "",
         f"Inter-annotator agreement (validity): Krippendorff's α = **{f(st['alpha'])}**, "
         f"Gwet's AC1 = **{f(st['ac1'])}**, disagreement rate "
         f"{100*st['disagreements']/max(st['double_annotated'],1):.1f}%.", "",
         "| provenance | n | validity % [95% CI] | α | AC1 | raw agr (n₂) | action |",
         "|---|--:|---|--:|--:|---|---|"]
    act = {"llm": "invalid → revert/remove", "attested": "invalid → revert/remove",
           "algorithmic": "invalid → remove"}
    for r in st["by_provenance"]:
        ci = "—" if not r["resolved"] else f"{100*r['validity']:.1f}% [{100*r['ci_lo']:.1f}, {100*r['ci_hi']:.1f}]"
        raw = "—" if r["raw_agreement"] is None else f"{100*r['raw_agreement']:.1f}% ({r['n_double']})"
        L.append(f"| {r['stratum']} | {r['n']} | {ci} | {f(r['alpha'])} | {f(r['ac1'])} | {raw} | {act.get(r['stratum'], '')} |")
    L += ["", "| strategy | n | validity % [95% CI] | α | AC1 | raw agr (n₂) |",
          "|---|--:|---|--:|--:|---|"]
    for r in st["by_strategy"]:
        ci = "—" if not r["resolved"] else f"{100*r['validity']:.1f}% [{100*r['ci_lo']:.1f}, {100*r['ci_hi']:.1f}]"
        raw = "—" if r["raw_agreement"] is None else f"{100*r['raw_agreement']:.1f}% ({r['n_double']})"
        L.append(f"| {r['stratum']} | {r['n']} | {ci} | {f(r['alpha'])} | {f(r['ac1'])} | {raw} |")
    L += ["", "Per-row verdicts (annotators as letters A–E), the blind key, the calibration "
          "reference answers and the statistics report ship in `audit/verification/`; "
          "`decisions.csv` maps every pre-verification row to its action and its position "
          "in the released files."]
    return "\n".join(L)


def render(text: str) -> str:
    rows = load()
    blocks = (("HEADLINE", block_headline(rows)),
              ("COMPOSITION", block_composition(rows)),
              ("STRATEGY", block_strategy(rows)),
              ("PROVENANCE", block_provenance(rows)),
              ("GROUNDING", block_difficulty(rows)),
              ("TIERS", block_tiers()),
              ("REALIZED", block_realized(rows)),
              ("VERIFICATION", block_verification()),
              ("GOLD", block_gold()))
    for tag, content in blocks:
        pat = re.compile(f"<!-- AUTOGEN:{tag} -->.*?<!-- /AUTOGEN:{tag} -->", re.DOTALL)
        if not pat.search(text):
            raise SystemExit(f"marker missing in {DATASHEET.name}: {tag}")
        text = pat.sub(lambda _m, c=content, t=tag: f"<!-- AUTOGEN:{t} -->\n{c}\n<!-- /AUTOGEN:{t} -->", text)
    return text


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    old = DATASHEET.read_text(encoding="utf-8")
    new = render(old)
    if check:
        if new != old:
            print(f"✗ {DATASHEET.relative_to(_REPO)} is out of date — run scripts/render_datasheet_tables.py")
            return 1
        print(f"✓ {DATASHEET.relative_to(_REPO)} matches the data")
        return 0
    DATASHEET.write_text(new, encoding="utf-8")
    print(f"written: {DATASHEET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
