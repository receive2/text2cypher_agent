#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/make_review_file.py
===========================
Turn one or more ``needs_verification.jsonl`` queues (emitted by
``generate_augmented.py``) into a single reviewer-friendly CSV for human
verification.  Only LLM-proposed abbrev/alias/partial edits are queued —
algorithmic (casing/typo) and attested-source edits are trusted and excluded.

Usage::

    python -m scripts.make_review_file ~/datasets/cypherbench_augmented_v2/needs_verification.jsonl \
        -o ~/datasets/review_queue.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Columns the reviewer FILLS IN are prefixed review_*.
_FIELDS = [
    "review_id", "graph", "strategy", "source",
    "original_entity", "perturbed_form", "augmented_question",
    "review_verdict",       # keep | fix | drop
    "review_corrected_to",  # if verdict=fix, the corrected perturbed form
    "review_notes",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("queues", nargs="+", help="needs_verification.jsonl file(s)")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    rows = []
    n = 0
    for q in args.queues:
        for line in Path(q).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            n += 1
            rows.append({
                "review_id": f"{e.get('graph','?')}-{n:04d}",
                "graph": e.get("graph", ""),
                "strategy": e.get("strategy", ""),
                "source": e.get("source", ""),
                "original_entity": e.get("from", ""),
                "perturbed_form": e.get("to", ""),
                "augmented_question": e.get("nl", ""),
                "review_verdict": "",
                "review_corrected_to": "",
                "review_notes": "",
            })

    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"[review] wrote {len(rows)} edits to review → {out}")
    # quick per-strategy / per-graph tally
    from collections import Counter
    bys = Counter(r["strategy"] for r in rows)
    byg = Counter(r["graph"] for r in rows)
    print(f"  by strategy: {dict(bys)}")
    print(f"  by graph:    {dict(byg)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
