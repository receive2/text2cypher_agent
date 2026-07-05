#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_gold_errors.py
====================
Standalone, **read-only** diagnostic for the dataset-audit team: list every
example whose **gold cypher fails to execute** ("gold error").

Why this exists
---------------
The eval harness makes **no judgement about dataset quality**: a gold query that
does not run is scored exactly like any other failure (it counts as 0 and stays
in the denominator — see ``eval/difficulty.py``). Deciding whether such a gold is
a genuine benchmark defect (and fixing or removing it) is a **dataset-audit**
task, deliberately kept OUT of the eval code. This script surfaces the candidates
for that audit; it never edits the dataset and never touches the metrics.

What it reads
-------------
The per-run record dirs written by ``eval_run`` (see ``eval_paths``):
``<runs-root>/<dataset>__<graph>__<method>/records.jsonl``. A record is a gold
error iff its ``error`` field starts with ``"gold:"``. Gold execution is
method-independent, so the same (dataset, graph, qid) is reported once even if it
errored under several methods.

Usage
-----
    python audit_gold_errors.py                       # scan logs/runs, write audit/gold_errors.jsonl
    python audit_gold_errors.py --runs-root logs/runs --out audit/gold_errors.jsonl --csv
    python audit_gold_errors.py --graph covid         # filter to one graph

Output
------
* ``--out`` JSONL: one object per unique broken gold —
  ``{dataset, graph, qid, category, error, gold_cypher, question, seen_in_methods}``
* optional ``--csv`` sibling file (same rows, flattened)
* a summary table to stdout (per graph + per category counts)

See ``docs/GOLD_ERROR_AUDIT.md`` for the step-by-step fix/remove workflow.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _parse_run_dir(name: str) -> Optional[Tuple[str, str, str]]:
    """``<dataset>__<graph>__<method>`` → (dataset, graph, method); ``None`` if it
    doesn't carry the three ``__``-joined parts. (Local copy so this tool has no
    eval-code import dependency.)"""
    parts = name.split("__")
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 and all(parts) else None


def _is_gold_error(rec: Dict[str, Any]) -> bool:
    return str(rec.get("error") or "").startswith("gold:")


def _categorize(err: str) -> str:
    """Best-effort triage of a gold-cypher error message. The boundary between
    'genuine bug' and 'Neo4j version/dialect' is heuristic — verify before acting
    (see the doc)."""
    e = err.lower()
    if "timeout" in e:
        return "timeout (likely OUR env, not the gold)"
    if "not defined" in e or "variable" in e:
        return "undefined variable (genuine gold bug)"
    if "has been replaced" in e or "point.distance" in e or "deprecated" in e:
        return "deprecated function / version (dialect)"
    if "cannot be parsed" in e or "datetime" in e or "temporal" in e:
        return "datetime parse (dialect/format)"
    if "unknown function" in e or "no procedure" in e or "unknown procedure" in e:
        return "missing function/procedure (version/APOC)"
    if "no such property" in e or ("property" in e and "unknown" in e):
        return "missing property (possibly schema)"
    if "no such label" in e or ("label" in e and "unknown" in e):
        return "missing label (possibly schema)"
    if "typeerror" in e:
        return "type error (genuine gold bug)"
    if "syntaxerror" in e:
        return "other syntax error (mixed: bug or dialect)"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser(description="List examples whose GOLD cypher fails to execute.")
    ap.add_argument("--runs-root", default="logs/runs",
                    help="Root holding <dataset>__<graph>__<method>/ run dirs (default: logs/runs).")
    ap.add_argument("--out", default="audit/gold_errors.jsonl",
                    help="JSONL output path (default: audit/gold_errors.jsonl).")
    ap.add_argument("--csv", action="store_true",
                    help="Also write a flattened CSV next to --out.")
    ap.add_argument("--graph", default=None, help="Filter to a single graph name.")
    ap.add_argument("--dataset", default=None, help="Filter to a single dataset key.")
    args = ap.parse_args()

    root = Path(args.runs_root)
    if not root.is_dir():
        print(f"[audit_gold_errors] runs-root not found: {root}", file=sys.stderr)
        return 1

    # key = (dataset, graph, qid) → record (first seen wins; methods accumulated)
    found: "OrderedDict[Tuple[str, str, str], Dict[str, Any]]" = OrderedDict()
    scanned_dirs = 0
    for rec_path in sorted(root.glob("*/records.jsonl")):
        parsed = _parse_run_dir(rec_path.parent.name)
        if parsed is None:
            continue
        dataset, graph, method = parsed
        if args.dataset and dataset != args.dataset:
            continue
        if args.graph and graph != args.graph:
            continue
        scanned_dirs += 1
        for line in rec_path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not _is_gold_error(rec):
                continue
            qid = rec.get("qid")
            key = (dataset, graph, qid)
            if key in found:
                found[key]["seen_in_methods"].append(method)
                continue
            err = str(rec.get("error") or "")
            found[key] = {
                "dataset":         dataset,
                "graph":           graph,
                "qid":             qid,
                "category":        _categorize(err),
                "error":           err,
                "gold_cypher":     rec.get("gold_cypher", ""),
                "question":        rec.get("question", ""),
                "seen_in_methods": [method],
            }

    rows = list(found.values())

    # ── write JSONL ──────────────────────────────────────────────────────────
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    if args.csv:
        csv_path = out_path.with_suffix(".csv")
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["dataset", "graph", "qid", "category", "error", "gold_cypher", "question"])
            for r in rows:
                w.writerow([r["dataset"], r["graph"], r["qid"], r["category"],
                            r["error"], r["gold_cypher"], r["question"]])

    # ── summary to stdout ────────────────────────────────────────────────────
    by_graph = Counter((r["dataset"], r["graph"]) for r in rows)
    by_cat = Counter(r["category"] for r in rows)
    print(f"Scanned {scanned_dirs} run dir(s) under {root}")
    print(f"Unique broken golds: {len(rows)}  (written to {out_path}"
          + (f" + {out_path.with_suffix('.csv')}" if args.csv else "") + ")\n")
    if rows:
        print("By graph:")
        for (ds, g), n in sorted(by_graph.items()):
            print(f"  {ds}/{g:18s} {n}")
        print("\nBy category (heuristic — verify before acting):")
        for c, n in by_cat.most_common():
            print(f"  {n:4d}  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
