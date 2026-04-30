#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_run.py
===========
Minimal driver for the text-to-Cypher evaluation harness.

This script intentionally has **no CLI flags** — every parameter lives
in :mod:`eval_config`, which the user hand-edits.  Run::

    python eval_run.py

The script:

1. Imports the config module-level variables from ``eval_config``.
2. Imports ``evaluate_dataset`` from each ``eval/metrics_*.py``.
3. Iterates over ``DATASETS`` and invokes the matching loader.
4. Writes per-dataset JSONL records + a summary JSON to ``OUT_DIR``.
5. Prints a small summary table (dataset × {EA, EM, PSJS, n, n_scored,
   n_errors}) to stdout.

Per-dataset output files
------------------------
For each dataset it writes:

    <OUT_DIR>/<dataset>.jsonl          — one evaluate_one() record per line
    <OUT_DIR>/<dataset>.summary.json   — aggregate summary (no records)

Errors loading or running a dataset are caught and reported in the
summary table — one bad dataset does not abort the others.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import eval_config as cfg
from eval.metrics_CypherBench  import evaluate_dataset as eval_cypherbench
from eval.metrics_MindTheQuery import evaluate_dataset as eval_mindthequery
from eval.metrics_ZOGRASCOPE   import evaluate_dataset as eval_zograscope


# Mapping of dataset name → (evaluate_dataset fn, config path attribute).
_DISPATCH = {
    "cypherbench":  (eval_cypherbench,  "CYPHERBENCH_PATH"),
    "mindthequery": (eval_mindthequery, "MINDTHEQUERY_PATH"),
    "zograscope":   (eval_zograscope,   "ZOGRASCOPE_PATH"),
}


def _summary_only(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the (potentially huge) per-example records list."""
    return {k: v for k, v in summary.items() if k != "records"}


def _fmt_metric(v: Any) -> str:
    if v is None:
        return "  n/a"
    try:
        return f"{float(v):.4f}"
    except Exception:
        return str(v)


def _print_table(rows: Dict[str, Dict[str, Any]]) -> None:
    """Render the dataset × metric summary table."""
    header = (
        f"{'dataset':<14}  {'EA':>7}  {'EM':>7}  {'PSJS':>7}  "
        f"{'n':>5}  {'n_ea':>5}  {'n_em':>5}  {'n_psjs':>6}  {'n_err':>5}"
    )
    print()
    print("═" * len(header))
    print(header)
    print("─" * len(header))
    for name, summary in rows.items():
        if "_error" in summary:
            print(f"{name:<14}  {summary['_error']}")
            continue
        ns = summary.get("n_scored", {}) or {}
        print(
            f"{name:<14}  "
            f"{_fmt_metric(summary.get('ea')):>7}  "
            f"{_fmt_metric(summary.get('em')):>7}  "
            f"{_fmt_metric(summary.get('psjs')):>7}  "
            f"{summary.get('n', 0):>5}  "
            f"{ns.get('ea', 0):>5}  "
            f"{ns.get('em', 0):>5}  "
            f"{ns.get('psjs', 0):>6}  "
            f"{summary.get('n_errors', 0):>5}"
        )
    print("═" * len(header))
    print()


def main() -> int:
    out_dir = Path(getattr(cfg, "OUT_DIR", "logs/eval"))
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries: Dict[str, Dict[str, Any]] = {}

    for dataset in cfg.DATASETS:
        if dataset not in _DISPATCH:
            print(
                f"[eval_run] Unknown dataset {dataset!r}; "
                f"expected one of {sorted(_DISPATCH)}",
                file=sys.stderr,
            )
            summaries[dataset] = {"_error": f"unknown dataset {dataset!r}"}
            continue

        fn, path_attr = _DISPATCH[dataset]
        path = getattr(cfg, path_attr, None)
        if not path:
            summaries[dataset] = {"_error": f"{path_attr} not set in eval_config"}
            continue

        out_jsonl   = out_dir / f"{dataset}.jsonl"
        out_summary = out_dir / f"{dataset}.summary.json"

        print(f"\n[eval_run] {dataset}: path={path}")
        try:
            summary = fn(
                path    = path,
                limit   = cfg.LIMIT,
                out     = str(out_jsonl),
                verbose = cfg.VERBOSE,
            )
        except Exception as exc:  # noqa: BLE001 — surface every failure
            print(f"[eval_run] {dataset} FAILED: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            summaries[dataset] = {"_error": f"{type(exc).__name__}: {exc}"}
            continue

        with out_summary.open("w", encoding="utf-8") as fh:
            json.dump(_summary_only(summary), fh, ensure_ascii=False, indent=2)

        summaries[dataset] = summary

    _print_table(summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
