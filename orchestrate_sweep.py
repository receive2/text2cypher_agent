#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orchestrate_sweep.py
====================
Run ONE generator model over the full perturbed-benchmark suite — 13 graphs x
5 methods — refresh the report tables, and publish the result as a branch.
One person, one model, one command.

    python orchestrate_sweep.py --smoke              # 5 methods x flight_accident x 3 questions -> logs/smoke/
    python orchestrate_sweep.py                      # the full suite; re-run the same command to resume
    python orchestrate_sweep.py --graphs movie nba   # only these graphs (all five methods)
    python orchestrate_sweep.py --methods react      # only this method (all graphs)
    python orchestrate_sweep.py --skip-methods react # this model does not run react: excluded from the run AND the verdict
    python orchestrate_sweep.py --status             # completeness matrix + headline numbers, no runs
    python orchestrate_sweep.py --publish            # branch sweep/<model>: run dirs + reports, commit, push
    python orchestrate_sweep.py --publish --allow-incomplete   # push a PARTIAL branch (missing/⚠ cells listed)

The model is ``eval_config.GENERATOR_LLM`` — the one line a participant edits.
Graphs are ``eval_config.FULL_EVAL_PAIRS_13_AUGMENTED``; methods are the five
below, in this order. The driver runs graph by graph (the live artifact tree is
swapped once per graph) and, per graph, the five methods in turn.

Completeness
------------
A cell (graph, method) is COMPLETE when the newest run for this model holds one
record per question of that graph (``records.jsonl`` rows == question count in
the benchmark file). Errored questions are allowed: the eval scores them 0
(denominator = all questions) and reports them in the ``err`` column.

Errors are not all alike, so every errored record is classified by its
``error`` string:

* ``gold``  — the benchmark's own gold Cypher failed (a data defect; identical
  for every method and model; never fixable by re-running);
* ``agent`` — the model's generated Cypher failed (the model's result; scores 0);
* ``infra`` — timeout / API timeout / rate limit / connection failure: the
  question was never really evaluated. These are the only errors a re-run can
  recover, and a cell with more than a handful of them is marked ⚠ and treated
  as NOT clean: the run loop re-runs it (at most SUSPECT_RERUN_MAX times) and
  ``--publish`` refuses it unless ``--allow-incomplete``;
* ``other`` — unclassified; flagged only when lopsided against the other
  methods on the same graph.

The matrix shows ✓ (clean), ✗ (missing/truncated) or ⚠ (infrastructure
failures), and a "Flagged cells" section prints the breakdown, the most common
error text and the exact command to re-run just that cell.

Resume
------
Completion is read from disk, so re-running the same command skips every
clean cell and re-runs the rest (up to MAX_TRIES attempts each). A cell that
keeps failing is reported, not retried forever; the run continues with the next
cell. A missing or truncated cell is always re-run. A complete-but-⚠ cell is
re-run at most SUSPECT_RERUN_MAX times across invocations, then reported as
persistent — unless you select it explicitly with ``--graphs`` / ``--methods``,
which re-runs it regardless and does not count against the budget.
``logs/sweep_<model>.json`` keeps the per-cell history. Resume granularity is
the cell: eval_run has no per-question resume, so an interrupted cell is re-run
in full (a fresh time-stamped directory). Re-runs write a new time-stamped directory; the newest one wins, so
nothing has to be deleted by hand.

Publish
-------
``--publish`` never touches your branch or working tree. It builds the commit
in a throw-away git worktree based on ``origin/sweep/<model>`` (or on HEAD the
first time), mirrors the current run dirs + ``report/<model>/`` +
``eval_config.py`` into it, commits, and pushes — so a second publish after a
``git pull`` fast-forwards instead of being rejected, and switching branches
afterwards cannot delete your run dirs. It ends by printing the three lines to
send to the coordinator (model, branch, report URL).

Reports
-------
After each graph, ``report/<Dataset>/<graph>.md`` is regenerated from the five
run dirs (``gen_ablation_report.py``); after each dataset, its pooled
``_summary.md`` (``gen_pooled_report.py``). Pooling is over all questions
(each question weighs one; an errored question scores 0) — the same arithmetic
as the committed gpt-4.1 tables. Everything a model produces lives under
``report/<model>/``: ``<Dataset>/<graph>.md``, ``<Dataset>/_summary.md`` and —
written at the end of every driver invocation, never overwritten —
``SWEEP_<YYYYMMDD-HHMMSS>.md``: the completeness matrix plus every table the
paper needs (per dataset and overall; by perturbation strategy; by query
difficulty), with ``SWEEP.md`` a copy of the latest one.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

# .env holds API keys only (never a model choice). The eval workers load it
# themselves; the driver needs it too because it builds a graph's FCAV index
# in-process (OpenAI embeddings) before running the fcav method.
load_dotenv(REPO / ".env")

import eval_config as cfg   # noqa: E402
import eval_paths           # noqa: E402

# (label, retrieval, METHOD value) in the order the reports list them.
METHODS: List[Tuple[str, str, str]] = [
    ("No Val Link", "—",         "no_val_link"),
    ("FCAV",        "vector",    "fcav"),
    ("ReAct",       "fuzzy",     "react"),
    ("GraphRAG",    "norm-Lev",  "graphrag"),
    ("CyANCHOR",    "fuzzy+lev", "cyanchor"),
]
# dataset key -> (report folder, label)
DATASET_INFO = {
    "cypherbench_augmented":  ("CypherBench",  "CypherBench"),
    "mindthequery_augmented": ("MindTheQuery", "MindTheQuery"),
    "zograscope_augmented":   ("ZOGRASCOPE",   "ZOGRASCOPE"),
}
SMOKE_PAIR = ("cypherbench_augmented", "flight_accident")
SMOKE_LIMIT = 3
SMOKE_OUT = "logs/smoke"
MAX_TRIES = 3
CYANCHOR_PER_EXAMPLE_TIMEOUT = "900"   # seconds; slowest legitimate examples take 70-120 s

# ⚠ detection — see "Completeness" in the module docstring.
SUSPECT_INFRA_MIN_ABS   = 10     # this many infra errors in a cell always flags it
SUSPECT_INFRA_RATE      = 0.02   # ... or this share of the cell's questions,
SUSPECT_INFRA_MIN_RATE  = 3      #     provided at least this many (small graphs)
SUSPECT_OTHER_RATE      = 0.25   # unclassified errors: flag when lopsided vs the
SUSPECT_OTHER_REF_RATE  = 0.05   #     other methods on the same graph (min ≤ this)
SUSPECT_OTHER_ABS_RATE  = 0.50   #     ... or when more than half the cell errored
SUSPECT_RERUN_MAX       = 2      # automatic re-runs of a ⚠ cell across invocations

