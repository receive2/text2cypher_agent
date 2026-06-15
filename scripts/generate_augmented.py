#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/generate_augmented.py
=============================
Generate the redesigned augmented dataset to a STAGING location and emit a
per-graph report + a human-verification queue.  Does NOT touch the live
``*_augmented`` dirs — writes to ``~/datasets/<dataset>_augmented_v2/`` so the
output can be reviewed before any swap.

Generation only READS the graph DB (distinct value sets for validity); it never
writes to the VM.  Requires the corporate VPN OFF (DB reachable) and, with
``--llm``, proxy-bypass for OpenAI::

    export OPENAI_API_KEY=$(grep '^OPENAI_API_KEY=' .env | cut -d= -f2- | tr -d '"')
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
        python -m scripts.generate_augmented cypherbench nba flight_accident --llm

Handles all three dataset formats (graph name = the dataset's own naming):
  * cypherbench   — ~/datasets/cypherbench/<split>.json, rows carry ``graph``.
  * mindthequery  — ~/datasets/mindthequery/Train_Test_Splits/Manual/<graph>/test/*_test.json
  * zograscope    — ~/datasets/zograscope/data/zograscope_<split>_v1.csv  (graph=pole)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator, Tuple

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data_augmentation import config as C                       # noqa: E402
from data_augmentation.llm import LLMClient                      # noqa: E402
from data_augmentation.pipeline import QuotaSampler, augment_nl, row_rng  # noqa: E402
from data_augmentation.providers import build_providers, close_all        # noqa: E402

try:
    csv.field_size_limit(2**24)
except OverflowError:
    csv.field_size_limit(2**20)

# Dataset graph name → eval_config.GRAPH_CONNS key, when they differ.
_CONN_ALIAS = {("mindthequery", "bloom"): "bloom50"}

_CB_NL = ("nl_question", "question", "nl")
_CB_CY = ("gold_cypher", "cypher", "target_cypher")
_MTQ_NL = ("NL Question", "nl_question", "question", "nl")
_MTQ_CY = ("Cypher", "cypher", "gold_cypher")


def _first(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k):
            return d[k]
    return None


def iter_rows(dataset: str, graph: str, split: str, limit) -> Iterator[Tuple[object, str, str, dict]]:
    """Yield (row_id, nl, gold_cypher, source_row) for one (dataset, graph, split)."""
    home = Path(os.path.expanduser("~/datasets"))
    n = 0
    if dataset == "cypherbench":
        data = json.load(open(home / "cypherbench" / f"{split}.json", encoding="utf-8"))
        for r in data:
            if isinstance(r, dict) and r.get("graph") == graph:
                nl, cy = _first(r, _CB_NL), _first(r, _CB_CY)
                if nl and cy:
                    yield (r.get("qid", n), str(nl), str(cy), r); n += 1
                    if limit and n >= limit:
                        return
    elif dataset == "mindthequery":
        base = home / "mindthequery" / "Train_Test_Splits" / "Manual" / graph / split
        for f in sorted(base.glob("*.json")):
            try:
                data = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for i, r in enumerate(data):
                nl, cy = _first(r, _MTQ_NL), _first(r, _MTQ_CY)
                if nl and cy:
                    yield (f"{f.stem}:{i}", str(nl), str(cy), r); n += 1
                    if limit and n >= limit:
                        return
    elif dataset == "zograscope":
        f = home / "zograscope" / "data" / f"zograscope_{split}_v1.csv"
        with open(f, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                nl, cy = (r.get("nl") or "").strip(), (r.get("mr") or "").strip()
                if nl and cy:
                    yield (r.get("id", n), nl, cy, r); n += 1
                    if limit and n >= limit:
                        return
    else:
        raise SystemExit(f"unknown dataset {dataset!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("graphs", nargs="+")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    args = ap.parse_args()

    out_dir = Path(os.path.expanduser(args.out or f"~/datasets/{args.dataset}_augmented_v2"))
    out_dir.mkdir(parents=True, exist_ok=True)
    llm = LLMClient(C.DEFAULT_LLM_CONFIG) if args.llm else LLMClient(None)

    out_rows, verify_q, report = [], [], {}
    for graph in args.graphs:
        rows = list(iter_rows(args.dataset, graph, args.split, args.limit))
        if not rows:
            print(f"[gen] {graph}: no rows", file=sys.stderr); continue
        conn_graph = _CONN_ALIAS.get((args.dataset, graph))
        values, aliases = build_providers(args.dataset, graph, conn_graph=conn_graph)
        sampler = QuotaSampler(C.PROPORTIONS)
        stats: Counter = Counter()
        kept = 0
        for (rid, nl, gold, src) in rows:
            res = augment_nl(nl, gold, proportions=C.PROPORTIONS, llm=llm,
                             use_llm_entity_fallback=args.llm,
                             rng=row_rng(args.seed, args.dataset, rid),
                             graph=graph, values=values, aliases=aliases,
                             sampler=sampler, stats=stats)
            if res is None:
                continue
            new_nl, meta = res
            out_rows.append({"dataset": args.dataset, "graph": graph, "id": rid,
                             "nl": new_nl, "gold_cypher": gold,
                             "_aug_meta": meta, "_source_row": src})
            kept += 1
            e = meta["edits"][0]
            if e.get("needs_verification"):
                verify_q.append({"graph": graph, "qid": rid, "strategy": e["strategy"],
                                 "from": e["from"], "to": e["to"], "source": e["source"],
                                 "nl": new_nl})
        report[graph] = {
            "rows": len(rows), "kept": kept,
            "realized_pct": {s: round(sampler.counts[s] / sampler.total * 100, 1)
                             if sampler.total else 0 for s in C.PROPORTIONS},
            "reasons": dict(stats),
            "needs_verification": sum(1 for v in verify_q if v["graph"] == graph),
        }
        print(f"[gen] {graph}: kept={kept}/{len(rows)}  "
              f"dist={report[graph]['realized_pct']}  verify={report[graph]['needs_verification']}")

    close_all()
    (out_dir / f"{args.split}.json").write_text(
        json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "needs_verification.jsonl").open("w", encoding="utf-8") as fh:
        for v in verify_q:
            fh.write(json.dumps(v, ensure_ascii=False) + "\n")
    print(f"\n[gen] {len(out_rows)} rows → {out_dir}/{args.split}.json | "
          f"report.json | needs_verification.jsonl ({len(verify_q)} edits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
