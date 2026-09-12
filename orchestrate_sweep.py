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
    python orchestrate_sweep.py --status             # completeness matrix + headline numbers, no runs
    python orchestrate_sweep.py --publish            # branch sweep/<model>: run dirs + reports, commit, push

The model is ``eval_config.GENERATOR_LLM`` — the one line a participant edits.
Graphs are ``eval_config.FULL_EVAL_PAIRS_13_AUGMENTED``; methods are the five
below, in this order. The driver runs graph by graph (the live artifact tree is
swapped once per graph) and, per graph, the five methods in turn.

Completeness
------------
A cell (graph, method) is COMPLETE when the newest run for this model holds one
record per question of that graph (``records.jsonl`` rows == question count in
the benchmark file). Errored questions are allowed: the eval scores them 0
(denominator = all questions) and reports them in the ``err`` column — a graph
with a few broken golds or timeouts still completes. What must never happen is
a missing or truncated cell, and that is what the matrix checks.

Resume
------
Completion is read from disk, so re-running the same command skips every
complete cell and re-runs the rest (up to MAX_TRIES attempts each). A cell that
keeps failing is reported, not retried forever; the run continues with the next
cell. ``logs/sweep_<model>.json`` keeps the per-cell history.

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
import subprocess
import sys
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


def cell_status(dataset: str, graph: str, method: str, expected: int, out_dir: str, model: str) -> dict:
    d = newest_run_dir(dataset, graph, method, out_dir, model)
    recs = read_records(d)
    return {"dir": str(d.relative_to(REPO)) if d else None, "n": len(recs), "err": n_err(recs),
            "expected": expected, "complete": bool(recs) and len(recs) == expected, "records": recs}


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
    complete = all(c["complete"] for c in cells.values())
    return {"model": model, "cells": cells, "complete": complete, "pairs": pairs, "methods": methods}


def render_status(status: dict) -> str:
    model, cells, pairs, methods = status["model"], status["cells"], status["pairs"], status["methods"]
    stamp = time.strftime("%Y-%m-%d %H:%M")
    lines = [f"# Sweep — `{model}` — {stamp}", ""]
    lines.append(("**COMPLETE** — every graph x method cell holds one record per question."
                  if status["complete"] else
                  "**INCOMPLETE** — cells marked ✗ are missing or truncated; re-run "
                  "`python orchestrate_sweep.py` to fill them. Do not report these numbers."))
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
            row.append(("✓ " if c["complete"] else "✗ ") + (f"{c['n']}/{c['err']}" if c["n"] else "missing"))
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


def publish(status: dict, allow_incomplete: bool) -> int:
    model = status["model"]
    if not status["complete"] and not allow_incomplete:
        log("✗ the sweep is INCOMPLETE — publish refused (pass --allow-incomplete only if the coordinator says so)")
        return 1
    branch = f"sweep/{model}"
    base = _git("rev-parse", "--abbrev-ref", "HEAD")
    subprocess.run(["git", "checkout", "-B", branch], cwd=REPO, check=True)
    dirs = sorted({c["dir"] for c in status["cells"].values() if c["dir"]})
    subprocess.run(["git", "add", "-f", *dirs], cwd=REPO, check=True)
    extras = [f"{cfg.REPORT_DIR}/{model}", "eval_config.py"] + [str(p.relative_to(REPO)) for p in
                                                  (state_path(model), REPO / "logs" / f"sweep_{model}.log") if p.is_file()]
    subprocess.run(["git", "add", "-f", *extras], cwd=REPO, check=True)
    n_cells = len(status["cells"]); n_done = sum(1 for c in status["cells"].values() if c["complete"])
    msg = (f"sweep({model}): {'full suite' if status['complete'] else 'PARTIAL'} — "
           f"{n_done}/{n_cells} graph x method cells, {len(dirs)} run dirs + reports\n\n"
           f"Generator: {model}. Base: {base}. Benchmarks {_benchmarks_version()}, artifacts set {_artifact_set_id()}.\n"
           f"records.jsonl / summary.json per run dir under logs/runs/; tables under {cfg.REPORT_DIR}/{model}/.")
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=REPO, check=True)
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=REPO, check=True)
    log(f"✓ published branch {branch} ({n_done}/{n_cells} cells, {len(dirs)} run dirs). You are now on that branch.")
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
    ap.add_argument("--allow-incomplete", action="store_true", help="let --publish proceed on an incomplete sweep")
    ap.add_argument("--graphs", nargs="+", metavar="GRAPH", help="restrict to these graphs")
    ap.add_argument("--methods", nargs="+", metavar="METHOD", choices=[m for _, _, m in METHODS], help="restrict to these methods")
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args(argv)

    model = model_name()
    _LOG_PATH = REPO / "logs" / f"sweep_{model}.log"
    methods = args.methods or [m for _, _, m in METHODS]
    expected = expected_counts()
    pairs = [SMOKE_PAIR] if args.smoke else suite_pairs()
    if args.graphs:
        pairs = [p for p in pairs if p[1] in args.graphs]
        unknown = set(args.graphs) - {p[1] for p in pairs}
        if unknown:
            ap.error(f"unknown graph(s) {sorted(unknown)}; suite graphs: {[p[1] for p in suite_pairs()]}")
    out_dir = SMOKE_OUT if args.smoke else eval_paths.RUNS_ROOT
    limit = SMOKE_LIMIT if args.smoke else None
    if args.smoke:
        expected = {p: min(SMOKE_LIMIT, expected.get(p, 0)) for p in pairs}

    if args.status or args.publish:
        status = build_status(pairs, methods, expected, out_dir, model)
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
                c = cell_status(ds, g, m, expected[(ds, g)], out_dir, model)
                if c["complete"]:
                    log(f"  = {ds}__{g}__{m}: complete ({c['n']} records, err={c['err']}) — skipped")
                    continue
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

    status = build_status(pairs, methods, expected, out_dir, model)
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
                systematic.append(f"{m}: {c['n']}/{c['expected']} records — the run did not finish")
        if systematic:
            log("✗ SMOKE FAILED:\n  " + "\n  ".join(systematic) + "\n  Send these lines to the coordinator.")
            return 1
        log(f"✓ SMOKE OK — all {len(methods)} methods produced {SMOKE_LIMIT} records on {SMOKE_PAIR[1]} "
            "(a few errors are fine; a whole method erroring is not). Now run: python orchestrate_sweep.py")
        return 0
    out = write_status(status)
    log(f"=== sweep {'COMPLETE' if status['complete'] else 'INCOMPLETE'}: {out.relative_to(REPO)} ===")
    if not status["complete"]:
        log("re-run `python orchestrate_sweep.py` to fill the missing cells; then `python orchestrate_sweep.py --publish`")
    return 0 if status["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
