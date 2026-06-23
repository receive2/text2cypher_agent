#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_pooled_report.py  <out> <dataset_label> <title> <dir_prefix> [<dir_prefix> ...]
==================================================================================
Pool the 5-config per-graph eval records across several graphs and render ONE
flight-format report (Overall + by perturbation strategy + by difficulty, EA &
PSJS) over the pooled set — i.e. the dataset-wide categorized breakdown, not a
per-graph table.

Each <dir_prefix> is a graph's log-dir prefix; the 5 configs are appended:
  <prefix>{no_val_link,fcav,react,graphrag,cyanchor_fl}

Example (MindTheQuery, covid + 4 driver graphs):
  python gen_pooled_report.py report/MindTheQuery/_summary.md MindTheQuery \
    "Ablation — MindTheQuery (all graphs pooled)" \
    cov_full_ mtq_er_ mtq_wwc_ mtq_healthcare_ mtq_bloom_
"""
import json, sys, re
from pathlib import Path
import subprocess

out, ds_label, title = sys.argv[1], sys.argv[2], sys.argv[3]
prefixes = sys.argv[4:]
tag = re.sub(r"\W+", "", ds_label.lower())

_METHODS = [
    ("No Val Link",          "—",    "no_val_link"),
    ("FCAV",                 "vector",    "fcav"),
    ("ReAct (Node + Rel)",   "fuzzy",     "react"),
    ("GraphRAG",             "norm-Lev",  "graphrag"),
    ("CyANCHOR (fuzzy+lev)", "fuzzy+lev", "cyanchor_fl"),
]

methods, n = [], 0
for label, ret, cfg in _METHODS:
    pooled = Path(f"logs/_pooled_{tag}_{cfg}")
    pooled.mkdir(parents=True, exist_ok=True)
    lines = []
    for p in prefixes:
        rj = Path(f"logs/{p}{cfg}/records.jsonl")
        if rj.exists():
            lines += [l for l in rj.read_text().splitlines() if l.strip()]
    (pooled / "records.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))
    if lines:
        methods.append({"label": label, "retrieval": ret, "dir": str(pooled)})
        n = max(n, len(lines))

if not methods:
    print(f"gen_pooled_report: no records for prefixes {prefixes}; skipping"); sys.exit(0)

spec = {
    "title": title, "out": out, "graph": "all graphs pooled",
    "dataset": ds_label, "n_questions": n, "generated": "2026-06-22",
    "llm": "gpt-4.1", "methods": methods,
}
Path(out).parent.mkdir(parents=True, exist_ok=True)
sp = Path(f"/tmp/_pooled_spec_{tag}.json"); sp.write_text(json.dumps(spec))
subprocess.run([sys.executable, "gen_ablation_report.py", str(sp)], check=True)
