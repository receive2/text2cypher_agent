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

* denominator  = ALL examples (no exclusions; the harness assumes nothing about
  dataset quality — a query that doesn't run is a wrong answer)
* EA           = mean(1.0 if ea is True else 0.0) over all rows
* PSJS         = mean(psjs or 0.0) over all rows
* n            = #examples (the denominator);  all errors score 0, none excluded
* err          = method failures (bad generated Cypher / timeout)
* gold err     = examples whose GOLD query does not execute (dataset defect,
                 scores 0 for every method; per-method count is a lower bound)

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
from typing import Any, Dict, List, Optional, Tuple

_STRAT_ORDER = ["casing", "typo", "partial", "abbrev", "alias"]
_DIFF_ORDER = ["easy", "medium", "hard"]


def _load(d: str) -> List[Dict[str, Any]]:
    p = Path(d) / "records.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def _load_run_meta(d: str) -> Dict[str, Any]:
    """Read the ``run_meta`` block from a method dir's sibling ``summary.json``
    (the harness captures the resolved config + a real timestamp there). Returns
    ``{}`` if absent, so the report degrades gracefully to spec values."""
    p = Path(d) / "summary.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        rm = data.get("run_meta")
        return rm if isinstance(rm, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _onoff(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "on" if v else "off"
    return str(v)


def _ea(rows: List[Dict[str, Any]]) -> Optional[float]:
    """EA over ALL rows: True→1, everything else (False / error / None)→0. No
    exclusions — a query that doesn't run is a wrong answer. Curating broken golds
    is a dataset-audit job, not an eval one (see audit_gold_errors.py)."""
    if not rows:
        return None
    return sum(1.0 if r.get("ea") is True else 0.0 for r in rows) / len(rows)


def _psjs(rows: List[Dict[str, Any]]) -> Optional[float]:
    """PSJS over ALL rows: a numeric psjs counts, anything else (error/None)→0."""
    if not rows:
        return None
    return sum(float(r["psjs"]) if isinstance(r.get("psjs"), (int, float))
               and not isinstance(r.get("psjs"), bool) else 0.0
               for r in rows) / len(rows)


def _err_is_gold(r: Dict[str, Any]) -> bool:
    """True when the example failed because the **gold** query does not execute.

    A broken gold is a dataset defect, not a method failure: no prediction can
    match a gold that errors, so every method scores 0 on that row. It is only
    *observed* once a method emits runnable Cypher and the harness reaches gold
    execution — a method that fails earlier masks it behind its own error, which
    is why weaker methods report fewer gold failures, not fewer broken golds."""
    return str(r.get("error") or "").startswith("gold:")


def _errs(rows: List[Dict[str, Any]]) -> Tuple[int, int]:
    """(method failures, gold-side failures) among errored rows."""
    errored = [r for r in rows if r.get("ea") is None]
    gold = sum(1 for r in errored if _err_is_gold(r))
    return len(errored) - gold, gold


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
    # run_meta (resolved config + real timestamp) captured by the harness in each
    # method dir's summary.json — used to make the report self-describing.
    metas = {m["label"]: _load_run_meta(m["dir"]) for m in methods}

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
        m_err, g_err = _errs(rows)     # both scored 0, NOT excluded
        overall_rows.append([
            m["label"], m["retrieval"],
            _fmt(_ea(rows)), _fmt(_psjs(rows)),
            str(len(rows)), str(m_err), str(g_err),
        ])
    overall = _table(
        ["method", "retrieval", "EA", "PSJS", "n", "err", "gold err"],
        overall_rows, ["l", "l", "r", "r", "r", "r", "r"])
    _g_max = max((int(r[-1]) for r in overall_rows), default=0)
    if _g_max:
        overall += (
            f"\n\n> `err` = examples the **method** failed on (unrunnable "
            f"generated Cypher, timeouts). `gold err` = examples whose **gold "
            f"query itself** does not execute — a dataset defect that scores 0 "
            f"for every method, not a property of the method. Both are scored 0 "
            f"and kept in the denominator. At least {_g_max} of the "
            f"{len(overall_rows) and len(data[methods[0]['label']])} examples "
            f"have a broken gold; a method that fails earlier masks some of "
            f"them behind its own error, so the per-method count is a lower "
            f"bound.\n")

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
    by_diff_psjs = bucket_table("difficulty", difficulties, _psjs)

    # ── header / prose ───────────────────────────────────────────────────────
    n_q = spec.get("n_questions")
    g = spec["graph"]
    ds = spec.get("dataset", "CypherBench")
    gen = spec.get("generated", "")
    llm = spec.get("llm", "gpt-4.1")
    snote = spec.get("strategies_note", " · ".join(strategies))

    # Resolve real provenance from the harness-captured run_meta; fall back to the
    # spec when summary.json is missing (older runs / hand-built specs).
    _meta_list = [m for m in metas.values() if m]

    def _first_meta(key: str):
        for m in _meta_list:
            v = m.get(key)
            if v not in (None, ""):
                return v
        return None

    _ts_all = sorted({str(m["generated_at"]) for m in _meta_list if m.get("generated_at")})
    ts = _ts_all[-1] if _ts_all else (gen or "(unrecorded)")   # latest run time
    ner_llm = _first_meta("ner_llm") or llm
    cyp_llm = _first_meta("cypher_llm") or llm
    qa_llm  = _first_meta("qa_llm") or llm
    cy_meta = next((m for m in _meta_list if m.get("method") == "cyanchor"), {})

    cy_bits: List[str] = []
    if cy_meta:
        if cy_meta.get("retrieval"):
            cy_bits.append(f"retrieval `{cy_meta['retrieval']}`")
        if cy_meta.get("tool_type"):
            cy_bits.append(f"tool `{cy_meta['tool_type']}`")
        _esc = _onoff(cy_meta.get("plan_exec_escalate"))
        if _esc:
            mi = cy_meta.get("plan_exec_max_iter")
            cy_bits.append(f"escalate `{_esc}`" + (f" (≤{mi})" if _esc == "on" and mi else ""))
        _sr = _onoff(cy_meta.get("cypher_semantic_repair"))
        if _sr:
            rr = cy_meta.get("cypher_repair_max_rounds")
            cy_bits.append(f"semantic_repair `{_sr}`" + (f" (≤{rr})" if _sr == "on" and rr else ""))
        _eiw = _onoff(cy_meta.get("cypher_empty_is_wrong"))
        if _eiw:
            cy_bits.append(f"empty_is_wrong `{_eiw}`")
        _vs = _onoff(cy_meta.get("plan_exec_value_snap"))
        if _vs:
            cy_bits.append(f"value_snap `{_vs}`")

    parts: List[str] = []
    parts.append(f"# {spec['title']}\n")
    parts.append(
        "**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).\n"
        "PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).\n"
        "Higher is better. Denominator = ALL examples; any failure (agent error, "
        "empty/wrong result, or a non-executing gold) scores 0.\n")
    parts.append(
        f"**Setup.** {ds} `{g}`, {n_q} entity-perturbed test questions\n"
        f"(strategies: {snote}).\n")
    parts.append(
        f"**Run config.** Generated {ts}. "
        f"LLMs: NER `{ner_llm}` · Cypher `{cyp_llm}` · QA `{qa_llm}`.\n"
        + ("CyANCHOR knobs: " + " · ".join(cy_bits) + ".\n" if cy_bits else ""))
    parts.append(
        "**Methods.**\n"
        "- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).\n"
        "- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve\n"
        "  candidate values from a self-built value index, an LLM generates the entity JSON.\n"
        "- **ReAct** — ReAct NER agent (fuzzy/BM25 retrieval) over node + relation tools.\n"
        "- **GraphRAG** — Multi-Agent GraphRAG baseline: generate→execute→evaluate→repair; on\n"
        "  error/empty it extracts the query's labels/values/rels, validates them, and proposes\n"
        "  normalized-Levenshtein replacements, iterating the generator.\n"
        "- **CyANCHOR** — our plan-and-execute grounder (node + relation tools): decompose the question into\n"
        "  entity mentions, route each to a database field, retrieve candidates with an LLM-judge\n"
        "  corrective loop, then the Cypher LLM value-links. Retrieval is the union of independently\n"
        "  toggleable arms — **fuzzy** (BM25) · **lev** (APOC normalized Levenshtein) · **vector**\n"
        "  (in-graph embeddings).\n")
    parts.append("---\n")
    parts.append("## Overall\n\n" + overall + "\n")
    parts.append("## By perturbation strategy — EA\n\n" + by_strat_ea + "\n")
    parts.append("## By query-difficulty — EA\n\n" + by_diff_ea + "\n")
    parts.append("## By perturbation strategy — PSJS\n\n" + by_strat_psjs + "\n")
    parts.append("## By query-difficulty — PSJS\n\n" + by_diff_psjs + "\n")

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
