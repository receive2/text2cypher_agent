#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/ner_ablation_report.py
==============================
Assemble a markdown comparison report across NER modes (full / node_only /
no_ner) from per-(dataset,graph) summary.json files written by eval_run.py
into mode-specific OUT_DIRs.

Reads the summaries directly (no re-run), aligns by (dataset, graph), and
emits a markdown doc with:
  * per-graph EA / PSJS by NER mode + Δ vs no_ner baseline
  * by-difficulty breakdown per graph
  * pooled (micro-averaged over all rows) summary

EM is intentionally omitted from the report (structurally 0 on CypherBench —
gold is template-generated, predictions are semantically-equivalent variants).

Usage
-----
    python -m scripts.ner_ablation_report \
        --mode full=logs/eval_p2_full \
        --mode node_only=logs/eval_p2_node_only \
        --mode no_ner=logs/eval_p2_no_ner \
        --baseline no_ner \
        --title "P2 — NER ablation on CypherBench (geography, politics)" \
        --out docs/NER_ABLATION_P2.md
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

_BUCKETS = ("easy", "medium", "hard")


def _load_mode(out_dir: str) -> Dict[Tuple[str, str], dict]:
    """(dataset, graph) -> summary dict, for every summary.json in out_dir."""
    out: Dict[Tuple[str, str], dict] = {}
    for path in sorted(glob.glob(os.path.join(out_dir, "*.summary.json"))):
        base = os.path.basename(path)[: -len(".summary.json")]
        if "__" not in base:
            continue
        dataset, graph = base.split("__", 1)
        out[(dataset, graph)] = json.loads(open(path).read())
    return out


def _fmt(v: Optional[float]) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "—"


def _pct(v: Optional[float]) -> str:
    return f"{100*v:.1f}%" if isinstance(v, (int, float)) else "—"


def _delta(a: Optional[float], b: Optional[float]) -> str:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        d = a - b
        return f"{d:+.3f}"
    return "—"


def _micro_avg(summaries: List[dict], metric: str) -> Optional[float]:
    """Row-weighted mean of a metric over a list of summaries (using n_scored)."""
    num = 0.0
    den = 0
    for s in summaries:
        v = s.get(metric)
        ns = s.get("n_scored", {}).get(metric, 0)
        if isinstance(v, (int, float)) and ns:
            num += v * ns
            den += ns
    return (num / den) if den else None


