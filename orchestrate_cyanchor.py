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
    ("ReAct (Node + Rel)", "fuzzy",    "react"),
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
    """Pin the CyANCHOR method + retrieval arms via env (propagated to workers
    by eval_run._build_env). fuzzy+lev always; vector only for the vec pass."""
    os.environ["METHOD"]                = "cyanchor"
    os.environ["RETRIEVAL_FUZZY"]       = "1"
    os.environ["RETRIEVAL_LEVENSHTEIN"] = "1"
    os.environ["RETRIEVAL_VECTOR"]      = "1" if vector else "0"
    # Generous per-example cap: CyANCHOR is the most LLM-call-heavy method (PLAN +
    # per-mention retrieval/escalation/abstain + Cypher gen + QA), so the 60s
    # default truncates its hardest multi-entity questions while lighter baselines
    # finish — unfair. 600s lets every example complete (the slow ones are ~70-120s).
    os.environ["EVAL_PER_EXAMPLE_TIMEOUT"] = "600"


def run_cyanchor(aug_dataset: str, conn_graph: str, vector: bool) -> bool:
    """Run CyANCHOR for one pair with retry. eval_run writes the canonical run dir
    (logs/runs/<aug_dataset>__<conn_graph>__cyanchor_{fl,fvl}/) directly — no copy.
    Returns True iff records were produced."""
    import eval_run

    _set_arms(vector)
    tag_seg  = eval_paths.method_tag("cyanchor", fuzzy=True, vector=vector, lev=True)
    run_path = eval_paths.run_dir(aug_dataset, conn_graph, tag_seg)  # under logs/runs
    rec_file = run_path / "records.jsonl"

    for attempt in range(1, MAX_TRIES + 1):
        cfg.EVAL_PAIRS = [(aug_dataset, conn_graph)]
        cfg.OUT_DIR    = eval_paths.RUNS_ROOT
        cfg.LIMIT      = None
        cfg.VERBOSE    = False
        tag = f"{aug_dataset}__{conn_graph}{' +vec' if vector else ''} (try {attempt}/{MAX_TRIES})"
        log(f"  run {tag} SHARDS={getattr(cfg,'SHARDS',1)} -> {run_path} ...")
        try:
            rc = eval_run.main()
        except Exception as exc:  # noqa: BLE001
            log(f"  eval_run raised: {type(exc).__name__}: {exc}")
            rc = 99
        n = sum(1 for _ in rec_file.open()) if rec_file.exists() else 0
        log(f"  -> rc={rc}, records={n}")
        if rc == 0 and n > 0:
            return True
        log(f"  attempt {attempt} failed for {tag}")
    return False


def gen_graph_report(report_graph: str, conn_graph: str, dataset_key: str,
                     folder: str, label: str, vec: bool) -> None:
    methods = [{"label": l, "retrieval": r,
                "dir": str(eval_paths.run_dir(dataset_key, conn_graph, c))}
               for l, r, c in _BASELINES]
    methods.append({"label": "CyANCHOR (fuzzy+lev)", "retrieval": "fuzzy+lev",
                    "dir": str(eval_paths.run_dir(dataset_key, conn_graph, "cyanchor_fl"))})
    if vec:
        methods.append({"label": "CyANCHOR (fuzzy+lev+vec)", "retrieval": "fuzzy+lev+vec",
                        "dir": str(eval_paths.run_dir(dataset_key, conn_graph, "cyanchor_fvl"))})
    methods = [m for m in methods if (REPO / m["dir"] / "records.jsonl").exists()]
    n = max((sum(1 for _ in (REPO / m["dir"] / "records.jsonl").open()) for m in methods),
            default=0)
    spec = {
        "title": f"Report — {report_graph} (entity-perturbed {label})",
        "out":   f"{cfg.REPORT_DIR}/{folder}/{report_graph}.md",
        "graph": report_graph, "dataset": label, "n_questions": n,
        "generated": time.strftime("%Y-%m-%d"), "llm": "gpt-4.1", "methods": methods,
    }
    Path(cfg.REPORT_DIR, folder).mkdir(parents=True, exist_ok=True)
    sp = TMP_OUT / f"_spec_{report_graph}.json"
    TMP_OUT.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(spec))
    subprocess.run([sys.executable, "gen_ablation_report.py", str(sp)], check=True, cwd=REPO)
    log(f"  report updated: {spec['out']}")


def gen_summary(folder: str, label: str, dataset_key: str, graphs: list[str]) -> None:
    out = f"{cfg.REPORT_DIR}/{folder}/_summary.md"
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
                if (eval_paths.run_dir(aug_dataset, cg, "cyanchor_fl") / "records.jsonl").exists()]
        if have:
            try:
                gen_summary(folder, label, aug_dataset, have)
            except Exception as exc:  # noqa: BLE001
                log(f"  summary gen failed for {label}: {type(exc).__name__}: {exc}")

    log(f"=== orchestrate DONE  (done={len(st['done'])} skipped={len(st['skipped'])}) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
