#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_ablation_report.py
======================
Render an entity-perturbation ablation report (the
``docs/ablation_*.md`` format) from a set of per-method eval log dirs.

Each method's ``records.jsonl`` is the source of truth; metrics are
recomputed the same way the worker's ``summary.json`` does it
(verified to reproduce it exactly):

* scored rows  = records whose ``ea`` is not ``None`` (executed OK)
* EA           = mean(1.0 if ea else 0.0) over scored
* PSJS         = mean(psjs) over rows whose ``psjs`` is not ``None``
* n            = #scored,  err = #(ea is None)  (execution errors)

Buckets (perturbation ``strategy`` / ``difficulty``) are discovered
from the data; known buckets are emitted in canonical order, any extra
values are appended so nothing is silently dropped.

Driven by a JSON spec (path as argv[1])::

    {
      "title":   "Ablation — movie (entity-perturbed CypherBench)",
      "out":     "docs/ablation_movie.md",
      "graph":   "movie",
      "dataset": "CypherBench",
      "n_questions": 200,
      "generated": "2026-06-21",
      "llm": "gpt-4.1",
      "strategies_note": "casing · typo · partial · abbrev · alias",
      "methods": [
        {"label": "No Val Link", "retrieval": "—", "dir": "logs/mv2_no_val_link"},
        ...
      ],
      "findings": ["...", "..."]      // optional; omitted -> auto summary line
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_STRAT_ORDER = ["casing", "typo", "partial", "abbrev", "alias"]
_DIFF_ORDER = ["easy", "medium", "hard"]


def _load(d: str) -> List[Dict[str, Any]]:
    p = Path(d) / "records.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _ea(rows: List[Dict[str, Any]]) -> Optional[float]:
    s = [r for r in rows if r.get("ea") is not None]
    if not s:
        return None
    return sum(1.0 if r["ea"] else 0.0 for r in s) / len(s)


def _psjs(rows: List[Dict[str, Any]]) -> Optional[float]:
    v = [r["psjs"] for r in rows if r.get("psjs") is not None]
    if not v:
        return None
    return sum(v) / len(v)


def _order(values: set, known: List[str]) -> List[str]:
    out = [k for k in known if k in values]
    out += sorted(v for v in values if v not in known and v is not None)
    return out


def _fmt(x: Optional[float]) -> str:
    return f"{x:.3f}" if x is not None else "—"


def _table(headers: List[str], rows: List[List[str]], aligns: List[str]) -> str:
    """Render a GitHub markdown table with padded, aligned columns."""
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    # the separator marker (:---, ---:, etc.) must also fit the width
    widths = [max(w, 3) for w in widths]

    def fmt_row(cells: List[str]) -> str:
        out = []
        for cell, w, a in zip(cells, widths, aligns):
            out.append(str(cell).rjust(w) if a == "r" else str(cell).ljust(w))
        return "| " + " | ".join(out) + " |"

    sep = []
    for w, a in zip(widths, aligns):
        sep.append(("-" * (w - 1) + ":") if a == "r" else ("-" * w))
    lines = [fmt_row(headers), "| " + " | ".join(sep) + " |"]
    lines += [fmt_row(r) for r in rows]
    return "\n".join(lines)


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    methods = spec["methods"]

    data = {m["label"]: _load(m["dir"]) for m in methods}

    # discover buckets across all methods
    strat_vals: set = set()
    diff_vals: set = set()
    for rows in data.values():
        strat_vals |= {r.get("strategy") for r in rows if r.get("strategy")}
        diff_vals |= {r.get("difficulty") for r in rows if r.get("difficulty")}
    strategies = _order(strat_vals, _STRAT_ORDER)
    difficulties = _order(diff_vals, _DIFF_ORDER)

    # ── Overall ──────────────────────────────────────────────────────────────
    overall_rows = []
    for m in methods:
        rows = data[m["label"]]
        scored = [r for r in rows if r.get("ea") is not None]
        err = sum(1 for r in rows if r.get("ea") is None)
        overall_rows.append([
            m["label"], m["retrieval"],
            _fmt(_ea(rows)), _fmt(_psjs(rows)),
            str(len(scored)), str(err),
        ])
    overall = _table(
        ["method", "retrieval", "EA", "PSJS", "n", "err"],
        overall_rows, ["l", "l", "r", "r", "r", "r"])

    # ── By strategy — EA ─────────────────────────────────────────────────────
    def bucket_table(field: str, buckets: List[str], metric) -> str:
        rows = []
        for m in methods:
            rs = data[m["label"]]
            cells = [m["label"]]
            for b in buckets:
                cells.append(_fmt(metric([r for r in rs if r.get(field) == b])))
            rows.append(cells)
        return _table(["method"] + buckets, rows, ["l"] + ["r"] * len(buckets))

    by_strat_ea = bucket_table("strategy", strategies, _ea)
    by_diff_ea = bucket_table("difficulty", difficulties, _ea)
    by_strat_psjs = bucket_table("strategy", strategies, _psjs)

    # ── header / prose ───────────────────────────────────────────────────────
    n_q = spec.get("n_questions")
    g = spec["graph"]
    ds = spec.get("dataset", "CypherBench")
    gen = spec.get("generated", "")
    llm = spec.get("llm", "gpt-4.1")
    snote = spec.get("strategies_note", " · ".join(strategies))

    parts: List[str] = []
    parts.append(f"# {spec['title']}\n")
    parts.append(
        "**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).\n"
        "PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).\n"
        f"Higher is better; both over each method's successfully-executed rows. Generated {gen}.\n")
    parts.append(
        f"**Setup.** {ds} `{g}`, {n_q} entity-perturbed test questions\n"
        f"(strategies: {snote}). LLMs: {llm} for grounding and Cypher generation.\n")
    parts.append(
        "**Methods.**\n"
        "- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).\n"
        "- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve\n"
        "  candidate values from a self-built value index, an LLM generates the entity JSON.\n"
        "- **ReAct (Node + Rel)** — ReAct NER agent (fuzzy/BM25 retrieval) over node + relation tools.\n"
        "- **GraphRAG** — Multi-Agent GraphRAG baseline: generate→execute→evaluate→repair; on\n"
        "  error/empty it extracts the query's labels/values/rels, validates them, and proposes\n"
        "  normalized-Levenshtein replacements, iterating the generator.\n"
        "- **CyANCHOR (Node + Rel)** — our plan-and-execute grounder: decompose the question into\n"
        "  entity mentions, route each to a database field, retrieve candidates with an LLM-judge\n"
        "  corrective loop, then the Cypher LLM value-links. Retrieval is the union of independently\n"
        "  toggleable arms — **fuzzy** (BM25) · **lev** (APOC normalized Levenshtein) · **vector**\n"
        "  (in-graph embeddings).\n")
    parts.append("---\n")
    parts.append("## Overall\n\n" + overall + "\n")
    parts.append("## By perturbation strategy — EA\n\n" + by_strat_ea + "\n")
    parts.append("## By query-difficulty — EA\n\n" + by_diff_ea + "\n")
    parts.append("## By perturbation strategy — PSJS\n\n" + by_strat_psjs + "\n")

    if spec.get("findings"):
        parts.append("---\n")
        parts.append("## Findings\n")
        parts.append("\n".join(f"{i+1}. {f}" for i, f in enumerate(spec["findings"])) + "\n")

    out = Path(spec["out"])
    out.write_text("\n".join(parts))
    print(f"wrote {out}  ({sum(len(v) for v in data.values())} records across {len(methods)} methods)")
    # echo the overall table to stdout for a quick sanity glance
    print("\n" + overall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