def _micro_avg_bucket(summaries: List[dict], bucket: str, metric: str) -> Optional[float]:
    num = 0.0
    den = 0
    for s in summaries:
        cell = s.get("by_difficulty", {}).get(bucket, {})
        v = cell.get(metric)
        ns = cell.get("n_scored", {}).get(metric, 0)
        if isinstance(v, (int, float)) and ns:
            num += v * ns
            den += ns
    return (num / den) if den else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", action="append", required=True,
                    help="mode=out_dir, e.g. full=logs/eval_p2_full")
    ap.add_argument("--baseline", default="no_ner",
                    help="mode name to use as Δ baseline (default no_ner).")
    ap.add_argument("--title", default="NER ablation report")
    ap.add_argument("--out", default=None, help="write markdown here (else stdout)")
    args = ap.parse_args()

    modes: Dict[str, str] = {}
    for spec in args.mode:
        name, _, d = spec.partition("=")
        modes[name] = d
    mode_names = list(modes.keys())
    base = args.baseline

    # Load all modes.
    loaded = {m: _load_mode(d) for m, d in modes.items()}

    # All (dataset, graph) pairs present in any mode.
    pairs = sorted({p for m in loaded.values() for p in m.keys()})

    L: List[str] = []
    L.append(f"# {args.title}")
    L.append("")
    L.append("> Metric key: **EA** = execution accuracy (predicted Cypher's result "
             "set matches gold's). **PSJS** = Provenance-Subgraph Jaccard "
             "Similarity (partial-credit overlap of the retrieved subgraph). "
             "Higher is better for both. EM omitted (structurally ~0 on "
             "CypherBench: gold is template-generated, predictions are "
             "semantically-equivalent string variants).")
    L.append("")
    L.append(f"**NER modes compared:** {', '.join(f'`{m}`' for m in mode_names)} "
             f"(Δ columns are vs `{base}` baseline).")
    L.append("")
    L.append("- `full` — NER ReAct agent with node + relation tools; resolves "
             "each question entity to its canonical DB value via fulltext search.")
    L.append("- `node_only` — NER agent with node-property tools only "
             "(relation tools ablated).")
    L.append(f"- `no_ner` — NER bypassed entirely; the Cypher LLM sees only "
             "schema + question (perturbed entity surface forms are copied "
             "verbatim into the query).")
    L.append("")

    # ── Per-graph headline ────────────────────────────────────────────────────
    L.append("## Per-graph results")
    L.append("")
    for (ds, graph) in pairs:
        present = [m for m in mode_names if (ds, graph) in loaded[m]]
        if not present:
            continue
        any_s = loaded[present[0]][(ds, graph)]
        n = any_s.get("n")
        L.append(f"### {ds} / {graph}  (N={n})")
        L.append("")
        # EA / PSJS table
        header = "| metric | " + " | ".join(f"`{m}`" for m in mode_names)
        if base in modes:
            header += " | " + " | ".join(f"Δ{m} vs {base}" for m in mode_names if m != base)
        header += " |"
        sep = "|" + "---|" * (1 + len(mode_names) + (len(mode_names) - 1 if base in modes else 0))
        L.append(header)
        L.append(sep)
        for metric in ("ea", "psjs"):
            vals = {m: loaded[m].get((ds, graph), {}).get(metric) for m in mode_names}
            row = f"| {metric.upper()} | " + " | ".join(_fmt(vals[m]) for m in mode_names)
            if base in modes:
                row += " | " + " | ".join(_delta(vals[m], vals[base]) for m in mode_names if m != base)
            row += " |"
            L.append(row)
        # errors row
        errs = {m: loaded[m].get((ds, graph), {}).get("n_errors") for m in mode_names}
        L.append(f"| n_errors | " + " | ".join(str(errs[m] if errs[m] is not None else "—") for m in mode_names)
                 + (" |" if base not in modes else " | " + " | ".join("" for m in mode_names if m != base) + " |"))
        L.append("")

        # by-difficulty
        L.append(f"<details><summary>by query-difficulty — {graph}</summary>")
        L.append("")
        L.append("| bucket | n | " + " | ".join(f"EA `{m}`" for m in mode_names)
                 + " | " + " | ".join(f"PSJS `{m}`" for m in mode_names) + " |")
        L.append("|" + "---|" * (2 + 2 * len(mode_names)))
        for b in _BUCKETS:
            ncell = any_s.get("by_difficulty", {}).get(b, {}).get("n", 0)
            if not ncell:
                continue
            ea_cells = [_fmt(loaded[m].get((ds, graph), {}).get("by_difficulty", {}).get(b, {}).get("ea")) for m in mode_names]
            pj_cells = [_fmt(loaded[m].get((ds, graph), {}).get("by_difficulty", {}).get(b, {}).get("psjs")) for m in mode_names]
            L.append(f"| {b} | {ncell} | " + " | ".join(ea_cells) + " | " + " | ".join(pj_cells) + " |")
        L.append("")
        L.append("</details>")
        L.append("")

    # ── Pooled (micro-average over all rows of all graphs) ────────────────────
    L.append("## Pooled (row-weighted across all graphs)")
    L.append("")
    L.append("| metric | " + " | ".join(f"`{m}`" for m in mode_names)
             + (" | " + " | ".join(f"Δ{m} vs {base}" for m in mode_names if m != base) if base in modes else "")
             + " |")
    L.append("|" + "---|" * (1 + len(mode_names) + (len(mode_names) - 1 if base in modes else 0)))
    pooled = {m: list(loaded[m].values()) for m in mode_names}
    for metric in ("ea", "psjs"):
        vals = {m: _micro_avg(pooled[m], metric) for m in mode_names}
        row = f"| {metric.upper()} | " + " | ".join(_fmt(vals[m]) for m in mode_names)
        if base in modes:
            row += " | " + " | ".join(_delta(vals[m], vals[base]) for m in mode_names if m != base)
        row += " |"
        L.append(row)
    L.append("")
    L.append("### Pooled by query-difficulty")
    L.append("")
    L.append("| bucket | " + " | ".join(f"EA `{m}`" for m in mode_names)
             + " | " + " | ".join(f"PSJS `{m}`" for m in mode_names) + " |")
    L.append("|" + "---|" * (1 + 2 * len(mode_names)))
    for b in _BUCKETS:
        ea_cells = [_fmt(_micro_avg_bucket(pooled[m], b, "ea")) for m in mode_names]
        pj_cells = [_fmt(_micro_avg_bucket(pooled[m], b, "psjs")) for m in mode_names]
        L.append(f"| {b} | " + " | ".join(ea_cells) + " | " + " | ".join(pj_cells) + " |")
    L.append("")

    text = "\n".join(L) + "\n"
    if args.out:
        open(args.out, "w").write(text)
        print(f"wrote {args.out} ({len(text)} bytes)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
