#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/stage_augment.py
========================
Staging runner for the redesigned augmentation: run the REAL pipeline over N
rows of one (dataset, graph) against the LIVE graph DB, and print the realized
strategy distribution, drop reasons, and sample edits — WITHOUT writing any
dataset.  This is the Phase-3 preview used to eyeball quality before scaling.

Requires the corporate VPN DISCONNECTED to reach the VM (see env-vpn-proxy).

Usage::

    python -m scripts.stage_augment cypherbench nba --limit 200
    python -m scripts.stage_augment cypherbench nba --limit 200 --llm   # enable gpt-4.1 proposer
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data_augmentation import config as C           # noqa: E402
from data_augmentation.llm import LLMClient          # noqa: E402
from data_augmentation.pipeline import QuotaSampler, augment_nl, row_rng  # noqa: E402
from data_augmentation.providers import build_providers, close_all        # noqa: E402

_NL_KEYS = ("nl_question", "question", "natural_language_question", "nl")
_CY_KEYS = ("gold_cypher", "cypher", "target_cypher", "ground_truth_cypher")


def _first(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k):
            return d[k]
    return None


def _load_rows(dataset, graph, limit):
    src = Path(os.path.expanduser(f"~/datasets/{dataset}/test.json"))
    data = json.load(open(src, encoding="utf-8"))
    rows = [r for r in data if isinstance(r, dict) and r.get("graph", graph) == graph]
    out = []
    for r in rows:
        nl, cy = _first(r, _NL_KEYS), _first(r, _CY_KEYS)
        if nl and cy:
            out.append((r.get("qid", len(out)), str(nl), str(cy)))
        if limit and len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("graph")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--llm", action="store_true", help="enable the gpt-4.1 proposer")
    ap.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    ap.add_argument("--samples", type=int, default=12)
    args = ap.parse_args()

    rows = _load_rows(args.dataset, args.graph, args.limit)
    print(f"[stage] {args.dataset}/{args.graph}: {len(rows)} rows  "
          f"(llm={'on' if args.llm else 'off'})")

    values, aliases = build_providers(args.dataset, args.graph)
    llm = LLMClient(C.DEFAULT_LLM_CONFIG) if args.llm else LLMClient(None)
    sampler = QuotaSampler(C.PROPORTIONS)
    stats: Counter = Counter()
    samples = []

    kept = 0
    for (rid, nl, gold) in rows:
        rng = row_rng(args.seed, args.dataset, rid)
        res = augment_nl(nl, gold, proportions=C.PROPORTIONS, llm=llm,
                         use_llm_entity_fallback=args.llm, rng=rng,
                         graph=args.graph, values=values, aliases=aliases,
                         sampler=sampler, stats=stats)
        if res is None:
            continue
        kept += 1
        new_nl, meta = res
        if len(samples) < args.samples:
            e = meta["edits"][0]
            samples.append((e["strategy"], e["source"], e["from"], e["to"], new_nl))

    close_all()

    # ── report ──────────────────────────────────────────────────────────────
    print(f"\n== realized distribution ({kept} augmented / {len(rows)} rows) ==")
    print(f"  {'strategy':9s}{'target':>8}{'realized':>10}{'count':>7}")
    for s in C.PROPORTIONS:
        c = sampler.counts[s]
        realized = (c / sampler.total * 100) if sampler.total else 0
        print(f"  {s:9s}{C.PROPORTIONS[s]*100:>7.1f}%{realized:>9.1f}%{c:>7}")

    drops = {k: v for k, v in stats.items() if k.startswith("drop:") or k.split(":")[-1] in
             ("collision", "not_unique", "margin", "splice_failed")}
    if drops:
        print("\n== drop / reject reasons ==")
        for k, v in sorted(drops.items(), key=lambda x: -x[1]):
            print(f"  {k:28s} {v}")

    print("\n== sample edits ==")
    for strat, src, frm, to, new_nl in samples:
        print(f"  [{strat}/{src}] {frm!r} → {to!r}")
        print(f"     {new_nl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