# A Cypher / Neo4j *statement* error is the query's fault (gold or agent) and
# never infrastructure — even when its message contains a number that looks
# like an HTTP status ("line 1, column 536"). Checked before the infra patterns.
_CYPHER_ERROR = re.compile(r"Cypher\w*Error|Neo\.ClientError\.", re.IGNORECASE)
_INFRA_PATTERNS = re.compile(
    r"example timeout|APITimeoutError|transaction timeout|timed out|"
    r"(?:Read|Write|Connect)?TimeoutError|(?:Read|Write|Connect)Timeout|"
    r"RateLimit|rate limit|\b429\b|(?:error code|status(?: code)?|http)\W{0,3}5\d\d\b|"
    r"ServiceUnavailable|InternalServerError|APIConnectionError|"
    r"Connection(?:Error|Reset|Refused)|overloaded|watchdog",
    re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
# Model / suite
# ──────────────────────────────────────────────────────────────────────────────

def model_name() -> str:
    """The preset named in eval_config.GENERATOR_LLM (fails early on a typo)."""
    import config
    name = str(getattr(cfg, "GENERATOR_LLM", "") or "").strip()
    config.resolve_preset(name)   # raises KeyError with the valid list
    return name


def suite_pairs() -> List[Tuple[str, str]]:
    return [tuple(p) for p in cfg.FULL_EVAL_PAIRS_13_AUGMENTED]


def expected_counts() -> Dict[Tuple[str, str], int]:
    """(dataset, graph) -> number of questions in the shipped benchmark file."""
    import eval_run
    counts: Dict[Tuple[str, str], int] = collections.Counter()
    for dataset in DATASET_INFO:
        rows = json.load(open(eval_run._resolve_test_path(dataset), encoding="utf-8"))
        for r in rows:
            counts[(dataset, r["graph"])] += 1
    return dict(counts)


def method_seg(method: str) -> str:
    """Run-dir method segment without the model suffix (cyanchor -> cyanchor_fl)."""
    return eval_paths.method_tag(method)


# ──────────────────────────────────────────────────────────────────────────────
# Run dirs / records / metrics
# ──────────────────────────────────────────────────────────────────────────────

def newest_run_dir(dataset: str, graph: str, method: str, out_dir: str, model: str) -> Optional[Path]:
    """Newest run dir for (pair, method) and this model under *out_dir*."""
    if out_dir == eval_paths.RUNS_ROOT:
        d = eval_paths.latest_run_dir(dataset, graph, method_seg(method))
    else:
        pattern = f"{dataset}__{graph}__{method_seg(method)}@{eval_paths.model_seg(model)}__*"
        hits = sorted(glob.glob(str(REPO / out_dir / pattern)))
        d = Path(hits[-1]) if hits else None
    if d is None:
        return None
    d = Path(d)
    return d if d.is_absolute() else REPO / d   # eval_paths returns repo-relative paths


def read_records(run_dir: Optional[Path]) -> List[dict]:
    if run_dir is None:
        return []
    f = Path(run_dir) / "records.jsonl"
    if not f.is_file():
        return []
    with f.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def ea(records: List[dict]) -> Optional[float]:
    """EA over ALL rows: True -> 1, everything else (False / error / None) -> 0."""
    return (sum(1.0 for r in records if r.get("ea") is True) / len(records)) if records else None


def psjs(records: List[dict]) -> Optional[float]:
    """PSJS over ALL rows: a numeric psjs counts, anything else (error / None) -> 0."""
    if not records:
        return None
    return sum(float(r["psjs"]) if isinstance(r.get("psjs"), (int, float)) else 0.0 for r in records) / len(records)


def n_err(records: List[dict]) -> int:
    return sum(1 for r in records if r.get("ea") is None)


def classify_error(error: Optional[str]) -> str:
    """'infra' | 'gold' | 'agent' | 'other' — see the module docstring.
    A Cypher/Neo4j statement error is classified by its prefix and is never
    infra; otherwise infra patterns win over the prefix ('agent: APITimeoutError'
    is infra)."""
    e = str(error or "")
    if _CYPHER_ERROR.search(e):
        return "gold" if e.startswith("gold") else "agent"
    if _INFRA_PATTERNS.search(e):
        return "infra"
    if e.startswith("gold"):
        return "gold"
    if e.startswith("agent"):
        return "agent"
    return "other"


def error_breakdown(records: List[dict]) -> dict:
    """Counts per error class plus the most common error text (digits masked)."""
    kinds = collections.Counter()
    texts = collections.Counter()
    for r in records:
        if r.get("ea") is not None:
            continue
        kinds[classify_error(r.get("error"))] += 1
        texts[re.sub(r"\d+", "N", str(r.get("error") or ""))[:160]] += 1
    top = texts.most_common(1)[0][0] if texts else ""
    return {"infra": kinds["infra"], "gold": kinds["gold"], "agent": kinds["agent"],
            "other": kinds["other"], "top_error": top}


def infra_suspect(bd: dict, n: int) -> bool:
    """A cell whose infrastructure failures exceed the small allowance."""
    k = bd["infra"]
    return k >= SUSPECT_INFRA_MIN_ABS or (k >= SUSPECT_INFRA_MIN_RATE and n and k / n >= SUSPECT_INFRA_RATE)


def cell_status(dataset: str, graph: str, method: str, expected: int, out_dir: str, model: str) -> dict:
    d = newest_run_dir(dataset, graph, method, out_dir, model)
    recs = read_records(d)
    bd = error_breakdown(recs)
    return {"dir": str(d.relative_to(REPO)) if d else None, "n": len(recs), "err": n_err(recs),
            "expected": expected, "complete": bool(recs) and len(recs) == expected, "records": recs,
            "breakdown": bd, "suspect": False, "why": ""}


# ──────────────────────────────────────────────────────────────────────────────
# Status report
# ──────────────────────────────────────────────────────────────────────────────

def _fmt(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.3f}"


def report_root(model: str) -> Path:
    """report/<model>/ — one folder per generator model."""
    return REPO / cfg.REPORT_DIR / model


try:  # canonical bucket order, shared with the per-graph tables
    from gen_ablation_report import _STRAT_ORDER, _DIFF_ORDER, _order as _bucket_order  # noqa: E402
except Exception:  # pragma: no cover
    _STRAT_ORDER, _DIFF_ORDER = [], []

    def _bucket_order(values, known):  # type: ignore[misc]
        return sorted(values)


def _breakdown(recs_by_method: Dict[str, List[dict]], field: str, known: List[str],
               metric, labels: Dict[str, str], methods: List[str]) -> str:
    """Markdown table: rows = methods, columns = buckets of *field* (+ all)."""
    values = {str(r.get(field) or "?") for recs in recs_by_method.values() for r in recs}
    buckets = list(_bucket_order(values, known))
    head = "| method | " + " | ".join(buckets) + " | all |\n|---|" + "---:|" * (len(buckets) + 1)
    rows = []
    for m in methods:
        recs = recs_by_method.get(m, [])
        cells = [_fmt(metric([r for r in recs if str(r.get(field) or "?") == b])) for b in buckets]
        rows.append("| " + labels[m] + " | " + " | ".join(cells) + f" | {_fmt(metric(recs))} |")
    counts = "| n | " + " | ".join(str(sum(1 for r in recs_by_method.get(methods[0], []) if str(r.get(field) or "?") == b))
                                   for b in buckets) + f" | {len(recs_by_method.get(methods[0], []))} |"
    return "\n".join([head, *rows, counts])


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPO, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return "?"


def _artifact_set_id() -> str:
    try:
        return json.load(open(REPO / "setup_artifacts" / "MANIFEST.json", encoding="utf-8")).get("set_id", "?")
    except Exception:  # noqa: BLE001
        return "?"


def _benchmarks_version() -> str:
    try:
        import re
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', (REPO / "benchmarks" / "verify.py").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else "?"
    except Exception:  # noqa: BLE001
        return "?"


def build_status(pairs: List[Tuple[str, str]], methods: List[str], expected: Dict[Tuple[str, str], int],
                 out_dir: str, model: str) -> dict:
    cells = {(ds, g, m): cell_status(ds, g, m, expected.get((ds, g), 0), out_dir, model)
             for ds, g in pairs for m in methods}
    flag_suspects(cells)
    complete = all(c["complete"] and not c["suspect"] for c in cells.values())
    return {"model": model, "cells": cells, "complete": complete, "pairs": pairs, "methods": methods,
            "missing": [k for k, c in cells.items() if not c["complete"]],
            "flagged": [k for k, c in cells.items() if c["suspect"]]}


def flag_suspects(cells: Dict[Tuple[str, str, str], dict]) -> None:
    """Mark cells whose errors are infrastructure failures rather than results.

    Rule 1 (by error type): more than a small allowance of ``infra`` errors.
    Rule 2 (fallback, unclassified ``other`` errors only): lopsided against the
    other methods on the same graph — this cell errors on ≥ SUSPECT_OTHER_RATE
    while the best other method errors on ≤ SUSPECT_OTHER_REF_RATE — or more
    than half the cell errored. ``gold`` and ``agent`` errors never flag: the
    first is the data, the second is the model's score."""
    by_graph: Dict[Tuple[str, str], List[Tuple[str, dict]]] = collections.defaultdict(list)
    for (ds, g, m), c in cells.items():
        by_graph[(ds, g)].append((m, c))
    for (ds, g), lst in by_graph.items():
        for m, c in lst:
            n, bd = c["n"], c["breakdown"]
            if not n:
                continue
            if infra_suspect(bd, n):
                c["suspect"] = True
                c["why"] = (f"{bd['infra']} of {n} questions failed on infrastructure "
                            f"(timeout / API / rate limit) — never evaluated")
                continue
            other_rate = bd["other"] / n
            if other_rate >= SUSPECT_OTHER_ABS_RATE:
                c["suspect"] = True
                c["why"] = f"{bd['other']} of {n} questions ({100*other_rate:.0f}%) failed with an unclassified error"
                continue
            if other_rate >= SUSPECT_OTHER_RATE:
                refs = [c2["err"] / c2["n"] for m2, c2 in lst if m2 != m and c2["n"] and c2["complete"]]
                if refs and min(refs) <= SUSPECT_OTHER_REF_RATE:
                    c["suspect"] = True
                    c["why"] = (f"{bd['other']} of {n} questions ({100*other_rate:.0f}%) failed with an "
                                f"unclassified error while another method on this graph failed on "
                                f"{100*min(refs):.1f}% — lopsided")


def decide_cell(c: dict, entry: dict, manual: bool) -> Tuple[str, str]:
    """What the run loop does with one cell. Returns ``(action, note)``:

    * ``skip``       — complete and clean;
    * ``run``        — missing or truncated: always re-run; the ⚠ budget never
                       applies (a killed re-run leaves a truncated dir and must
                       not be parked);
    * ``rerun``      — complete but ⚠: re-run while the automatic budget lasts,
                       or always when the user selected this cell explicitly
                       (``--graphs`` / ``--methods``), which does not consume it;
    * ``persistent`` — complete but ⚠ and the automatic budget is spent."""
    if not c["complete"]:
        return "run", "missing or truncated"
    if not c["suspect"]:
        return "skip", ""
    done = int(entry.get("suspect_reruns", 0))
    if manual:
        return "rerun", f"re-running on request (--graphs/--methods); automatic re-runs so far: {done}"
    if done >= SUSPECT_RERUN_MAX:
        return "persistent", (f"already re-run {done}x automatically, not retrying. Persistent: report the "
                              "'Flagged cells' section to the coordinator, or re-run by hand with "
                              "`python orchestrate_sweep.py --graphs <graph> --methods <method>`")
    return "rerun", f"re-running automatically (attempt {done + 1}/{SUSPECT_RERUN_MAX})"


SKIPPED_METHODS: List[str] = []


def render_status(status: dict) -> str:
    model, cells, pairs, methods = status["model"], status["cells"], status["pairs"], status["methods"]
    stamp = time.strftime("%Y-%m-%d %H:%M")
    lines = [f"# Sweep — `{model}` — {stamp}", ""]
    if SKIPPED_METHODS:
        lines += [f"**Methods not run for this model (by decision, --skip-methods): {', '.join(SKIPPED_METHODS)}.** "
                  "They are absent from every table below and do not count against completeness.", ""]
    n_missing, n_flag = len(status.get("missing", [])), len(status.get("flagged", []))
    if status["complete"]:
        lines.append("**COMPLETE** — every graph x method cell holds one record per question, "
                     "and no cell is dominated by infrastructure failures.")
    else:
        parts = []
        if n_missing:
            parts.append(f"{n_missing} cell(s) marked ✗ are missing or truncated")
        if n_flag:
            parts.append(f"{n_flag} cell(s) marked ⚠ failed on infrastructure (timeouts / API) and were "
                         "never really evaluated — see *Flagged cells* below")
        lines.append("**NOT CLEAN** — " + "; ".join(parts) + ". Re-run `python orchestrate_sweep.py` "
                     "(it re-runs only these cells). Do not report these numbers.")
    lines += ["", f"- generated: {time.strftime('%Y-%m-%d %H:%M')} · commit `{_git('rev-parse', '--short', 'HEAD')}` "
              f"· benchmarks `{_benchmarks_version()}` · artifacts set `{_artifact_set_id()}`",
              f"- run config: CYPHER_EMPTY_IS_WRONG={getattr(cfg, 'CYPHER_EMPTY_IS_WRONG', '?')} · "
              f"CYPHER_SEMANTIC_REPAIR={getattr(cfg, 'CYPHER_SEMANTIC_REPAIR', '?')} · "
              f"RETRIEVAL fuzzy/vector/lev={int(bool(getattr(cfg, 'RETRIEVAL_FUZZY', 1)))}/"
              f"{int(bool(getattr(cfg, 'RETRIEVAL_VECTOR', 0)))}/{int(bool(getattr(cfg, 'RETRIEVAL_LEVENSHTEIN', 1)))} · "
              f"SHARDS={getattr(cfg, 'SHARDS', '?')} (cyanchor always 1)", ""]
    # ── completeness matrix ──
    labels = {m: lab for lab, _, m in METHODS}
    lines += ["## Completeness (n / err per cell; n must equal the question count)", "",
              "| dataset | graph | questions | " + " | ".join(labels[m] for m in methods) + " |",
              "|---|---|--:|" + "|".join("---" for _ in methods) + "|"]
    for ds, g in pairs:
        row = [DATASET_INFO[ds][1], g, str(cells[(ds, g, methods[0])]["expected"])]
        for m in methods:
            c = cells[(ds, g, m)]
            mark = "⚠ " if c["suspect"] else ("✓ " if c["complete"] else "✗ ")
            row.append(mark + (f"{c['n']}/{c['err']}" if c["n"] else "missing"))
        lines.append("| " + " | ".join(row) + " |")
    # ── flagged cells: what failed, why, and the one command that re-runs it ──
    flagged = [(k, cells[k]) for k in status.get("flagged", [])]
    if flagged:
        lines += ["", "## Flagged cells — infrastructure failures, not results", "",
                  "These cells hold one record per question but a large share of those records are "
                  "timeouts or API failures: the model never answered them and they score 0 for the wrong "
                  "reason. `python orchestrate_sweep.py` re-runs them automatically (up to "
                  f"{SUSPECT_RERUN_MAX} times); to re-run one by hand use the command shown.", ""]
        for (ds, g, m), c in flagged:
            bd = c["breakdown"]
            lines += [f"- **{DATASET_INFO[ds][1]} · {g} · {labels[m]}** — {c['why']}.",
                      f"  errors: infra {bd['infra']} · gold {bd['gold']} · agent {bd['agent']} · other {bd['other']}",
                      f"  most common: `{bd['top_error'] or '—'}`",
                      f"  re-run: `python orchestrate_sweep.py --graphs {g} --methods {m}`"]
    # ── error breakdown per dataset × method (so 116 errors reads as 71 model + 45 timeouts) ──
    lines += ["", "## Errors by kind (pooled per dataset) — infra / gold / agent / other", "",
              "`infra` = timeout, API or rate-limit failure (recoverable by re-running; flags ⚠ when large). "
              "`gold` = the benchmark's own gold query failed (a data defect, the same for every model). "
              "`agent` = the model's generated Cypher failed (the model's result). "
              "`other` = unclassified.", "",
              "| method | " + " | ".join(DATASET_INFO[ds][1] for ds in DATASET_INFO
                                          if any(p[0] == ds for p in pairs)) + " | All |",
              "|---|" + "---|" * (sum(1 for ds in DATASET_INFO if any(p[0] == ds for p in pairs)) + 1)]
    for m in methods:
        row = [labels[m]]
        tot = collections.Counter()
        for ds in DATASET_INFO:
            if not any(p[0] == ds for p in pairs):
                continue
            k = collections.Counter()
            for (d2, g2, m2), c in cells.items():
                if d2 == ds and m2 == m:
                    for kind in ("infra", "gold", "agent", "other"):
                        k[kind] += c["breakdown"][kind]
            tot.update(k)
            row.append(f"{k['infra']} / {k['gold']} / {k['agent']} / {k['other']}")
        row.append(f"{tot['infra']} / {tot['gold']} / {tot['agent']} / {tot['other']}")
        lines.append("| " + " | ".join(row) + " |")
    # ── headline numbers (pooled over questions; errors score 0) ──
    lines += ["", "## Headline — EA / PSJS pooled over all questions (errored questions score 0)", "",
              "| method | " + " | ".join(f"{DATASET_INFO[ds][1]} EA | {DATASET_INFO[ds][1]} PSJS" for ds in DATASET_INFO
                                          if any(p[0] == ds for p in pairs)) + " | All EA | All PSJS | n | err |",
              "|---|" + "---:|" * (2 * sum(1 for ds in DATASET_INFO if any(p[0] == ds for p in pairs)) + 4)]
    for m in methods:
        row = [labels[m]]
        all_recs: List[dict] = []
        for ds in DATASET_INFO:
            if not any(p[0] == ds for p in pairs):
                continue
            recs = [r for (d2, g2, m2), c in cells.items() if d2 == ds and m2 == m for r in c["records"]]
            partial = any(not c["complete"] for (d2, g2, m2), c in cells.items() if d2 == ds and m2 == m)
            row += [_fmt(ea(recs)) + ("*" if partial else ""), _fmt(psjs(recs)) + ("*" if partial else "")]
            all_recs += recs
        row += [_fmt(ea(all_recs)), _fmt(psjs(all_recs)), str(len(all_recs)), str(n_err(all_recs))]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "`*` = one or more cells of that dataset are incomplete; the number is over the records present."]
    # ── the breakdown tables the paper uses, per dataset and over everything ──
    scopes = [(DATASET_INFO[ds][1], ds) for ds in DATASET_INFO if any(p[0] == ds for p in pairs)]
    if len(scopes) > 1:
        scopes.append(("All datasets", None))
    for title, ds in scopes:
        by_m = {m: [r for (d2, g2, m2), c in cells.items() if m2 == m and (ds is None or d2 == ds) for r in c["records"]]
                for m in methods}
        if not any(by_m.values()):
            continue
        lines += ["", f"## {title} — by perturbation strategy", "",
                  "EA", "", _breakdown(by_m, "strategy", list(_STRAT_ORDER), ea, labels, methods), "",
                  "PSJS", "", _breakdown(by_m, "strategy", list(_STRAT_ORDER), psjs, labels, methods),
                  "", f"## {title} — by query difficulty", "",
                  "EA", "", _breakdown(by_m, "difficulty", list(_DIFF_ORDER), ea, labels, methods), "",
                  "PSJS", "", _breakdown(by_m, "difficulty", list(_DIFF_ORDER), psjs, labels, methods)]
    lines += ["", f"Per-graph tables: `{cfg.REPORT_DIR}/{model}/<Dataset>/<graph>.md`; "
              f"per-dataset pooled tables: `{cfg.REPORT_DIR}/{model}/<Dataset>/_summary.md`."]
    return "\n".join(lines) + "\n"


