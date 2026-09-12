#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_pooled_report.py  <out> <dataset_label> <title> <dataset_key> <graph> [<graph> ...]
======================================================================================
Pool the 5-config per-graph eval records across several graphs and render ONE
flight-format report (Overall + by perturbation strategy + by difficulty, EA &
PSJS) over the pooled set — i.e. the dataset-wide categorized breakdown, not a
per-graph table.

Records are read from the canonical per-run dirs (see ``eval_paths``):
  logs/runs/<dataset_key>__<graph>__{no_val_link,fcav,react,graphrag,cyanchor_fl}/

Example (MindTheQuery, covid + 4 driver graphs):
  python gen_pooled_report.py report/<model>/MindTheQuery/_summary.md MindTheQuery \
    "Ablation — MindTheQuery (all graphs pooled)" \
    mindthequery_augmented covid er wwc healthcare bloom
"""
import json, sys, re
from pathlib import Path
import subprocess

import eval_paths

out, ds_label, title = sys.argv[1], sys.argv[2], sys.argv[3]
dataset_key = sys.argv[4]
graphs = sys.argv[5:]
tag = re.sub(r"\W+", "", ds_label.lower())

_METHODS = [
    ("No Val Link",          "—",    "no_val_link"),
    ("FCAV",                 "vector",    "fcav"),
    ("ReAct",                "fuzzy",     "react"),
    ("GraphRAG",             "norm-Lev",  "graphrag"),
    ("CyANCHOR",             "fuzzy+lev", "cyanchor_fl"),
]

methods, n = [], 0
for label, ret, cfg in _METHODS:
    pooled = Path(f"logs/_pooled_runs/{tag}_{cfg}")
    pooled.mkdir(parents=True, exist_ok=True)
    lines = []
    for g in graphs:
        d_path = eval_paths.latest_run_dir(dataset_key, g, cfg)
        rj = (d_path / "records.jsonl") if d_path else None
        if rj is not None and rj.exists():
            lines += [l for l in rj.read_text().splitlines() if l.strip()]
    (pooled / "records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))
    if lines:
        methods.append({"label": label, "retrieval": ret, "dir": str(pooled)})
        n = max(n, len(lines))

if not methods:
    print(f"gen_pooled_report: no records for prefixes {prefixes}; skipping"); sys.exit(0)

spec = {
    "title": title, "out": out, "graph": "all graphs pooled",
    "dataset": ds_label, "n_questions": n, "generated": __import__("time").strftime("%Y-%m-%d"),
    "llm": eval_paths.default_model(), "methods": methods,
}
Path(out).parent.mkdir(parents=True, exist_ok=True)
sp = Path(f"/tmp/_pooled_spec_{tag}.json"); sp.write_text(json.dumps(spec))
subprocess.run([sys.executable, "gen_ablation_report.py", str(sp)], check=True)
