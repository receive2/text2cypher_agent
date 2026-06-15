#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/backfill_query_difficulty.py
====================================
Tag every row in the existing ``~/datasets/*_augmented_v2/test.json`` with
``_aug_meta.query_difficulty`` (one of ``easy`` / ``medium`` / ``hard`` /
``None``), computed by :func:`eval.difficulty.classify` from the row's gold
Cypher.

We do this as a backfill rather than re-running ``scripts/generate_augmented``
because the latter would also re-roll the LLM-perturbed ``nl`` field — slow,
costly, and irrelevant to a difficulty-label refresh.

Usage
-----
    python -m scripts.backfill_query_difficulty            # all three datasets
    python -m scripts.backfill_query_difficulty --dry-run  # print summary only

Idempotent: re-running just re-classifies; no double-tagging.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import List

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from eval.difficulty import classify  # noqa: E402

_DATA_ROOT = Path.home() / "datasets"
_DATASETS = ("cypherbench", "mindthequery", "zograscope")
_TARGETS = ("test.json", "test.probed.json")


def _backfill_file(path: Path, *, dry_run: bool) -> Counter:
    """Add `_aug_meta.query_difficulty` to every row.  Returns bucket counter."""
    rows: List[dict] = json.loads(path.read_text())
    c: Counter = Counter()
    changed = 0
    for r in rows:
        meta = r.get("_aug_meta")
        if not isinstance(meta, dict):
            # Skip rows without `_aug_meta` (shouldn't happen post-augmentation;
            # could happen on intermediate test fixtures).
            c["skipped:no_aug_meta"] += 1
            continue
        bucket = classify(r.get("gold_cypher"))
        prev = meta.get("query_difficulty")
        if prev != bucket:
            changed += 1
        meta["query_difficulty"] = bucket
        c[bucket if bucket is not None else "none"] += 1
    n = sum(v for k, v in c.items() if not k.startswith("skipped"))
    print(f"  {path.relative_to(Path.home())}: "
          f"n={n} changed={changed}  "
          + "  ".join(f"{k}={v}" for k, v in c.items()))
    if not dry_run:
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Classify and print summary, do NOT write files.")
    ap.add_argument("--dataset", choices=_DATASETS, action="append",
                    help="Restrict to a subset of datasets (default: all 3).")
    args = ap.parse_args()
    datasets = args.dataset or list(_DATASETS)

    pooled: Counter = Counter()
    print(f"Backfill query_difficulty into _aug_meta "
          f"({'DRY RUN' if args.dry_run else 'writing files'})")
    for ds in datasets:
        d = _DATA_ROOT / f"{ds}_augmented_v2"
        if not d.is_dir():
            print(f"  ! {ds}: dir missing, skipping ({d})")
            continue
        print(f"[{ds}]")
        for fn in _TARGETS:
            p = d / fn
            if p.is_file():
                pooled += _backfill_file(p, dry_run=args.dry_run)
            else:
                print(f"  {p.name}: not found, skipping")
    print()
    print(f"POOLED: " + "  ".join(f"{k}={v}" for k, v in pooled.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