def write_status(status: dict) -> Path:
    """One timestamped file per driver invocation (never overwritten) plus
    SWEEP.md, a copy of the latest. Returns the timestamped path."""
    root = report_root(status["model"]); root.mkdir(parents=True, exist_ok=True)
    text = render_status(status)
    out = root / f"SWEEP_{time.strftime('%Y%m%d-%H%M%S')}.md"
    out.write_text(text, encoding="utf-8")
    (root / "SWEEP.md").write_text(text, encoding="utf-8")
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Running one cell
# ──────────────────────────────────────────────────────────────────────────────

_LOG_PATH: Optional[Path] = None


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _LOG_PATH is not None:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def ensure_fcav_index(dataset: str, graph: str) -> None:
    """Build the FCAV value index for a graph whose archive has none — the same
    steps as setup_fcav.py, for this one pair — so the fcav method never
    starts on a missing index (eval_run would refuse it)."""
    from eval.artifact_swap import archive_dir_for, swap_in, archive_optional_dir
    from neo4j import GraphDatabase
    from fcav import build_fcav_index
    if (archive_dir_for(dataset, graph) / "generated" / "fcav").is_dir():
        return
    log(f"  fcav index missing for {dataset}__{graph}: building it (OpenAI embeddings of the graph's values)")
    swap_in(dataset, graph)
    conn = cfg.conn_for(dataset, graph)
    driver = GraphDatabase.driver(conn.uri, auth=(conn.user, conn.password))
    try:
        m = build_fcav_index(driver, conn.database, include_descriptions=False,
                             dataset=dataset, graph=graph, uri=conn.uri)
    finally:
        driver.close()
    archive_optional_dir(dataset, graph, "generated/fcav")
    log(f"  fcav index built: {m['count']} values")


