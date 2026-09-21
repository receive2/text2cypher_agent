#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orchestrate_cyanchor.py
=======================
Re-run ONLY CyANCHOR for every (dataset, graph), graph-by-graph, and refresh the
reports — the operational driver for a full CyANCHOR refresh.

Per graph:
  * run CyANCHOR (fuzzy+lev, SHARDS-parallel) via eval_run.main(), with up to
    MAX_TRIES attempts; after MAX_TRIES consecutive failures, SKIP to the next.
  * eval_run writes the canonical run dir
    logs/runs/<aug_dataset>__<graph>__cyanchor_fl/ directly (no copy step); on
    success regenerate report/<folder>/<graph>.md (combining the freshly-run
    CyANCHOR row with the existing baseline rows — baselines are NOT re-run).
After each dataset's graphs finish, regenerate REPORT_DIR/<folder>/_summary.md.
covid additionally gets a fuzzy+lev+vec run (-> ...__covid__cyanchor_fvl), and its
report carries both the fuzzy+lev and fuzzy+lev+vec CyANCHOR rows.

State is journalled to logs/orchestrate_state.json so a restart skips finished
graphs (idempotent — safe to relaunch if the process dies).

Only CyANCHOR is touched; baselines (no_val_link/fcav/react/graphrag) are read
from their existing log dirs unchanged.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import eval_config as cfg
import eval_paths

REPO = Path(__file__).resolve().parent
STATE_PATH = REPO / "logs" / "orchestrate_state.json"
LOG_PATH = REPO / "logs" / "orchestrate.log"
MAX_TRIES = 3
TMP_OUT = REPO / "logs" / "_orch_tmp"

_BASELINES = [
    ("No Val Link",        "—",        "no_val_link"),
    ("FCAV",               "vector",   "fcav"),
    ("ReAct",              "fuzzy",    "react"),
    ("GraphRAG",           "norm-Lev", "graphrag"),
]

# (report_graph, conn_graph, vec?) per dataset. Run-dir locations are resolved
# through eval_paths from (aug_dataset, conn_graph, method) — no prefix map.
DATASETS = [
    ("CypherBench", "CypherBench", "cypherbench_augmented", [
        ("company",             "company",             False),
        ("fictional_character", "fictional_character", False),
        ("flight_accident",     "flight_accident",     False),
        ("geography",           "geography",           False),
        ("movie",               "movie",               False),
        ("nba",                 "nba",                 False),
        ("politics",            "politics",            False),
    ]),
    ("MindTheQuery", "MindTheQuery", "mindthequery_augmented", [
        ("bloom",      "bloom",      False),
        ("covid",      "covid",      False),  # vec skipped per request
        ("er",         "er",         False),
        ("healthcare", "healthcare", False),
        ("wwc",        "wwc",        False),
    ]),
]


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"done": [], "skipped": []}


def save_state(st: dict) -> None:
    STATE_PATH.write_text(json.dumps(st, indent=2))


def _set_arms(vector: bool) -> None:
    """Pin the CyANCHOR method + retrieval arms on eval_config (the authoritative
    surface; eval_run._build_env propagates cfg to the workers). fuzzy+lev always;
    vector only for the vec pass."""
    cfg.METHOD                = "cyanchor"
    cfg.RETRIEVAL_FUZZY       = True
    cfg.RETRIEVAL_LEVENSHTEIN = True
    cfg.RETRIEVAL_VECTOR      = vector
    # SHARDS=1 for CyANCHOR — REQUIRED, not just a speed knob. CyANCHOR is the most
    # LLM-call-heavy method (PLAN + per-mention escalation/abstain judges + Cypher
    # gen + the ≤4-round semantic-repair loop + value-snap = 10+ gpt-4.1 calls/ex).
    # At SHARDS>1 the parallel workers burst the LLM API → rate-limit backoff → a
    # single example's call chain stalls for hundreds of seconds and trips the
    # per-example watchdog. Under the all-examples-denominator eval those timeouts
    # score 0, spuriously depressing CyANCHOR (verified: a question that took 622s
    # at SHARDS=4 ran 17s in isolation). SHARDS=1 = ~17s/ex, no contention.
    cfg.SHARDS = 1
    # Generous per-example cap as a second safety net (slowest legit examples ~70-120s).
    # Worker watchdog knob, not a run-config field, so it stays in env.
    os.environ["EVAL_PER_EXAMPLE_TIMEOUT"] = "900"


def _latest_records(dataset_key: str, conn_graph: str, method_seg: str):
    """records.jsonl of the newest run for a triple, or None (eval_paths
    resolves timestamped run dirs, falling back to the legacy layout)."""
    p = eval_paths.latest_run_dir(dataset_key, conn_graph, method_seg)
    return (p / "records.jsonl") if p else None


