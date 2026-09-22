#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/gold_executability.py
=============================
How many released gold queries fail to execute, per graph — the number the
datasheet reports under "known limitations".

Two ways to produce it; both write ``audit/gold_executability.json``:

    python scripts/gold_executability.py                    # execute every released gold against the graphs
    python scripts/gold_executability.py --from-runs gpt-5.6-terra
                                                            # read the harness's own gold verdicts out of a
                                                            # full run (records whose error starts with "gold:")

The live mode uses the harness's execution path (``neo4j_lib.safe_query``,
30 s server-side timeout) so the count matches what evaluation reports. The
``--from-runs`` mode needs no database: any complete ``no_val_link`` run over
the released rows carries the same verdict per question.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import eval_config as cfg  # noqa: E402

OUT = REPO / "audit" / "gold_executability.json"
DATASETS = ("cypherbench", "mindthequery", "zograscope")
CLEAN_GRAPH = {"bloom": "bloom50"}
TIMEOUT_SEC = 30.0


def _version() -> str:
    import re
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', (REPO / "benchmarks" / "verify.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def _released_rows():
    for ds in DATASETS:
        for r in json.load(open(REPO / "benchmarks" / f"{ds}_augmented_v2" / "test.json", encoding="utf-8")):
            yield ds, r["graph"], str(r["id"]), r["gold_cypher"]


def from_runs(model: str) -> dict:
    graphs = []
    for (ds, g), _ in [(k, v) for k, v in cfg.GRAPH_CONNS.items() if k[0].endswith("_augmented")]:
        pass
    by_graph: dict = {}
    for ds, g, qid, _ in _released_rows():
        by_graph.setdefault((ds, g), set()).add(qid)
    for (ds, g), qids in sorted(by_graph.items()):
        hits = sorted(glob.glob(str(REPO / "logs" / "runs" / f"{ds}_augmented__{g}__no_val_link@{model}__*")))
        recs = {}
        for h in hits:
            f = Path(h) / "records.jsonl"
            if f.is_file():
                rs = [r for r in (json.loads(l) for l in f.open(encoding="utf-8") if l.strip())
                      if str(r["qid"]) in qids]                     # rows removed since the run are ignored
                if len(rs) == len(qids):
                    recs = {str(r["qid"]): r for r in rs}
        if not recs:
            raise SystemExit(f"no complete no_val_link@{model} run for {ds}/{g} under logs/runs")
        errs = Counter()
        for qid in qids:
            e = str(recs[qid].get("error") or "")
            if e.startswith("gold:"):
                errs["timeout" if "timeout" in e.lower() else "error"] += 1
        graphs.append({"dataset": ds, "graph": g, "n": len(qids),
                       "gold_error": errs["error"], "gold_timeout": errs["timeout"]})
    return {"version": _version(), "method": f"gold verdicts recorded by the evaluation harness in a complete "
                                            f"run over the released rows, {TIMEOUT_SEC:.0f} s server-side timeout",
            "date": time.strftime("%Y-%m-%d"), "graphs": graphs}


def live() -> dict:
    from neo4j import GraphDatabase
    from neo4j_lib.safe_query import safe_cypher_run, TransactionTimedOutError
    by_graph: dict = {}
    for ds, g, qid, gold in _released_rows():
        by_graph.setdefault((ds, g), []).append(gold)
    graphs = []
    for (ds, g), golds in sorted(by_graph.items()):
        conn = cfg.conn_for(ds, CLEAN_GRAPH.get(g, g))
        drv = GraphDatabase.driver(conn.uri, auth=(conn.user, conn.password))
        errs = Counter(); empty = 0
        try:
            for q in golds:
                try:
                    rows = safe_cypher_run(drv, q, params=None, timeout=TIMEOUT_SEC, database=conn.database)
                    if not rows:
                        empty += 1
                except TransactionTimedOutError:
                    errs["timeout"] += 1
                except Exception:  # noqa: BLE001 — any execution failure is a gold error
                    errs["error"] += 1
        finally:
            drv.close()
        graphs.append({"dataset": ds, "graph": g, "n": len(golds), "gold_error": errs["error"],
                       "gold_timeout": errs["timeout"], "gold_empty": empty})
        print(f"  {ds}/{g}: n={len(golds)} error={errs['error']} timeout={errs['timeout']} empty={empty}", flush=True)
    return {"version": _version(), "method": f"every released gold executed against the deployed graphs, "
                                            f"{TIMEOUT_SEC:.0f} s server-side timeout",
            "date": time.strftime("%Y-%m-%d"), "graphs": graphs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-runs", metavar="MODEL", help="derive from a complete no_val_link run of this model instead of executing")
    args = ap.parse_args(argv)
    data = from_runs(args.from_runs) if args.from_runs else live()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tot = sum(g["gold_error"] + g["gold_timeout"] for g in data["graphs"])
    print(f"[gold_executability] {tot} non-executing golds on {data['version']} → {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
