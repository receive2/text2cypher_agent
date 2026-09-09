#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
adjudication_worklist.py
========================
Write the list of items that still need a human adjudication decision, with
everything the adjudicator needs on one line, plus an empty ``validity`` column
to fill in.

An item is *pending* when its raters disagree, or agree on ``unsure``, or (for
single-annotated items) the lone rater said ``unsure``. The pre-registered
protocol (docs/VERIFICATION_PROTOCOL.md §4 step 5) resolves these to one gold
label by a third annotator / expert or by consensus — never by a model.

Verdict logic is imported from ``verification_stats.collect_labels`` so the
items listed here are exactly the ones the statistics report counts as
pending.

Usage
-----
    python scripts/adjudication_worklist.py \\
        --key verification/verification_key.csv \\
        --annotations "verification/returns/annotator_*/verification_annotator_*.REPAIRED.csv" \\
        --out verification/adjudication_worklist.csv

Fill the ``validity`` column (valid / invalid) and save the two columns
``id,validity`` as ``verification/adjudicated.csv`` — or just save the whole
worklist under that name; readers only look at those two columns. Then rerun
``verification_stats.py --adjudicated verification/adjudicated.csv``.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from verification_stats import collect_labels, expand_paths, _annotator_name, _norm  # noqa: E402

COLS = ["id", "tier", "strategy", "dataset", "graph", "original_entity", "perturbed_form",
        "augmented_question", "raters", "validity_labels", "naturalness_labels",
        "source_error_labels", "corrected_forms", "notes", "validity", "adjudicator_note"]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", required=True)
    ap.add_argument("--annotations", nargs="+", required=True)
    ap.add_argument("--adjudicated", default=None,
                    help="existing id,validity CSV — items it already resolves are omitted")
    ap.add_argument("--calibration", nargs="*", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    got = collect_labels(args.key, args.annotations, args.adjudicated, args.calibration)
    pending = sorted(i for i, f in got["final"].items() if f == "pending")

    key = {r["id"]: r for r in csv.DictReader(open(args.key, encoding="utf-8-sig"))}
    # every rater's full row, for notes / corrected_form / naturalness
    raw: Dict[str, Dict[str, dict]] = {}
    for f in expand_paths(args.annotations):
        ann = _annotator_name(f)
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            raw.setdefault(row["id"], {})[ann] = row

    out = []
    for i in pending:
        k = key.get(i, {})
        rows = raw.get(i, {})
        anns = sorted(rows)
        j = lambda field: "; ".join(f"{a}={_norm(rows[a].get(field)) or '-'}" for a in anns)
        free = lambda field: " | ".join(f"{a}: {(rows[a].get(field) or '').strip()}"
                                        for a in anns if (rows[a].get(field) or "").strip())
        out.append({
            "id": i, "tier": k.get("provenance", ""), "strategy": k.get("strategy", ""),
            "dataset": k.get("dataset", ""), "graph": k.get("graph", ""),
            "original_entity": k.get("original_entity", ""),
            "perturbed_form": k.get("perturbed_form", ""),
            "augmented_question": k.get("augmented_question", ""),
            "raters": "".join(anns),
            "validity_labels": j("validity"),
            "naturalness_labels": j("naturalness"),
            "source_error_labels": j("source_error"),
            "corrected_forms": free("corrected_form"),
            "notes": free("notes"),
            "validity": "", "adjudicator_note": "",
        })

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    by_tier: Dict[str, int] = {}
    for r in out:
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    print(f"{len(out)} items pending adjudication -> {args.out}")
    for t, n in sorted(by_tier.items()):
        print(f"  {t:12s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