def run_cell(dataset: str, graph: str, method: str, *, limit: Optional[int], out_dir: str,
             user_shards: int, model: str, state: dict) -> dict:
    """Run one (pair, method) with retry; returns the cell status afterwards."""
    import eval_run
    key = f"{dataset}__{graph}__{method}"
    entry = state["cells"].setdefault(key, {"tries": 0})
    if method == "fcav":
        try:
            ensure_fcav_index(dataset, graph)
        except Exception as exc:  # noqa: BLE001
            entry.update({"status": "failed", "last_error": f"fcav index: {type(exc).__name__}: {exc}"})
            log(f"  ✗ {key}: could not build the fcav index: {type(exc).__name__}: {exc}")
            return cell_status(dataset, graph, method, 0, out_dir, model)
    cfg.METHOD     = method
    cfg.EVAL_PAIRS = [(dataset, graph)]
    cfg.LIMIT      = limit
    cfg.OUT_DIR    = out_dir
    cfg.VERBOSE    = False
    # CyANCHOR is the most LLM-call-heavy method: SHARDS>1 bursts the provider,
    # rate-limit backoff trips the per-example watchdog, and those timeouts score
    # 0 — so it always runs at SHARDS=1 with a generous per-example cap.
    if method == "cyanchor":
        cfg.SHARDS = 1
        os.environ["EVAL_PER_EXAMPLE_TIMEOUT"] = CYANCHOR_PER_EXAMPLE_TIMEOUT
    else:
        cfg.SHARDS = user_shards
        os.environ.pop("EVAL_PER_EXAMPLE_TIMEOUT", None)
    expected = state["expected"][f"{dataset}__{graph}"] if limit is None else min(limit, state["expected"][f"{dataset}__{graph}"])
    for attempt in range(1, MAX_TRIES + 1):
        entry["tries"] = entry.get("tries", 0) + 1
        t0 = time.time()
        log(f"  ▶ {key}  (try {attempt}/{MAX_TRIES}, SHARDS={cfg.SHARDS}, limit={limit})")
        try:
            rc = eval_run.main()
        except SystemExit as exc:      # eval_run may sys.exit on a config error
            rc = int(exc.code or 0)
        except Exception as exc:  # noqa: BLE001
            log(f"    eval_run raised: {type(exc).__name__}: {exc}")
            rc = 99
        c = cell_status(dataset, graph, method, expected, out_dir, model)
        log(f"    rc={rc} records={c['n']}/{expected} err={c['err']} ({time.time() - t0:.0f}s)")
        if c["complete"]:
            entry.update({"status": "done", "n": c["n"], "err": c["err"], "dir": c["dir"],
                          "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            save_state(state)
            return c
        entry["last_error"] = f"rc={rc}, records={c['n']}/{expected}"
        save_state(state)
    entry["status"] = "failed"
    save_state(state)
    log(f"  ✗ {key}: not complete after {MAX_TRIES} attempts — continuing with the next cell")
    return cell_status(dataset, graph, method, expected, out_dir, model)


# ──────────────────────────────────────────────────────────────────────────────
# Reports (same tooling as the committed gpt-4.1 tables)
# ──────────────────────────────────────────────────────────────────────────────

def refresh_graph_report(dataset: str, graph: str, model: str) -> None:
    folder, label = DATASET_INFO[dataset]
    methods = []
    for lab, ret, m in METHODS:
        d = newest_run_dir(dataset, graph, m, eval_paths.RUNS_ROOT, model)
        if d is not None and (d / "records.jsonl").is_file():
            methods.append({"label": lab, "retrieval": ret, "dir": str(d.relative_to(REPO))})
    if not methods:
        return
    n = max(len(read_records(REPO / m["dir"])) for m in methods)
    spec = {"title": f"Report — {graph} (entity-perturbed {label})",
            "out": f"{cfg.REPORT_DIR}/{model}/{folder}/{graph}.md",
            "graph": graph, "dataset": label, "n_questions": n,
            "generated": time.strftime("%Y-%m-%d"), "llm": model, "methods": methods}
    (report_root(model) / folder).mkdir(parents=True, exist_ok=True)
    tmp = REPO / "logs" / "_sweep_tmp"; tmp.mkdir(parents=True, exist_ok=True)
    sp = tmp / f"_spec_{graph}.json"; sp.write_text(json.dumps(spec), encoding="utf-8")
    subprocess.run([sys.executable, "gen_ablation_report.py", str(sp)], check=True, cwd=REPO)
    log(f"  report: {spec['out']}")


def refresh_summary(dataset: str, graphs: List[str], model: str) -> None:
    folder, label = DATASET_INFO[dataset]
    have = [g for g in graphs if eval_paths.latest_run_dir(dataset, g, method_seg("cyanchor")) is not None]
    if not have:
        return
    (report_root(model) / folder).mkdir(parents=True, exist_ok=True)
    out = f"{cfg.REPORT_DIR}/{model}/{folder}/_summary.md"
    subprocess.run([sys.executable, "gen_pooled_report.py", out, label, f"Report — {label} (all graphs pooled)",
                    dataset, *have], check=True, cwd=REPO)
    log(f"  summary: {out}")


# ──────────────────────────────────────────────────────────────────────────────
# Pre-flight, state, publish
# ──────────────────────────────────────────────────────────────────────────────

def preflight(pairs: List[Tuple[str, str]]) -> bool:
    """verify_setup's two checks for every pair; False if anything is red."""
    import verify_setup
    from scripts import artifact_manifest as am
    from eval.artifact_swap import _setup_artifacts_root
    root = _setup_artifacts_root()
    manifest = am.load_manifest(am.manifest_path(root))
    ok = True
    for ds, g in pairs:
        status, detail = verify_setup._check_archive(ds, g)
        mstatus, mdetail = am.check_pair(manifest, root, ds, g)
        bad = status != "OK" or mstatus in (am.MISMATCH, am.MISSING)
        mark = "✗" if bad else ("!" if mstatus == am.UNPUBLISHED else "✓")
        log(f"  {mark} {ds}__{g}: {status} — {detail} | artifacts {mstatus}")
        ok = ok and not bad
    return ok


def state_path(model: str) -> Path:
    return REPO / "logs" / f"sweep_{model}.json"


def load_state(model: str, expected: Dict[Tuple[str, str], int]) -> dict:
    p = state_path(model)
    st = {"model": model, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "cells": {}}
    if p.is_file():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    st["expected"] = {f"{ds}__{g}": n for (ds, g), n in expected.items()}
    return st


def save_state(st: dict) -> None:
    p = state_path(st["model"]); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=2), encoding="utf-8")


