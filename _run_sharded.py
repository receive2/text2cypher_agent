#!/usr/bin/env python3
"""Cross-question parallel eval via PROCESS SHARDING (safe: each shard = own
process with its own SIGALRM watchdog; mode-agnostic — works for any VAL_LINK_MODE).

Env:
  SHARD_OUT   = output dir (merged records -> <dir>/cypherbench_augmented__movie.records.jsonl)
  SHARDS      = number of parallel shard processes (default 4)
  SHARD_LIMIT = first-N movie examples to run (default 100)
  plus the usual VAL_LINK_MODE / AGENT_TYPE / ... (inherited by each worker)
"""
import sys, os, json, subprocess
from pathlib import Path
import eval_config as cfg
from eval.artifact_swap import swap_in

DATASET, GRAPH = "cypherbench_augmented", "movie"
K     = int(os.environ.get("SHARDS", "4"))
LIMIT = int(os.environ.get("SHARD_LIMIT", "100"))
OUT   = os.environ["SHARD_OUT"]
Path(OUT).mkdir(parents=True, exist_ok=True)

swap_in(DATASET, GRAPH)                      # artifacts into live tree (once)
conn = cfg.conn_for(DATASET, GRAPH)

data = [d for d in json.load(open(cfg.CYPHERBENCH_AUGMENTED_PATH))
        if d.get("graph") == GRAPH][:LIMIT]
print(f"[sharded] {len(data)} movie examples -> {K} shards", flush=True)

env = dict(os.environ)
env["EVAL_NEO4J_URI"]      = conn.uri
env["EVAL_NEO4J_USER"]     = conn.user
env["EVAL_NEO4J_PASSWORD"] = conn.password
env["EVAL_NEO4J_DATABASE"] = conn.database

procs, shard_recs = [], []
for k in range(K):
    sub = data[k::K]                          # stride shard (deterministic)
    sp  = f"{OUT}/shard_{k}.json"
    json.dump(sub, open(sp, "w"), ensure_ascii=False)
    rec = f"{OUT}/shard_{k}.records.jsonl"; summ = f"{OUT}/shard_{k}.summary.json"
    shard_recs.append(rec)
    procs.append(subprocess.Popen(
        [sys.executable, "-m", "eval._worker", DATASET, GRAPH, sp, rec, summ],
        env=env))
for p in procs:
    p.wait()

merged = []
for rec in shard_recs:
    if os.path.exists(rec):
        merged += open(rec).readlines()
out_path = f"{OUT}/cypherbench_augmented__movie.records.jsonl"
open(out_path, "w").writelines(merged)
print(f"[sharded] merged {len(merged)} records -> {out_path}", flush=True)
