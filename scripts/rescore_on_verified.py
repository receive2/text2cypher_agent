#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rescore_on_verified.py
======================
Recompute evaluation metrics on the **human-verified** subset of the benchmark,
without re-running any model.

Why this exists
---------------
Human verification only ever *removes* rows (`invalid` / `source_error`); it
never changes a question or a gold query. Since ``eval_run.py`` writes one
record per example (``records.jsonl``), the experiments can be run on the frozen
release **while annotation is still in progress**, and the headline numbers
re-derived afterwards by dropping the rejected ids. That takes annotation off
the critical path.

Verdicts come from ``verification_stats.collect_labels`` — the same function the
statistics report uses — so the rows the paper says were dropped are exactly the
rows the metrics were recomputed without.

Joining evaluation records to verification ids
----------------------------------------------
Verification ids are ``<dataset>:<position>``; evaluation records carry
``(graph, qid)``. The release manifest holds both, so it is the join table.
Rows outside the verification queue were never sampled for human review and are
**kept** — they remain in the release.

Usage
-----
    python scripts/rescore_on_verified.py \\
        --eval-dir logs/my_run \\
        --key verification/verification_key.csv \\
        --annotations "verification/returns/annotator_*/verification_annotator_*.REPAIRED.csv" \\
        [--adjudicated verification/adjudicated.csv] \\
        [--pending keep|drop] \\
        [--out report/verified_metrics.md]

Writes ``summary.verified.json`` beside each ``records.jsonl`` and prints a
before/after table. Use ``--pending drop`` for a conservative bound while
adjudication is still outstanding.
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from eval_run import _summarize_records                    # noqa: E402
from verification_stats import collect_labels              # noqa: E402

# Joins by (graph, qid) -> "<dataset>:<position>". Verdicts and decisions are
# keyed by v2.1 positions, so runs made on the v2.1 files join through the
# v2.1 manifest (default). Runs made on the verified v2.2 files need no
# rescoring — every row they saw is already a released row.
DEFAULT_MANIFEST = "~/datasets/release_manifest_v2.1.jsonl"
DROP_LABELS = {"invalid", "source_error"}


def load_manifest_join(path: str) -> Dict[Tuple[str, str], str]:
    """(graph, qid) -> verification id ``<dataset>:<position>``."""
    join: Dict[Tuple[str, str], str] = {}
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("_manifest_header"):
                continue
            graph, qid = d.get("graph"), d.get("id")
            if graph is None or qid is None:
                continue
            join[(graph, qid)] = f"{d.get('dataset')}:{d.get('position')}"
    return join


def read_records(path: Path) -> List[dict]:
    recs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return recs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-dir", required=True,
                    help="directory containing <pair>/records.jsonl subdirectories")
    ap.add_argument("--key", required=True, help="verification_key.csv")
    ap.add_argument("--annotations", nargs="+", default=None,
                    help="filled annotator CSVs (globs allowed); not needed with --decisions")
    ap.add_argument("--decisions", default=None,
                    help="audit/verification/decisions.csv from the release freeze. "
                         "Preferred once it exists: every row whose action removed OR "
                         "reverted it is dropped, because a reverted row's question "
                         "changed and the old model record no longer applies to it.")
    ap.add_argument("--adjudicated", default=None, help="optional id,validity CSV")
    ap.add_argument("--calibration", nargs="*", default=None,
                    help="see verification_stats.py (default: auto-detect)")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST,
                    help=f"release manifest used as the join table (default {DEFAULT_MANIFEST})")
    ap.add_argument("--pending", choices=("keep", "drop"), default="keep",
                    help="items still awaiting adjudication: keep (default) or "
                         "drop for a conservative lower bound")
    ap.add_argument("--out", default=None, help="write the markdown table here (else stdout)")
    args = ap.parse_args(argv)

    # 1. which v2.1 rows no longer stand as evaluated
    if args.decisions:
        import csv
        drop_ids: Set[str] = set()
        pending_ids: Set[str] = set()
        n_files = 1
        with open(args.decisions, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                act = (row.get("action") or "")
                if act.startswith(("remove", "revert")):
                    drop_ids.add(row["id"])
                elif act == "pending":
                    pending_ids.add(row["id"])
        if args.pending == "drop":
            drop_ids |= pending_ids
    else:
        if not args.annotations:
            sys.exit("pass --annotations (raw verdicts) or --decisions (release freeze)")
        got = collect_labels(args.key, args.annotations, args.adjudicated, args.calibration)
        final: Dict[str, str] = got["final"]
        n_files = len(got["files"])
        drop_ids = {i for i, f in final.items() if f in DROP_LABELS}
        pending_ids = {i for i, f in final.items() if f == "pending"}
        if args.pending == "drop":
            drop_ids |= pending_ids

    # 2. join table
    join = load_manifest_join(args.manifest)
    if not join:
        sys.exit(f"manifest produced no join rows: {args.manifest}")
    drop_keys: Set[Tuple[str, str]] = {k for k, vid in join.items() if vid in drop_ids}

    # 3. rescore every pair directory
    pair_dirs = sorted(p.parent for p in Path(os.path.expanduser(args.eval_dir)).glob("*/records.jsonl"))
    if not pair_dirs:
        sys.exit(f"no <pair>/records.jsonl under {args.eval_dir}")

    L = ["# Metrics on the human-verified subset\n",
         f"- Verdicts from {'the release decisions file' if args.decisions else f'{n_files} annotator file(s)'}; "
         f"pending items **{args.pending}** ({len(pending_ids)} pending)",
         f"- Rows dropped by verification: **{len(drop_ids)}** "
         f"(invalid / source-error{'' if args.pending == 'keep' else ' / pending'})",
         f"- Rows outside the verification queue are kept (never sampled for review)\n",
         "| run | n before | n after | dropped | EA before | EA after | EM before | EM after | PSJS before | PSJS after |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]

    unmatched_total = 0
    for d in pair_dirs:
        recs = read_records(d / "records.jsonl")
        if not recs:
            continue
        dataset = d.name.split("__")[0]
        kept, dropped, unmatched = [], 0, 0
        for r in recs:
            k = (r.get("graph"), r.get("qid"))
            if k not in join:
                unmatched += 1
            if k in drop_keys:
                dropped += 1
            else:
                kept.append(r)
        unmatched_total += unmatched

        before = _summarize_records(recs, dataset)
        after = _summarize_records(kept, dataset)
        after["verified_subset"] = True
        after["dropped_by_verification"] = dropped
        after["pending_policy"] = args.pending
        (d / "summary.verified.json").write_text(
            json.dumps(after, ensure_ascii=False, indent=2), encoding="utf-8")

        L.append(f"| {d.name} | {before['n']} | {after['n']} | {dropped} | "
                 f"{before['ea']:.4f} | {after['ea']:.4f} | "
                 f"{before['em']:.4f} | {after['em']:.4f} | "
                 f"{before['psjs']:.4f} | {after['psjs']:.4f} |")

    if unmatched_total:
        L.append(f"\n> **Warning:** {unmatched_total} record(s) had no manifest entry "
                 f"for their (graph, qid) and were kept unconditionally. This means the "
                 f"evaluation ran on a different dataset build than the manifest — check "
                 f"before using these numbers.")

    report = "\n".join(L) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