def _remote_https_url() -> Optional[str]:
    """https://github.com/<owner>/<repo> for origin, or None if it cannot be derived."""
    url = _git("remote", "get-url", "origin")
    m = (re.match(r"^https?://([^/]+)/(.+?)(?:\.git)?/?$", url)
         or re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", url))
    return f"https://{m.group(1)}/{m.group(2)}" if m else None


def _classify_push_failure(stderr: str) -> str:
    e = stderr.lower()
    if "403" in e or "denied" in e or "not authorized" in e or "permission" in e or "authentication" in e:
        return "access"
    if "non-fast-forward" in e or "fetch first" in e or "rejected" in e:
        return "moved"
    if "could not resolve" in e or "unable to access" in e or "connection" in e or "timed out" in e:
        return "network"
    return "unknown"


def _publish_tree(repo: Path, branch: str, run_dirs: List[str], extra_paths: List[str],
                  mirror_roots: List[str], message: str) -> Tuple[str, str]:
    """Commit *run_dirs* + *extra_paths* (repo-relative) onto ``origin/<branch>``
    and push, without touching the caller's branch or working tree.

    Builds the commit in a detached throw-away worktree based on the remote
    branch (or HEAD when the branch does not exist yet), first un-tracking
    *mirror_roots* so the committed tree mirrors what is on disk now, then
    copying the paths in and force-adding them (they live under gitignored
    ``logs/``). Returns ``("pushed"|"unchanged", commit_sha)``; raises
    ``subprocess.CalledProcessError`` with stderr on git failure."""
    def git(*args, cwd=repo, **kw):
        return subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                              capture_output=True, **kw)
    git("worktree", "prune")
    # a hard kill during an earlier publish can leave a registered t2c_publish_* worktree behind
    for line in subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo, text=True,
                               capture_output=True).stdout.splitlines():
        if line.startswith("worktree ") and "t2c_publish_" in line:
            subprocess.run(["git", "worktree", "remove", "--force", line[len("worktree "):]],
                           cwd=repo, capture_output=True)
    git("worktree", "prune")
    subprocess.run(["git", "fetch", "origin", branch], cwd=repo, text=True, capture_output=True)  # may not exist yet
    remote_ok = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
                               cwd=repo, capture_output=True).returncode == 0
    base = f"refs/remotes/origin/{branch}" if remote_ok else "HEAD"
    tmp = Path(tempfile.mkdtemp(prefix="t2c_publish_"))
    try:
        git("worktree", "add", "--detach", str(tmp), base)
        if mirror_roots:
            git("rm", "-r", "-q", "--cached", "--ignore-unmatch", *mirror_roots, cwd=tmp)
        to_add: List[str] = []
        for rel in run_dirs + extra_paths:
            src = repo / rel
            dst = tmp / rel
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            else:
                continue
            to_add.append(rel)
        if to_add:
            git("add", "-f", "--", *to_add, cwd=tmp)
        changed = git("status", "--porcelain", cwd=tmp).stdout.strip() != ""
        if changed:
            git("commit", "-q", "-m", message, cwd=tmp)
        sha = git("rev-parse", "--short", "HEAD", cwd=tmp).stdout.strip()
        git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=tmp)
        return ("pushed" if changed else "unchanged"), sha
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tmp)], cwd=repo, capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _cell_label(k: Tuple[str, str, str]) -> str:
    ds, g, m = k
    return f"{DATASET_INFO[ds][1]} · {g} · {m}"


