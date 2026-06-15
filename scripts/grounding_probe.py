#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/grounding_probe.py
==========================
Post-hoc difficulty annotator for augmented datasets.  For every edit
(``_aug_meta.edits[0]``: canonical ``from`` → perturbed ``to``) it records,
*independently of any system under test and without touching the DB*, how hard
the perturbed surface is to ground back to the canonical value — the objective
difficulty spectrum the paper reports.

Signals (pure string comparison of the surface↔canonical pair):
  * ``exact_ci``  — perturbed == canonical case-insensitively (baseline
                    case-insensitive exact match still grounds it → trivial).
  * ``damerau``   — Damerau distance perturbed → canonical.
  * ``substring`` — perturbed is a substring of the canonical (partial-name
                    signature → fulltext-recoverable).
  * ``class``     — exact_ci | edit_distance | substring | semantic.
                    semantic = no surface overlap (abbrev/alias) → the hardest,
                    where value-grounding / vector retrieval is required.

(True Lucene/vector ranks would need indexes built on the graphs — a separate
enhancement; the class spectrum above is index- and DB-free.)

Usage::

    python -m scripts.grounding_probe                       # all 3 datasets' _augmented_v2
    python -m scripts.grounding_probe cypherbench mindthequery zograscope
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data_augmentation import validity as V   # noqa: E402

_ORDER = ["exact_ci", "edit_distance", "substring", "semantic"]


def _classify(frm: str, to: str) -> dict:
    f_lc, t_lc = frm.lower(), to.lower()
    exact_ci = (f_lc == t_lc)
    dam = V.damerau_distance(to, frm)
    substring = (t_lc in f_lc) and not exact_ci
    if exact_ci:
        cls = "exact_ci"
    elif dam <= 2:
        cls = "edit_distance"
    elif substring:
        cls = "substring"
    else:
        cls = "semantic"
    return {"exact_ci": exact_ci, "damerau": dam, "substring": substring, "class": cls}


def _probe_dataset(dataset: str):
    d = Path(os.path.expanduser(f"~/datasets/{dataset}_augmented_v2"))
    f = d / "test.json"
    if not f.is_file():
        return None
    rows = json.load(open(f, encoding="utf-8"))
    by_class = Counter()
    by_strat_class = defaultdict(Counter)
    n = 0
    for r in rows:
        meta = r.get("_aug_meta")
        if not isinstance(meta, dict) or not meta.get("edits"):
            continue
        e = meta["edits"][0]
        probe = _classify(e["from"], e["to"])
        e["grounding_probe"] = probe
        by_class[probe["class"]] += 1
        by_strat_class[e["strategy"]][probe["class"]] += 1
        n += 1
    (d / "test.probed.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return {"n": n, "by_class": by_class, "by_strat_class": by_strat_class}


def _print_block(title, n, by_class, by_strat_class):
    print(f"\n== {title}  ({n} edits) ==")
    for c in _ORDER:
        print(f"  {c:14s} {by_class[c]:5d}  ({by_class[c]/n*100:4.1f}%)" if n else f"  {c}: 0")
    if n:
        gap = 1 - by_class["exact_ci"] / n
        print(f"  → baseline ci-exact-match FAILS on {gap*100:.1f}% (grounding gap)")
    if by_strat_class:
        print(f"  {'strategy':9s}" + "".join(f"{c:>14}" for c in _ORDER))
        for s in sorted(by_strat_class):
            print(f"  {s:9s}" + "".join(f"{by_strat_class[s][c]:>14}" for c in _ORDER))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("datasets", nargs="*",
                    default=["cypherbench", "mindthequery", "zograscope"])
    args = ap.parse_args()

    tot_class = Counter()
    tot_strat = defaultdict(Counter)
    tot_n = 0
    for ds in args.datasets:
        res = _probe_dataset(ds)
        if res is None:
            print(f"[probe] {ds}: no _augmented_v2/test.json, skipped", file=sys.stderr)
            continue
        _print_block(f"{ds}", res["n"], res["by_class"], res["by_strat_class"])
        tot_n += res["n"]
        tot_class.update(res["by_class"])
        for s, c in res["by_strat_class"].items():
            tot_strat[s].update(c)
    _print_block("ALL DATASETS", tot_n, tot_class, tot_strat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
