#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_cb_summary.py
=================
Cross-graph summary for the CypherBench entity-perturbation ablation:
one row per graph, one column per method, for EA and PSJS, plus a
macro-average row. Companion to the per-graph ``docs/ablation_<graph>.md``
files (same metric definitions, recomputed from each method's
``records.jsonl``).

Metric rule (identical to gen_ablation_report.py / each summary.json):
  scored = rows whose ``ea`` is not None; EA = mean(1.0 if ea else 0.0);
  PSJS  = mean(psjs) over rows whose ``psjs`` is not None.

Driven by a JSON spec (argv[1])::

    {
      "title": "...", "out": "docs/ablation_cypherbench_summary.md",
      "generated": "2026-06-21",
      "methods": ["No Val Link","FCAV","ReAct","GraphRAG","CyANCHOR"],
      "graphs": [
        {"label":"flight_accident","n":170,
         "dirs":{"No Val Link":"logs/fl2_no_val_link", ...}},
        ...
      ],
      "findings": ["...", ...]
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load(d: str) -> List[Dict[str, Any]]:
    p = Path(d) / "records.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _ea(rows: List[Dict[str, Any]]) -> Optional[float]:
    s = [r for r in rows if r.get("ea") is not None]
    return sum(1.0 if r["ea"] else 0.0 for r in s) / len(s) if s else None


def _psjs(rows: List[Dict[str, Any]]) -> Optional[float]:
    v = [r["psjs"] for r in rows if r.get("psjs") is not None]
    return sum(v) / len(v) if v else None


def _n_scored(rows: List[Dict[str, Any]]) -> int:
    return sum(1 for r in rows if r.get("ea") is not None)


def _fmt(x: Optional[float]) -> str:
    return f"{x:.3f}" if x is not None else "—"


def _table(headers: List[str], rows: List[List[str]], aligns: List[str]) -> str:
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(3, max(len(str(c)) for c in col)) for col in cols]

    def fmt(cells):
        return "| " + " | ".join(
            (str(c).rjust(w) if a == "r" else str(c).ljust(w))
            for c, w, a in zip(cells, widths, aligns)) + " |"

    sep = ["-" * (w - 1) + ":" if a == "r" else "-" * w for w, a in zip(widths, aligns)]
    return "\n".join([fmt(headers), "| " + " | ".join(sep) + " |"] + [fmt(r) for r in rows])


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    methods: List[str] = spec["methods"]

    # load every (graph, method) → rows; skip graphs with no data yet
    data: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    present = []
    for g in spec["graphs"]:
        gd = {m: _load(g["dirs"].get(m, "")) for m in methods}
        if any(gd[m] for m in methods):
            data[g["label"]] = gd
            present.append(g)

    def metric_table(metric, title: str) -> str:
        rows = []
        # per-graph rows
        col_vals = {m: [] for m in methods}
        for g in present:
            cells = [g["label"]]
            gd = data[g["label"]]
            # n = max scored across methods (per-method n can differ slightly on errors)
            ncol = max((_n_scored(gd[m]) for m in methods), default=0)
            cells.append(str(ncol))
            for m in methods:
                v = metric(gd[m])
                cells.append(_fmt(v))
                if v is not None:
                    col_vals[m].append(v)
            rows.append(cells)
        # macro-average row (unweighted mean across graphs)
        avg = ["**macro-avg**", ""]
        for m in methods:
            vs = col_vals[m]
            avg.append(f"**{sum(vs)/len(vs):.3f}**" if vs else "—")
        rows.append(avg)
        headers = ["graph", "n"] + methods
        aligns = ["l", "r"] + ["r"] * len(methods)
        return f"## {title}\n\n" + _table(headers, rows, aligns)

    parts: List[str] = []
    parts.append(f"# {spec['title']}\n")
    parts.append(
        "**Cross-graph summary** of the entity-perturbation ablation over the CypherBench\n"
        "graphs. EA = execution accuracy, PSJS = Provenance-Subgraph Jaccard Similarity\n"
        "(both over each method's successfully-executed rows). Full graph per column "
        f"(`n` = scored examples). All methods share the identical Cypher system prompt. "
        f"Generated {spec.get('generated','')}.\n")
    parts.append(
        "Per-graph breakdowns (by perturbation strategy + difficulty) live in the "
        "individual `docs/ablation_<graph>.md` files.\n")
    parts.append("---\n")
    parts.append(metric_table(_ea, "Execution Accuracy (EA)") + "\n")
    parts.append(metric_table(_psjs, "Provenance-Subgraph Jaccard Similarity (PSJS)") + "\n")
    if spec.get("findings"):
        parts.append("---\n")
        parts.append("## Findings\n")
        parts.append("\n".join(f"{i+1}. {f}" for i, f in enumerate(spec["findings"])) + "\n")

    out = Path(spec["out"])
    out.write_text("\n".join(parts))
    print(f"wrote {out}  ({len(present)}/{len(spec['graphs'])} graphs present)")
    print("\n" + metric_table(_ea, "Execution Accuracy (EA)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
