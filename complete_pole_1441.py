#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
complete_pole_1441.py
=====================
Finish ZOGRASCOPE `pole` at the FULL 1441 for ALL 5 methods (consistency with the
other 12 graphs), then regenerate pole.md + ZOGRASCOPE _summary.md at 1441.

- CyANCHOR: RESUME from the 652 already in logs/pole_run/ (run only the remaining
  examples, append) — avoids redoing ~4h.
- Baselines (no_val_link/fcav/react/graphrag): run full 1441. The pole hang was a
  CONCURRENCY-contention deadlock on the single container, so heavy methods use
  SHARDS=1 (no contention → proven safe); light methods use SHARDS=4 for speed.
- Per method: raised outer timeout (no 4h cap), 300s/example, hang detection on
  record-progress stall → SKIP that method (don't blindly retry).

Outputs land in logs/pol_<method>_f1441/ then are copied into the pol_ dirs the
report generator reads; pole.md + _summary.md regenerated at 1441 at the end.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
import eval_config as cfg

POLE_HOST_PORT = 15076
DATA_PATH = cfg.ZOGRASCOPE_AUGMENTED_PATH
LOG = REPO / "logs" / "pole1441.log"
POLE_REC = REPO / "logs" / "pole_run" / "zograscope_augmented__pole.records.jsonl"
# All SHARDS=1: the pole hang was a concurrency-contention deadlock on the single
# container, and SHARDS=1 (no concurrency) is the proven-safe mode for unattended
# runs. Slower (~no parallelism) but cannot hang.
BASELINES = [("no_val_link", 1), ("fcav", 1), ("react", 1), ("graphrag", 1)]

def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"; print(line, flush=True)
    with LOG.open("a") as fh: fh.write(line + "\n")

def _conn_env():
    conn = cfg.conn_for("zograscope_augmented", "pole")
    e = dict(os.environ)
    e.update({"EVAL_NEO4J_URI": conn.uri, "EVAL_NEO4J_USER": conn.user,
              "EVAL_NEO4J_PASSWORD": conn.password, "EVAL_NEO4J_DATABASE": conn.database,
              "EVAL_PER_EXAMPLE_TIMEOUT": "300", "EVAL_WORKER_TIMEOUT_SEC": "57600"})  # 16h cap
    return e

def resume_cyanchor():
    """Run the remaining pole examples for CyANCHOR (SHARDS=1) and append to POLE_REC."""
    data = [d for d in json.load(open(DATA_PATH)) if d.get("graph") == "pole"]
    done = {json.loads(l)["qid"] for l in POLE_REC.open()} if POLE_REC.exists() else set()
    remaining = [d for d in data if d.get("id") not in done]
    log(f"CyANCHOR resume: {len(done)} done, {len(remaining)} remaining of {len(data)}")
    if not remaining:
        return
    sub = REPO / "logs" / "_pole_remaining.json"; sub.write_text(json.dumps(remaining))
    rec = REPO / "logs" / "_pole_remaining.records.jsonl"
    summ = REPO / "logs" / "_pole_remaining.summary.json"
    e = _conn_env()
    e.update({"METHOD": "cyanchor", "RETRIEVAL_FUZZY": "1", "RETRIEVAL_VECTOR": "0",
              "RETRIEVAL_LEVENSHTEIN": "1"})
    subprocess.run([sys.executable, "-m", "eval._worker", "zograscope_augmented", "pole",
                    str(sub), str(rec), str(summ)], env=e, cwd=REPO)
    if rec.exists():
        with POLE_REC.open("a") as fh:
            fh.write(rec.read_text())
    n = sum(1 for _ in POLE_REC.open())
    log(f"CyANCHOR now {n}/{len(data)} total")

def run_baseline(method, shards):
    out = REPO / "logs" / f"pol_{method}_f1441"
    if out.exists(): shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    cfg.EVAL_PAIRS = [("zograscope_augmented", "pole")]
    cfg.OUT_DIR = str(out); cfg.LIMIT = None; cfg.SHARDS = shards; cfg.VERBOSE = False
    os.environ["METHOD"] = method
    for k in ("EVAL_PER_EXAMPLE_TIMEOUT", "EVAL_WORKER_TIMEOUT_SEC"):
        os.environ[k] = _conn_env()[k]
    log(f"baseline {method} SHARDS={shards} full 1441 ...")
    import eval_run
    try:
        rc = eval_run.main()
    except Exception as exc:
        log(f"  {method} raised {exc}"); rc = 99
    f = out / "zograscope_augmented__pole.records.jsonl"
    n = sum(1 for _ in f.open()) if f.exists() else 0
    log(f"  {method} rc={rc} records={n}")
    return n

def main():
    LOG.parent.mkdir(exist_ok=True)
    log("=== complete pole @1441 start ===")
    resume_cyanchor()
    for m, sh in BASELINES:
        run_baseline(m, sh)
    # assemble 1441 dirs for the report generator
    data_n = len([d for d in json.load(open(DATA_PATH)) if d.get("graph") == "pole"])
    if POLE_REC.exists():
        (REPO / "logs" / "pol_cyanchor_fl").mkdir(exist_ok=True)
        shutil.copyfile(POLE_REC, REPO / "logs" / "pol_cyanchor_fl" / "records.jsonl")
    for m, _ in BASELINES:
        src = REPO / "logs" / f"pol_{m}_f1441" / "zograscope_augmented__pole.records.jsonl"
        if src.exists():
            shutil.copyfile(src, REPO / "logs" / f"pol_{m}" / "records.jsonl")
    import orchestrate_cyanchor as o
    o.gen_graph_report("pole", "ZOGRASCOPE", "ZOGRASCOPE", "pol_", False)
    o.gen_summary("ZOGRASCOPE", "ZOGRASCOPE", ["pol_"])
    log(f"=== pole @1441 DONE (target {data_n}); pole.md + summary regenerated ===")

if __name__ == "__main__":
    raise SystemExit(main())
