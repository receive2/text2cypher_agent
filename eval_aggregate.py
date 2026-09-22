#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_aggregate.py
=================
Print the bucketed per-dataset metric table over every per-pair record
file currently sitting in :data:`eval_config.OUT_DIR`.

This script is the *reader* half of the per-graph eval harness.  The
*writer* half — :mod:`eval_run` — produces one canonical run directory
``<dataset>__<graph>__<method>/`` (records.jsonl + summary.json) per
``(dataset, graph, method)`` it evaluates (see :mod:`eval_paths`).  This script:

    1. Scans :data:`eval_config.OUT_DIR` for ``*/summary.json`` run dirs.
    2. Groups them by ``(dataset, method)`` (parsed from the run-dir name).
    3. For each group, loads every ``records.jsonl`` that contributed and
       recomputes the bucketed table by re-aggregating the records with
       :func:`eval.difficulty.aggregate_by_difficulty`.
    4. Prints one table block per ``(dataset, method)`` and a footer naming the
       graphs that contributed.

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
import eval_paths
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
# Run-dir parsing lives in eval_paths.parse_run_dir (single source of truth for
# the <dataset>__<graph>__<method>/ convention).
# ──────────────────────────────────────────────────────────────────────────────


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


def _aligned_table(headers: List[str], rows: List[List[str]], right: set) -> List[str]:
    """Render a Markdown table with padded, fixed-width columns — text columns
    left-justified, columns in *right* right-justified (numbers) — so the raw
    text is aligned and viewers honour the ``---:`` alignment markers."""
    cols = len(headers)
    width = [len(str(headers[i])) for i in range(cols)]
    for r in rows:
        for i in range(cols):
            width[i] = max(width[i], len(str(r[i])))

    def cell(value: Any, i: int) -> str:
        s = str(value)
        return s.rjust(width[i]) if i in right else s.ljust(width[i])

    out = ["| " + " | ".join(cell(headers[i], i) for i in range(cols)) + " |"]
    out.append(
        "| " + " | ".join(
            ("-" * (width[i] - 1) + ":") if i in right else ("-" * width[i])
            for i in range(cols)
        ) + " |"
    )
    for r in rows:
        out.append("| " + " | ".join(cell(r[i], i) for i in range(cols)) + " |")
    return out


