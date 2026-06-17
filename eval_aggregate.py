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


def _render_dataset_table(
    dataset:      str,
    cells:        Dict[str, Dict[str, Any]],
    graphs:       List[str],
    bucket_order: tuple = _BUCKET_ORDER,
    axis:         str   = "difficulty",
) -> List[str]:
    """Render one dataset table as Markdown lines (readable in a terminal too)."""
    lines: List[str] = [
        f"\n### {dataset} — by {axis}",
        "",
        f"| {axis} | EA | EM | PSJS | n | n_err |",
        "|---|---|---|---|---|---|",
    ]
    for b in bucket_order:
        cell = cells.get(b)
        if not cell or cell.get("n", 0) == 0:
            continue
        lines.append(
            f"| {b} | {_fmt_metric(cell.get('ea'))} | {_fmt_metric(cell.get('em'))} "
            f"| {_fmt_metric(cell.get('psjs'))} | {cell.get('n', 0)} "
            f"| {cell.get('n_errors', 0)} |"
        )
    lines.append("")
    lines.append(
        f"_aggregated from {len(graphs)} graph"
        f"{'s' if len(graphs) != 1 else ''}: {', '.join(graphs)}_"
    )
    return lines


def _load_run_meta(summary_path: Path) -> Dict[str, Any]:
    """Return the ``run_meta`` block from a summary.json (``{}`` if absent)."""
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        rm = data.get("run_meta")
        return rm if isinstance(rm, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _render_meta_header(
    metas:    List[Dict[str, Any]],
    datasets: List[str],
    graphs:   List[str],
    out_dir:  Path,
    generated_at: str,
) -> List[str]:
    """Build the report's metadata header: modes, graphs, and key config so the
    table is self-describing (which mode produced these numbers, on which
    graphs, under what model / retrieval settings)."""
    def _distinct(key: str) -> List[str]:
        seen: List[str] = []
        for m in metas:
            v = m.get(key)
            if v is not None and str(v) not in seen:
                seen.append(str(v))
        return seen

    modes = _distinct("ner_mode") or _distinct("ner_mode_env") or ["(unknown)"]
    lines = [
        "# Experiment Report",
        "",
        f"- **Generated:** {generated_at}",
        f"- **Source:** `{out_dir}`",
        f"- **NER mode(s):** {', '.join(modes)}",
        f"- **Datasets:** {', '.join(datasets)}",
        f"- **Graphs:** {', '.join(graphs)}",
    ]
    # Key config — only emit rows we actually captured.
    cfg_fields = [
        ("ner_llm",                    "NER LLM"),
        ("cypher_llm",                 "Cypher LLM"),
        ("qa_llm",                     "QA LLM"),
        ("tool_retrieval_mode",        "Tool retrieval"),
        ("hybrid_strategy",            "Hybrid strategy"),
        ("tool_select_top_k",          "Tool-select top-k"),
        ("values_per_tool",            "Values/tool (ReAct)"),
        ("plan_exec_tools_per_entity", "plan_exec tools/entity"),
        ("plan_exec_values_per_tool",  "plan_exec values/tool"),
    ]
    for key, label in cfg_fields:
        vals = _distinct(key)
        if vals:
            lines.append(f"- **{label}:** {', '.join(vals)}")
    return lines


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
    metas: List[Dict[str, Any]] = []
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
        rm = _load_run_meta(sp)
        if rm:
            metas.append(rm)

    if not by_dataset:
        print("[eval_aggregate] No recognisable summaries to aggregate.", file=sys.stderr)
        return 1

    # Timestamp the report (filename + header). Prefer the run's own timestamp
    # when all summaries agree; otherwise stamp at aggregation time.
    from datetime import datetime
    now = datetime.now().astimezone()
    generated_at = now.isoformat(timespec="seconds")
    stamp = now.strftime("%Y%m%d_%H%M%S")

    all_graphs = sorted({g for ds in by_dataset.values() for g, _ in ds})
    report: List[str] = _render_meta_header(
        metas, sorted(by_dataset), all_graphs, out_dir, generated_at
    )

    for dataset in sorted(by_dataset):
        pairs = sorted(by_dataset[dataset])
        records: List[Dict[str, Any]] = []
        graphs: List[str] = []
        for graph, rp in pairs:
            graphs.append(graph)
            records.extend(_load_records(rp))

        if not records:
            report.append(f"\n### {dataset}")
            report.append(f"\n_(no records loaded; graphs scanned: {graphs})_")
            continue

        by_diff = aggregate_by_difficulty(records)
        report += _render_dataset_table(dataset, by_diff, graphs,
                                        bucket_order=_BUCKET_ORDER, axis="difficulty")

        # Per-strategy table — only for augmented datasets (records carry a
        # non-null "strategy"). Skipped silently for the base/non-augmented sets.
        by_strategy = aggregate_by_strategy(records)
        if _has_strategy_rows(by_strategy):
            report += _render_dataset_table(dataset, by_strategy, graphs,
                                            bucket_order=_STRATEGY_ORDER, axis="strategy")

    text = "\n".join(report) + "\n"
    print(text)

    report_path = out_dir / f"report_{stamp}.md"
    report_path.write_text(text, encoding="utf-8")
    print(f"[eval_aggregate] wrote report → {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
