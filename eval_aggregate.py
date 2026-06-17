#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_aggregate.py
=================
Print the bucketed per-dataset metric table over every per-pair record
file currently sitting in :data:`eval_config.OUT_DIR`.

This script is the *reader* half of the per-graph eval harness.  The
*writer* half — :mod:`eval_run` — produces one
``<dataset>__<graph>.records.jsonl`` + ``<dataset>__<graph>.summary.json``
pair per ``(dataset, graph)`` it evaluates.  This script:

    1. Scans :data:`eval_config.OUT_DIR` for ``*.summary.json`` files.
    2. Groups them by dataset (the ``<dataset>__<graph>`` filename
       prefix carries both pieces).
    3. For each dataset, loads every ``.records.jsonl`` file that
       contributed and recomputes the bucketed table by re-aggregating
       the records with :func:`eval.difficulty.aggregate_by_difficulty`.
    4. Prints one table per dataset and a footer naming the graphs that
       contributed.

Why re-aggregate from records and not from summaries?
-----------------------------------------------------
Summaries are pre-aggregated *per graph*.  Combining N graph-level
summaries into a dataset-level summary would require weighting by ``n``
on every metric; re-running the (cheap) aggregation over the union of
all records is simpler and matches how the per-graph summaries
themselves are produced.

The script reads everything from :data:`eval_config.OUT_DIR` and takes
no CLI arguments.  Single-graph reporting is supported as a first-class
case — pass a single pair through ``EVAL_PAIRS`` and run this script;
the table prints with one graph in the footer.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import eval_config as cfg
from eval.difficulty import (
    aggregate_by_difficulty,
    aggregate_by_strategy,
    STRATEGY_BUCKETS,
)


# Bucket print order; rows where ``n == 0`` are skipped silently so
# datasets that don't populate every bucket don't print empty lines.
_BUCKET_ORDER = ("all", "easy", "medium", "hard")
_STRATEGY_ORDER = ("all",) + STRATEGY_BUCKETS


# ──────────────────────────────────────────────────────────────────────────────
# 1. Filename parsing
# ──────────────────────────────────────────────────────────────────────────────

_SUMMARY_SUFFIX = ".summary.json"
_RECORDS_SUFFIX = ".records.jsonl"


def _parse_pair_from_summary(path: Path) -> tuple[str, str] | None:
    """
    Return ``(dataset, graph)`` parsed from a ``<dataset>__<graph>.summary.json``
    filename.  Returns ``None`` if the filename doesn't match the layout.
    """
    name = path.name
    if not name.endswith(_SUMMARY_SUFFIX):
        return None
    stem = name[: -len(_SUMMARY_SUFFIX)]
    if "__" not in stem:
        return None
    dataset, _, graph = stem.partition("__")
    if not dataset or not graph:
        return None
    return dataset, graph


# ──────────────────────────────────────────────────────────────────────────────
# 2. Records loader
# ──────────────────────────────────────────────────────────────────────────────

def _load_records(records_path: Path) -> List[Dict[str, Any]]:
    if not records_path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    with records_path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(
                    f"[eval_aggregate] WARN: skipping malformed JSONL line "
                    f"{line_no} of {records_path}: {exc}",
                    file=sys.stderr,
                )
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 3. Table rendering (mirrors the previous eval_run._print_dataset_table)
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_metric(v: Any) -> str:
    if v is None:
        return "  n/a"
    try:
        return f"{float(v):.4f}"
    except Exception:
        return str(v)


def _print_dataset_table(
    dataset:      str,
    cells:        Dict[str, Dict[str, Any]],
    graphs:       List[str],
    bucket_order: tuple = _BUCKET_ORDER,
    axis:         str   = "difficulty",
) -> None:
    header = (
        f"{axis:<8}  {'EA':>7}  {'EM':>7}  {'PSJS':>7}  "
        f"{'n':>5}  {'n_err':>5}"
    )
    print(f"\n══ {dataset} — by {axis} ══")
    print(header)
    print("─" * len(header))
    for b in bucket_order:
        cell = cells.get(b)
        if not cell or cell.get("n", 0) == 0:
            continue
        print(
            f"{b:<8}  "
            f"{_fmt_metric(cell.get('ea')):>7}  "
            f"{_fmt_metric(cell.get('em')):>7}  "
            f"{_fmt_metric(cell.get('psjs')):>7}  "
            f"{cell.get('n', 0):>5}  "
            f"{cell.get('n_errors', 0):>5}"
        )
    print(f"  (aggregated from {len(graphs)} graph{'s' if len(graphs) != 1 else ''}: {graphs})")


def _has_strategy_rows(by_strategy: Dict[str, Dict[str, Any]]) -> bool:
    """True iff at least one *named* strategy bucket has examples — i.e. this is
    an augmented dataset. Non-augmented datasets populate only ``"all"``, so we
    skip the (otherwise misleading all-in-one-row) strategy table for them."""
    return any(by_strategy.get(b, {}).get("n", 0) > 0 for b in STRATEGY_BUCKETS)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    out_dir = Path(getattr(cfg, "OUT_DIR", "logs/eval"))
    if not out_dir.is_dir():
        print(
            f"[eval_aggregate] OUT_DIR {out_dir} does not exist — "
            "nothing to aggregate.  Run `python eval_run.py` first.",
            file=sys.stderr,
        )
        return 1

    summaries = sorted(out_dir.glob(f"*{_SUMMARY_SUFFIX}"))
    if not summaries:
        print(
            f"[eval_aggregate] No *{_SUMMARY_SUFFIX} files found under "
            f"{out_dir}. Run `python eval_run.py` first.",
            file=sys.stderr,
        )
        return 1

    # dataset -> [(graph, records_path), ...]
    by_dataset: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for sp in summaries:
        parsed = _parse_pair_from_summary(sp)
        if parsed is None:
            print(
                f"[eval_aggregate] WARN: skipping unrecognised filename "
                f"{sp.name} (expected <dataset>__<graph>.summary.json).",
                file=sys.stderr,
            )
            continue
        dataset, graph = parsed
        records_path = sp.with_name(f"{dataset}__{graph}{_RECORDS_SUFFIX}")
        by_dataset[dataset].append((graph, records_path))

    if not by_dataset:
        print("[eval_aggregate] No recognisable summaries to aggregate.", file=sys.stderr)
        return 1

    for dataset in sorted(by_dataset):
        pairs = sorted(by_dataset[dataset])
        records: List[Dict[str, Any]] = []
        graphs: List[str] = []
        for graph, rp in pairs:
            graphs.append(graph)
            records.extend(_load_records(rp))

        if not records:
            # Defensive: summaries existed but records files were empty
            # or missing.  Still print a header so the user can see the
            # state.
            print(f"\n══ {dataset} ══")
            print(f"  (no records loaded; graphs scanned: {graphs})")
            continue

        by_diff = aggregate_by_difficulty(records)
        _print_dataset_table(dataset, by_diff, graphs,
                             bucket_order=_BUCKET_ORDER, axis="difficulty")

        # Per-strategy table — only for augmented datasets (records carry a
        # non-null "strategy"). Skipped silently for the base/non-augmented sets.
        by_strategy = aggregate_by_strategy(records)
        if _has_strategy_rows(by_strategy):
            _print_dataset_table(dataset, by_strategy, graphs,
                                 bucket_order=_STRATEGY_ORDER, axis="strategy")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