def _render_dataset_table(
    dataset:      str,
    cells:        Dict[str, Dict[str, Any]],
    graphs:       List[str],
    bucket_order: tuple = _BUCKET_ORDER,
    axis:         str   = "difficulty",
) -> List[str]:
    """Render one dataset table as aligned Markdown (readable in a terminal too)."""
    headers = [axis, "EA", "PSJS", "n", "err"]   # EM is not reported: near-zero by construction on perturbed questions
    rows: List[List[str]] = []
    for b in bucket_order:
        c = cells.get(b)
        if not c or c.get("n", 0) == 0:
            continue
        rows.append([
            b,
            _fmt_metric(c.get("ea")), _fmt_metric(c.get("psjs")),
            str(c.get("n", 0)), str(c.get("n_errors", 0)),
        ])

    lines: List[str] = [f"\n### {dataset} — by {axis}", ""]
    lines += _aligned_table(headers, rows, right={1, 2, 3, 4, 5})
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
        f"- **Mode(s):** {', '.join(modes)}",
        f"- **Datasets:** {', '.join(datasets)}",
        f"- **Graphs:** {', '.join(graphs)}",
    ]
    # Value-linking axes (only emit the ones captured by run_meta).
    axis_fields = [
        ("val_link_mode",  "VAL_LINK_MODE"),
        ("agent_type",     "AGENT_TYPE"),
        ("retrieval_type", "RETRIEVAL_TYPE"),
        ("tool_type",      "TOOL_TYPE"),
    ]
    for key, label in axis_fields:
        vals = _distinct(key)
        if vals:
            lines.append(f"- **{label}:** {', '.join(vals)}")
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

    # Canonical layout (eval_paths): one dir per run, named
    # <dataset>__<graph>__<method>/ holding records.jsonl + summary.json.
    summaries = sorted(out_dir.glob(f"*/summary.json"))
    if not summaries:
        print(
            f"[eval_aggregate] No */summary.json found under {out_dir}. "
            "Run `python eval_run.py` first.",
            file=sys.stderr,
        )
        return 1

    # Runs are timestamped (eval_paths): several run dirs may exist per
    # (dataset, graph, method) triple. Aggregate ONLY the newest run of each
    # triple — a plain max() on the stamp, where the legacy unstamped layout
    # parses with stamp "" and therefore loses to any stamped re-run.
    latest: dict[tuple[str, str, str], tuple[str, Path]] = {}
    for sp in summaries:
        parsed = eval_paths.parse_run_dir_stamped(sp.parent)
        if parsed is None:
            print(
                f"[eval_aggregate] WARN: skipping unrecognised run dir "
                f"{sp.parent.name} (expected <dataset>__<graph>__<method>"
                f"[__<stamp>]/).",
                file=sys.stderr,
            )
            continue
        dataset, graph, method, stamp = parsed
        # Runs recorded before the model became part of the method segment carry
        # no "@model". Recover it from run_meta so a legacy run and a re-run of
        # the *same* model collapse to one key (newest wins) instead of showing
        # up as two rows for what is one configuration.
        if "@" not in method:
            legacy_model = eval_paths.run_meta_model(sp.parent)
            if legacy_model:
                method = eval_paths.method_tag_join(method, legacy_model)
        key = (dataset, graph, method)
        if key not in latest or stamp > latest[key][0]:
            latest[key] = (stamp, sp)

    # (dataset, method) -> [(graph, records_path), ...]. Method is part of the
    # group key so a five-method sweep in one OUT_DIR prints one table block per
    # (dataset, method) instead of silently pooling different methods together.
    by_group: dict[tuple[str, str], list[tuple[str, Path]]] = defaultdict(list)
    metas: List[Dict[str, Any]] = []
    for (dataset, graph, method), (_stamp, sp) in sorted(latest.items()):
        records_path = sp.with_name("records.jsonl")
        by_group[(dataset, method)].append((graph, records_path))
        rm = _load_run_meta(sp)
        if rm:
            metas.append(rm)

    if not by_group:
        print("[eval_aggregate] No recognisable run dirs to aggregate.", file=sys.stderr)
        return 1

    # Timestamp the report (filename + header). Prefer the run's own timestamp
    # when all summaries agree; otherwise stamp at aggregation time.
    from datetime import datetime
    now = datetime.now().astimezone()
    generated_at = now.isoformat(timespec="seconds")
    stamp = now.strftime("%Y%m%d_%H%M%S")

    all_graphs = sorted({g for grp in by_group.values() for g, _ in grp})
    all_datasets = sorted({ds for ds, _ in by_group})
    report: List[str] = _render_meta_header(
        metas, all_datasets, all_graphs, out_dir, generated_at
    )
    report += [
        "",
        f"> **Development view.** Aggregated from whatever run dirs are under `{out_dir}` for this "
        "checkout's `GENERATOR_LLM`. Not a sweep deliverable and not to be sent as one: the model "
        "sweep is run, checked for completeness and delivered with `python orchestrate_sweep.py` "
        "(docs/EXPERIMENT_HANDOUT.md).",
    ]

    for dataset, method in sorted(by_group):
        label = f"{dataset} [{method}]"
        pairs = sorted(by_group[(dataset, method)])
        records: List[Dict[str, Any]] = []
        graphs: List[str] = []
        for graph, rp in pairs:
            graphs.append(graph)
            records.extend(eval_paths.drop_retired(dataset, graph, _load_records(rp)))

        if not records:
            report.append(f"\n### {label}")
            report.append(f"\n_(no records loaded; graphs scanned: {graphs})_")
            continue

        by_diff = aggregate_by_difficulty(records)
        report += _render_dataset_table(label, by_diff, graphs,
                                        bucket_order=_BUCKET_ORDER, axis="difficulty")

        # Per-strategy table — only for augmented datasets (records carry a
        # non-null "strategy"). Skipped silently for the base/non-augmented sets.
        by_strategy = aggregate_by_strategy(records)
        if _has_strategy_rows(by_strategy):
            report += _render_dataset_table(label, by_strategy, graphs,
                                            bucket_order=_STRATEGY_ORDER, axis="strategy")

    text = "\n".join(report) + "\n"
    print(text)

    report_path = out_dir / f"report_{stamp}.md"
    report_path.write_text(text, encoding="utf-8")
    print(f"[eval_aggregate] wrote report → {report_path}")
    print("[eval_aggregate] development view only — the model sweep is run and delivered with "
          "`python orchestrate_sweep.py` (docs/EXPERIMENT_HANDOUT.md); do not send this file as a result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