def publish(status: dict, allow_incomplete: bool) -> int:
    model = status["model"]
    branch = f"sweep/{model}"
    missing, flagged = status.get("missing", []), status.get("flagged", [])
    cells = status["cells"]

    # ── 1. verdict ──────────────────────────────────────────────────────────
    if (missing or flagged) and not allow_incomplete:
        log("✗ publish refused — the sweep is not clean:")
        for k in missing:
            c = cells[k]
            log(f"    ✗ {_cell_label(k)}: {c['n']}/{c['expected']} records" + ("" if c["n"] else " (missing)"))
        for k in flagged:
            log(f"    ⚠ {_cell_label(k)}: {cells[k]['why']}")
        log("  Next:")
        log("    1. python orchestrate_sweep.py            # re-runs only the ✗ and ⚠ cells; everything else is kept")
        log("    2. python orchestrate_sweep.py --status   # confirm every cell shows ✓")
        log("    3. if a ⚠ cell is still flagged after its automatic re-runs, publish anyway so the finished")
        log("       records reach the repository, and paste the 'Flagged cells' section to the coordinator:")
        log("       python orchestrate_sweep.py --publish --allow-incomplete")
        log("  Do not send report files by email or chat — the per-question records only exist on the branch.")
        return 1

    # ── 2. can we push at all? (a dry run creates nothing) ──────────────────
    dry = subprocess.run(["git", "push", "--dry-run", "origin", f"HEAD:refs/heads/{branch}"],
                         cwd=REPO, text=True, capture_output=True)
    if dry.returncode != 0:
        kind = _classify_push_failure(dry.stderr)
        if kind == "access":
            log("✗ you cannot push to this repository (no write access).")
            log("  Ask the coordinator to add you as a collaborator on GitHub and accept the invitation,")
            log("  then run --publish again. Nothing was changed. Do not send files instead.")
            return 1
        if kind == "network":
            log("✗ GitHub is not reachable from here (network / VPN / proxy). Nothing was changed.")
            log("  " + dry.stderr.strip().splitlines()[-1] if dry.stderr.strip() else "")
            return 1
        # 'moved' (non-fast-forward) is expected when the branch already exists — handled below.

    # ── 3. build + push in a throw-away worktree ────────────────────────────
    run_dirs = sorted({c["dir"] for c in cells.values() if c["dir"]})
    extras = [f"{cfg.REPORT_DIR}/{model}", "eval_config.py"] + [
        str(p.relative_to(REPO)) for p in (state_path(model), REPO / "logs" / f"sweep_{model}.log") if p.is_file()]
    n_cells = len(cells); n_done = sum(1 for c in cells.values() if c["complete"] and not c["suspect"])
    verdict = "full suite" if status["complete"] else "PARTIAL"
    msg = (f"sweep({model}): {verdict} — {n_done}/{n_cells} clean graph x method cells, {len(run_dirs)} run dirs + reports\n\n"
           f"Generator: {model}. Base: {_git('rev-parse', '--short', 'HEAD')}. "
           f"Benchmarks {_benchmarks_version()}, artifacts set {_artifact_set_id()}.\n"
           f"records.jsonl / summary.json per run dir under logs/runs/; tables under {cfg.REPORT_DIR}/{model}/.")
    if missing:
        msg += "\n\nMissing / truncated cells:\n" + "\n".join(f"  ✗ {_cell_label(k)}" for k in missing)
    if flagged:
        msg += "\n\nCells flagged as infrastructure failures (⚠), included as-is:\n" + "\n".join(
            f"  ⚠ {_cell_label(k)}: {cells[k]['why']}" for k in flagged)
    try:
        outcome, sha = _publish_tree(REPO, branch, run_dirs, extras,
                                     mirror_roots=[eval_paths.RUNS_ROOT, f"{cfg.REPORT_DIR}/{model}"], message=msg)
    except subprocess.CalledProcessError as exc:
        kind = _classify_push_failure(exc.stderr or "")
        if kind == "access":
            log("✗ push rejected: no write access to this repository. Ask the coordinator to add you as a "
                "collaborator, then run --publish again. Nothing was changed on your machine.")
        elif kind == "moved":
            log("✗ push rejected: the remote branch moved while publishing (someone else pushed to it). "
                "Run --publish again — it rebuilds on the new tip. Never force-push.")
        else:
            log("✗ git failed during publish. Nothing was changed on your branch or working tree.")
            log("  " + (exc.stderr or str(exc)).strip()[-600:])
        return 1

    # ── 4. what to send ─────────────────────────────────────────────────────
    url = _remote_https_url()
    report_url = f"{url}/blob/{branch}/{cfg.REPORT_DIR}/{model}/SWEEP.md" if url else f"(report at {cfg.REPORT_DIR}/{model}/SWEEP.md on branch {branch})"
    log(f"✓ published branch {branch} @ {sha} ({n_done}/{n_cells} clean cells, {len(run_dirs)} run dirs)"
        + (" — no change since the last publish" if outcome == "unchanged" else "")
        + ". Your branch and working tree were not touched.")
    log("")
    log("  Send the coordinator exactly this:")
    log(f"    model:   {model}")
    log(f"    branch:  {branch}")
    log(f"    report:  {report_url}")
    if not status["complete"]:
        log(f"    status:  PARTIAL — {len(missing)} missing, {len(flagged)} ⚠ (see the 'Flagged cells' section of the report)")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    global _LOG_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", action="store_true", help=f"5 methods x {SMOKE_PAIR[1]} x {SMOKE_LIMIT} questions into {SMOKE_OUT}/")
    ap.add_argument("--status", action="store_true", help="print the completeness matrix + headline numbers; run nothing")
    ap.add_argument("--publish", action="store_true", help="commit this model's run dirs + reports to branch sweep/<model> and push")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="let --publish push a PARTIAL branch although cells are missing (✗) or flagged ⚠; "
                         "the report and the commit message list them")
    ap.add_argument("--graphs", nargs="+", metavar="GRAPH", help="restrict to these graphs")
    ap.add_argument("--methods", nargs="+", metavar="METHOD", choices=[m for _, _, m in METHODS], help="restrict to these methods (a partial re-run; the verdict still covers all five)")
    ap.add_argument("--skip-methods", nargs="+", metavar="METHOD", choices=[m for _, _, m in METHODS], default=[],
                    help="methods this model does NOT run (e.g. react for a model without tool calling): removed from the suite, so COMPLETE and --publish ignore them; recorded in the SWEEP file")
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args(argv)

    model = model_name()
    _LOG_PATH = REPO / "logs" / f"sweep_{model}.log"
    all_methods = [m for _, _, m in METHODS if m not in set(args.skip_methods)]
    if not all_methods:
        ap.error("--skip-methods removed every method")
    methods = [m for m in (args.methods or all_methods) if m in all_methods]
    manual = bool(args.graphs or args.methods)   # an explicit selection is a request, not an automatic re-run
    global SKIPPED_METHODS
    SKIPPED_METHODS = list(args.skip_methods)
    expected = expected_counts()
    # The verdict (COMPLETE / NOT CLEAN, the SWEEP file, --publish) is ALWAYS
    # over the full suite; --graphs / --methods only restrict what runs now.
    scope_pairs = [SMOKE_PAIR] if args.smoke else suite_pairs()
    pairs = list(scope_pairs)
    if args.graphs:
        pairs = [p for p in pairs if p[1] in args.graphs]
        unknown = set(args.graphs) - {p[1] for p in pairs}
        if unknown:
            ap.error(f"unknown graph(s) {sorted(unknown)}; suite graphs: {[p[1] for p in suite_pairs()]}")
    out_dir = SMOKE_OUT if args.smoke else eval_paths.RUNS_ROOT
    limit = SMOKE_LIMIT if args.smoke else None
    if args.smoke:
        expected = {p: min(SMOKE_LIMIT, expected.get(p, 0)) for p in scope_pairs}

    if args.status or args.publish:
        status = build_status(scope_pairs, all_methods, expected, out_dir, model)
        text = render_status(status)
        print(text)
        if not args.smoke:
            log(f"status written: {write_status(status).relative_to(REPO)}")
        return publish(status, args.allow_incomplete) if args.publish else (0 if status["complete"] else 1)

    log(f"=== sweep start: model={model} graphs={len(pairs)} methods={methods} "
        f"{'SMOKE' if args.smoke else 'FULL'} ===")
    if not args.skip_preflight:
        log("pre-flight (archives vs live graphs, archives vs published set):")
        if not preflight(pairs):
            log("✗ pre-flight failed — fix the red lines (see docs/EXPERIMENT_HANDOUT.md §4) before running")
            return 1
    user_shards = int(getattr(cfg, "SHARDS", 1) or 1)
    state = load_state(model, expected)
    save_state(state)

    by_dataset: Dict[str, List[str]] = collections.OrderedDict()
    for ds, g in pairs:
        by_dataset.setdefault(ds, []).append(g)
    for ds, graphs in by_dataset.items():
        for g in graphs:
            for m in methods:
                probe = build_status([(ds, g)], methods, expected, out_dir, model)  # flags need the graph's peers
                c = probe["cells"][(ds, g, m)]
                key = f"{ds}__{g}__{m}"
                entry = state["cells"].setdefault(key, {"tries": 0})
                action, note = decide_cell(c, entry, manual)
                if action == "skip":
                    log(f"  = {key}: clean ({c['n']} records, err={c['err']}) — skipped")
                    continue
                if action == "persistent":
                    log(f"  ⚠ {key}: {c['why']} — {note}")
                    continue
                if action == "rerun":
                    if not manual:
                        entry["suspect_reruns"] = int(entry.get("suspect_reruns", 0)) + 1
                        save_state(state)
                    log(f"  ⚠ {key}: {c['why']} — {note}")
                run_cell(ds, g, m, limit=limit, out_dir=out_dir, user_shards=user_shards, model=model, state=state)
            if not args.smoke:
                try:
                    refresh_graph_report(ds, g, model)
                except Exception as exc:  # noqa: BLE001
                    log(f"  report generation failed for {ds}__{g}: {type(exc).__name__}: {exc}")
        if not args.smoke:
            try:
                refresh_summary(ds, graphs, model)
            except Exception as exc:  # noqa: BLE001
                log(f"  summary generation failed for {ds}: {type(exc).__name__}: {exc}")

    status = build_status(scope_pairs, all_methods, expected, out_dir, model)
    print(); print(render_status(status))
    if args.smoke:
        # A method whose every example errored is a systematic rejection (bad
        # parameter, missing key, unsupported feature) — stop before the full run.
        systematic = []
        for (ds, g, m), c in status["cells"].items():
            if c["n"] and c["err"] == c["n"]:
                first = next((r.get("error") for r in c["records"] if r.get("error")), "")
                systematic.append(f"{m}: every example errored — {str(first)[:300]}")
            elif not c["complete"]:
                why = state["cells"].get(f"{ds}__{g}__{m}", {}).get("last_error", "")
                systematic.append(f"{m}: {c['n']}/{c['expected']} records — the run did not finish"
                                  + (f" — {why}" if why else ""))
        if systematic:
            log("✗ SMOKE FAILED:\n  " + "\n  ".join(systematic) + "\n  Send these lines to the coordinator.")
            return 1
        log(f"✓ SMOKE OK — all {len(methods)} methods produced {SMOKE_LIMIT} records on {SMOKE_PAIR[1]} "
            "(a few errors are fine; a whole method erroring is not). Now run: python orchestrate_sweep.py")
        return 0
    out = write_status(status)
    log(f"=== sweep {'COMPLETE' if status['complete'] else 'NOT CLEAN'}: {out.relative_to(REPO)} ===")
    if status["complete"]:
        log("next: python orchestrate_sweep.py --publish")
    else:
        if status.get("missing"):
            log(f"{len(status['missing'])} cell(s) missing/truncated (✗); "
                f"{len(status.get('flagged', []))} cell(s) failed on infrastructure (⚠).")
        elif status.get("flagged"):
            log(f"{len(status['flagged'])} cell(s) failed on infrastructure (⚠) — see 'Flagged cells' in the report.")
        log("next: python orchestrate_sweep.py            # re-runs only the ✗ / ⚠ cells")
        log("      python orchestrate_sweep.py --publish  # when every cell shows ✓")
        log("      (a ⚠ cell that persists after its automatic re-runs: --publish --allow-incomplete, "
            "and send the 'Flagged cells' section to the coordinator)")
    return 0 if status["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
