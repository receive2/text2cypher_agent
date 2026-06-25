#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pole_baselines.py
=====================
Re-run the FOUR baselines (no_val_link, fcav, react, graphrag) for ZOGRASCOPE
`pole` on the FULL augmented set (1441 examples), so every method is scored on
the SAME 1441 — the orchestrator already runs CyANCHOR at 1441, but the existing
baseline records were a 200-example subset (mismatched n). Then regenerate
report/ZOGRASCOPE/pole.md + _summary.md over all 5 methods at 1441.

This re-runs baselines verbatim (METHOD env only) — it does NOT optimize them.
Idempotent via logs/pole_baselines_state.json (restart skips finished methods).
Launch AFTER the orchestrator finishes CyANCHOR pole (single shared live tree).
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path
import eval_config as cfg

REPO = Path(__file__).resolve().parent
DS, G, PREFIX = "zograscope_augmented", "pole", "pol_"
METHODS = ["no_val_link", "fcav", "react", "graphrag"]
TMP = REPO / "logs" / "_pole_tmp"
STATE = REPO / "logs" / "pole_baselines_state.json"
LOG = REPO / "logs" / "pole_baselines.log"
MAX_TRIES = 3

def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"; print(line, flush=True)
    with LOG.open("a") as fh: fh.write(line + "\n")

def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"done": []}

def save(s): STATE.write_text(json.dumps(s, indent=2))

def run_method(method):
    import eval_run
    os.environ["METHOD"] = method
    os.environ["EVAL_PER_EXAMPLE_TIMEOUT"] = "600"
    out = TMP / f"{DS}__{G}.records.jsonl"
    summ = TMP / f"{DS}__{G}.summary.json"
    for attempt in range(1, MAX_TRIES + 1):
        if TMP.exists(): shutil.rmtree(TMP, ignore_errors=True)
        TMP.mkdir(parents=True, exist_ok=True)
        cfg.EVAL_PAIRS = [(DS, G)]; cfg.OUT_DIR = str(TMP); cfg.LIMIT = None; cfg.VERBOSE = False
        log(f"  run {method} pole full (try {attempt}/{MAX_TRIES}) SHARDS={getattr(cfg,'SHARDS',1)}")
        try:
            rc = eval_run.main()
        except Exception as exc:
            log(f"  raised {type(exc).__name__}: {exc}"); rc = 99
        n = sum(1 for _ in out.open()) if out.exists() else 0
        log(f"  -> rc={rc} records={n}")
        if rc == 0 and n > 0:
            dest = REPO / "logs" / f"{PREFIX}{method}"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out, dest / "records.jsonl")
            if summ.exists(): shutil.copyfile(summ, dest / "summary.json")
            return True
    return False

def gen_report():
    import orchestrate_cyanchor as o
    o.gen_graph_report("pole", "ZOGRASCOPE", "ZOGRASCOPE", "pol_", False)
    o.gen_summary("ZOGRASCOPE", "ZOGRASCOPE", ["pol_"])

def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    s = state()
    log(f"=== pole baselines start (done={s['done']}) ===")
    for m in METHODS:
        if m in s["done"]:
            log(f"skip (done): {m}"); continue
        ok = run_method(m)
        if ok:
            s["done"].append(m); save(s)
        else:
            log(f"FAILED {m} after {MAX_TRIES} tries; leaving its old records in place")
    try:
        gen_report()
        log("pole.md + ZOGRASCOPE _summary.md regenerated (all methods at 1441)")
    except Exception as exc:
        log(f"report gen failed: {type(exc).__name__}: {exc}")
    log("=== pole baselines DONE ===")

if __name__ == "__main__":
    raise SystemExit(main())
