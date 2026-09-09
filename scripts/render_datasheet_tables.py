#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_datasheet_tables.py
==========================
Single source of truth for every number in docs/DATASHEET.md: recompute all
figure/table blocks from the released datasets and splice them into the
AUTOGEN-marked regions. **Never hand-edit those regions** — rerun this script
after any data change (and after post-annotation adjudication).

Blocks: HEADLINE (exact-match-defeat rate), COMPOSITION (§2), DIFFICULTY (§4
grounding spectrum), REALIZED (§6 per-graph mix + provenance + census counts).
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
    L = [f"{len(by)} datasets, {graphs} graphs, **{n:,}** perturbed examples "
         f"(test split, post-curation; see §7 curation log).", "",
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
    L = ["| class | meaning | all | cypherbench | mtq | zograscope |",
         "|---|---|--:|--:|--:|--:|"]
    def pct(sub, c):
        return 100 * sum(1 for r in sub if r["gclass"] == c) / len(sub)
    for c in ("exact_ci", "edit_distance", "substring", "semantic"):
        cells = [f"{pct(rows, c):.1f}%"] + \
                [f"{pct([r for r in rows if r['dataset']==d], c):.1f}%" for d in _DATASETS]
        L.append(f"| `{c}` | {meaning[c]} | " + " | ".join(cells) + " |")
    return "\n".join(L)


def block_realized(rows):
    n = len(rows)
    L = ["Post-curation realized mix (regenerate with "
         "`scripts/render_datasheet_tables.py`; canonical figures are "
         "post-adjudication). `census` = LLM- + attested-provenance edits "
         "(all human-verified, Tier 1).", "",
         "| dataset | graph | n | casing | typo | partial | abbrev | alias | census |",
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
             f"**{al:.1f}%**. Deviations from the §3 targets are supply "
             f"ceilings, measured in `audit/APPLICABILITY_CEILING.md`; headline "
             f"metrics macro-average over strategies.")
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
    L = [f"**Release {sm['version']}** — {sm['rows_in']:,} rows in → "
         f"**{sm['rows_out']:,}** released "
         f"({sm['actions'].get('remove_total', 0)} removed, "
         f"{sm['actions'].get('revert_total', 0)} reverted to a certified prior "
         f"algorithmic form, {sm['actions'].get('pending', 0)} pending). "
         f"Naturalness policy: `{sm['naturalness_policy']}`. "
         f"Verdicts from {len(st['annotators'])} annotators over {st['items']:,} "
         f"measured items ({st['double_annotated']:,} double-annotated; "
         f"{st['calibration_ids_in_queue']} calibration items excluded).", "",
         f"Inter-annotator agreement (validity): Krippendorff's α = **{f(st['alpha'])}**, "
         f"Gwet's AC1 = **{f(st['ac1'])}**, disagreement rate "
         f"{100*st['disagreements']/max(st['double_annotated'],1):.1f}%.", "",
         "| provenance | n | validity % [95% CI] | α | AC1 | raw agr (n₂) | action |",
         "|---|--:|---|--:|--:|---|---|"]
    act = {"llm": "invalid → revert/remove", "attested": "invalid → revert/remove",
           "algorithmic": "rate only (no removals)"}
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
    L += ["", "Per-row verdicts (anonymised annotator letters), the blind key, the "
          "calibration reference answers and the full statistics report ship in "
          "`audit/verification/`; `decisions.csv` maps every v2.1 row to its "
          "action and its position in the released files."]
    return "\n".join(L)


def main() -> int:
    rows = load()
    s = DATASHEET.read_text(encoding="utf-8")
    for tag, content in (("HEADLINE", block_headline(rows)),
                         ("COMPOSITION", block_composition(rows)),
                         ("DIFFICULTY", block_difficulty(rows)),
                         ("REALIZED", block_realized(rows)),
                         ("VERIFICATION", block_verification())):
        pat = re.compile(f"<!-- AUTOGEN:{tag} -->.*?<!-- /AUTOGEN:{tag} -->",
                         re.DOTALL)
        if not pat.search(s):
            print(f"  ✗ marker missing: {tag}")
            return 1
        s = pat.sub(f"<!-- AUTOGEN:{tag} -->\n{content}\n<!-- /AUTOGEN:{tag} -->", s)
        print(f"  ✓ {tag} rendered")
    DATASHEET.write_text(s, encoding="utf-8")
    print(f"written: {DATASHEET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
