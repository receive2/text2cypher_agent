#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_graph_report.py  <graph> <dataset_dir> <dataset_label> <dataset_key> [date]
============================================================================
Generate report/<dataset_dir>/<graph>.md (flight-format tables, no hand
findings) from the canonical per-run dirs
``logs/runs/<dataset_key>__<graph>__<method>/`` for the 5-config set. Thin
wrapper that builds a spec and calls gen_ablation_report.py.

``dataset_key`` is the data dataset name eval_run uses (e.g.
``cypherbench_augmented``); the run-dir locations are resolved through
``eval_paths`` — no per-graph prefix map.

Example:
  python gen_graph_report.py geography CypherBench CypherBench cypherbench_augmented 2026-06-22
"""
import json, sys, subprocess
from pathlib import Path

import eval_paths

try:
    from eval_config import REPORT_DIR
except Exception:
    REPORT_DIR = "report"

graph        = sys.argv[1]
dataset_dir  = sys.argv[2]
dataset_lab  = sys.argv[3]
dataset_key  = sys.argv[4]
date         = sys.argv[5] if len(sys.argv) > 5 else ""

_METHODS = [
    ("No Val Link",          "—",     "no_val_link"),
    ("FCAV",                 "vector",     "fcav"),
    ("ReAct (Node + Rel)",   "fuzzy",      "react"),
    ("GraphRAG",             "norm-Lev",   "graphrag"),
    ("CyANCHOR (fuzzy+lev)", "fuzzy+lev",  "cyanchor_fl"),
]

methods, n = [], 0
for label, ret, cfg in _METHODS:
    d = str(eval_paths.run_dir(dataset_key, graph, cfg))
    rj = Path(d) / "records.jsonl"
    if rj.exists():
        methods.append({"label": label, "retrieval": ret, "dir": d})
        n = max(n, sum(1 for _ in rj.open()))

if not methods:
    print(f"gen_graph_report: no records for {graph} (prefix {prefix}); skipping")
    sys.exit(0)

spec = {
    "title": f"Report — {graph} (entity-perturbed {dataset_lab})",
    "out":   f"{REPORT_DIR}/{dataset_dir}/{graph}.md",
    "graph": graph, "dataset": dataset_lab, "n_questions": n,
    "generated": date, "llm": "gpt-4.1", "methods": methods,
}
Path(REPORT_DIR, dataset_dir).mkdir(parents=True, exist_ok=True)
sp = Path(f"/tmp/_spec_{graph}.json"); sp.write_text(json.dumps(spec))
subprocess.run([sys.executable, "gen_ablation_report.py", str(sp)], check=True)