def run_cyanchor(aug_dataset: str, conn_graph: str, vector: bool) -> bool:
    """Run CyANCHOR for one pair with retry. eval_run writes a fresh timestamped
    run dir (logs/runs/<aug_dataset>__<conn_graph>__cyanchor_{fl,fvl}__<stamp>/)
    directly — no copy. Returns True iff records were produced."""
    import eval_run

    _set_arms(vector)
    tag_seg = eval_paths.method_tag("cyanchor", fuzzy=True, vector=vector, lev=True)

    for attempt in range(1, MAX_TRIES + 1):
        cfg.EVAL_PAIRS = [(aug_dataset, conn_graph)]
        cfg.OUT_DIR    = eval_paths.RUNS_ROOT
        cfg.LIMIT      = None
        cfg.VERBOSE    = False
        tag = f"{aug_dataset}__{conn_graph}{' +vec' if vector else ''} (try {attempt}/{MAX_TRIES})"
        log(f"  run {tag} SHARDS={getattr(cfg,'SHARDS',1)} -> {aug_dataset}__{conn_graph}__{tag_seg} ...")
        try:
            rc = eval_run.main()
        except Exception as exc:  # noqa: BLE001
            log(f"  eval_run raised: {type(exc).__name__}: {exc}")
            rc = 99
        # Resolve the dir eval_run just wrote (newest stamp for the triple).
        rec_file = _latest_records(aug_dataset, conn_graph, tag_seg)
        n = sum(1 for _ in rec_file.open()) if rec_file is not None and rec_file.exists() else 0
        log(f"  -> rc={rc}, records={n}")
        if rc == 0 and n > 0:
            return True
        log(f"  attempt {attempt} failed for {tag}")
    return False


def gen_graph_report(report_graph: str, conn_graph: str, dataset_key: str,
                     folder: str, label: str, vec: bool) -> None:
    wanted = list(_BASELINES) + [("CyANCHOR", "fuzzy+lev", "cyanchor_fl")]
    if vec:
        wanted.append(("CyANCHOR (+vector)", "fuzzy+lev+vec", "cyanchor_fvl"))
    methods = []
    for l, r, c in wanted:
        p = eval_paths.latest_run_dir(dataset_key, conn_graph, c)
        if p is not None:
            methods.append({"label": l, "retrieval": r, "dir": str(p)})
    methods = [m for m in methods if (REPO / m["dir"] / "records.jsonl").exists()]
    n = max((sum(1 for _ in (REPO / m["dir"] / "records.jsonl").open()) for m in methods),
            default=0)
    spec = {
        "title": f"Report — {report_graph} (entity-perturbed {label})",
        "out":   f"{cfg.REPORT_DIR}/{eval_paths.default_model()}/{folder}/{report_graph}.md",
        "graph": report_graph, "dataset": label, "n_questions": n,
        "generated": time.strftime("%Y-%m-%d"), "llm": eval_paths.default_model(), "methods": methods,
    }
    Path(cfg.REPORT_DIR, eval_paths.default_model(), folder).mkdir(parents=True, exist_ok=True)
    sp = TMP_OUT / f"_spec_{report_graph}.json"
    TMP_OUT.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(spec))
    subprocess.run([sys.executable, "gen_ablation_report.py", str(sp)], check=True, cwd=REPO)
    log(f"  report updated: {spec['out']}")


def gen_summary(folder: str, label: str, dataset_key: str, graphs: list[str]) -> None:
    out = f"{cfg.REPORT_DIR}/{eval_paths.default_model()}/{folder}/_summary.md"
    Path(cfg.REPORT_DIR, eval_paths.default_model(), folder).mkdir(parents=True, exist_ok=True)
    title = f"Report — {label} (all graphs pooled)"
    subprocess.run([sys.executable, "gen_pooled_report.py", out, label, title,
                    dataset_key, *graphs], check=True, cwd=REPO)
    log(f"  summary updated: {out}")


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    st = load_state()
    log(f"=== orchestrate start  (done={len(st['done'])} skipped={len(st['skipped'])}) ===")

    for label, folder, aug_dataset, graphs in DATASETS:
        for report_graph, conn_graph, vec in graphs:
            key = f"{aug_dataset}__{report_graph}"
            if key in st["done"] or key in st["skipped"]:
                log(f"skip (already {('done' if key in st['done'] else 'skipped')}): {key}")
                continue
            log(f"GRAPH {key}  vec={vec}")

            ok = run_cyanchor(aug_dataset, conn_graph, False)
            if ok and vec:
                okv = run_cyanchor(aug_dataset, conn_graph, True)
                if not okv:
                    log(f"  WARN vec pass failed for {key}; report will omit the vec row")
            if not ok:
                log(f"SKIP {key} after {MAX_TRIES} failed attempts")
                st["skipped"].append(key); save_state(st)
                continue

            try:
                gen_graph_report(report_graph, conn_graph, aug_dataset, folder, label, vec)
            except Exception as exc:  # noqa: BLE001
                log(f"  report gen failed for {key}: {type(exc).__name__}: {exc}")
            st["done"].append(key); save_state(st)

        # dataset complete -> refresh summary over the graphs we have records for
        have = [cg for _, cg, _ in graphs
                if (rf := _latest_records(aug_dataset, cg, "cyanchor_fl")) is not None
                and rf.exists()]
        if have:
            try:
                gen_summary(folder, label, aug_dataset, have)
            except Exception as exc:  # noqa: BLE001
                log(f"  summary gen failed for {label}: {type(exc).__name__}: {exc}")

    log(f"=== orchestrate DONE  (done={len(st['done'])} skipped={len(st['skipped'])}) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
