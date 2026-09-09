#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_applicability_ceiling.py
================================
Measure the **applicability ceiling** per (graph, strategy): what fraction of
rows have an entity that *admits* a legal abbrev / alias at all?  Answers the
reviewer question "is the typo share a supply ceiling or an allocation
artifact" with numbers (see audit/APPLICABILITY_CEILING.md).

Three phases:

  attested   (default)  Exact, free: scan every row's entity against the
                        per-graph AliasProvider (curated + simplekg [+RxNorm]).
                        -> audit/ceiling_attested.jsonl
  --probe    Stratified row sample; ask claude-opus-5 (abstention-first) for an
             attested abbrev AND alias in one call. Cached per (graph, entity),
             resume-safe. -> audit/ceiling_probe.jsonl
  --report   Combine into the per-graph ceiling table (Wilson CIs on probe
             rates; LLM supply discounted by the A/B-measured ~85% precision).
             -> audit/APPLICABILITY_CEILING.md

Ceiling definition (per strategy s, per graph):
  ceil_s = share(rows already s) + share(not-s rows with an attested s-form)
           + PRECISION * share(not-s rows, no attested form, where the LLM
             proposes one)
Alias on synthetic graphs (pole/er/bloom) is 0 by design policy.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_REPO / ".env")

import eval_config as cfg  # noqa: E402
from data_augmentation.config import SYNTHETIC_GRAPHS  # noqa: E402
from data_augmentation.kb_aliases import AliasProvider  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
ATTESTED = _REPO / "audit" / "ceiling_attested.jsonl"
PROBE = _REPO / "audit" / "ceiling_probe.jsonl"
REPORT = _REPO / "audit" / "APPLICABILITY_CEILING.md"
PRECISION = 0.85          # opus-5 proposal precision, from audit/llm_proposer_ab_results.md
SEED = 42

SYSTEM = (
    "You help build a benchmark of realistic entity mentions. Given an entity "
    "from a knowledge graph, report whether a REAL, attested (a) abbreviation/"
    "short form and (b) nickname/colloquial alternative name exist that people "
    "actually use for EXACTLY this entity.\n"
    "Rules: never invent, translate, or embellish; most obscure entities have "
    "neither — null is then the correct answer; a form must be unambiguous.\n"
    'Output strict JSON only: {"abbrev": "..." or null, "alias": "..." or null, '
    '"evidence": "one short sentence"}'
)


def _rows():
    for ds, path in _DATASETS.items():
        for i, x in enumerate(json.load(open(path, encoding="utf-8"))):
            m = x.get("_aug_meta") or {}
            e = (m.get("edits") or [{}])[0]
            if e.get("from"):
                yield {"row_id": f"{ds}:{i}", "dataset": ds,
                       "graph": m.get("graph", ""), "strategy": e.get("strategy"),
                       "entity": e["from"]}


def attested() -> int:
    providers: dict = {}
    out = []
    for r in _rows():
        g = r["graph"]
        if g not in providers:
            providers[g] = AliasProvider(graph=g)
        p = providers[g]
        r["attested_abbrev"] = bool(p.abbrevs(r["entity"]))
        r["attested_alias"] = bool(p.aliases(r["entity"]))
        out.append(r)
    with open(ATTESTED, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    c = Counter()
    for r in out:
        c[(r["graph"], "abbrev")] += r["attested_abbrev"]
        c[(r["graph"], "alias")] += r["attested_alias"]
        c[(r["graph"], "_n")] += 1
    print(f"attested scan: {len(out)} rows -> {ATTESTED}")
    for g in sorted({k[0] for k in c}):
        n = c[(g, "_n")]
        print(f"  {g:20s} n={n:5d}  attested_abbrev={c[(g,'abbrev')]:4d} "
              f"({100*c[(g,'abbrev')]/n:4.1f}%)  attested_alias={c[(g,'alias')]:4d} "
              f"({100*c[(g,'alias')]/n:4.1f}%)")
    return 0


def probe(sample_per_graph: int, workers: int) -> int:
    import anthropic
    rows = [json.loads(l) for l in open(ATTESTED, encoding="utf-8")]
    done = set()
    if PROBE.exists():
        for l in open(PROBE, encoding="utf-8"):
            done.add(json.loads(l)["key"])
    # sample rows lacking BOTH attested forms (the unknown-supply pool),
    # stratified per graph, all current strategies included
    rng = random.Random(SEED)
    by_g = defaultdict(list)
    for r in rows:
        if not (r["attested_abbrev"] or r["attested_alias"]):
            by_g[r["graph"]].append(r)
    todo, keys = [], set()
    for g, pool in sorted(by_g.items()):
        pool.sort(key=lambda r: r["row_id"])
        for r in rng.sample(pool, min(sample_per_graph, len(pool))):
            k = f"{g}|{r['entity']}"
            if k in done or k in keys:
                continue
            keys.add(k)
            todo.append((k, g, r["entity"]))
    print(f"probe: {len(todo)} unique (graph, entity) calls "
          f"(cached: {len(done)})")
    client = anthropic.Anthropic()
    lock = threading.Lock()

    def one(item):
        k, g, ent = item
        rec = {"key": k, "graph": g, "entity": ent}
        prompt = f"Entity: {ent}\nDomain: a '{g}' knowledge graph\nJSON:"
        try:
            resp = client.messages.create(model="claude-opus-5", max_tokens=900,
                                          system=SYSTEM,
                                          messages=[{"role": "user", "content": prompt}])
            out = "".join(b.text for b in resp.content if b.type == "text")
            m = re.search(r"\{.*\}", out, re.DOTALL)
            d = json.loads(m.group(0)) if m else {}
            def norm(v):
                v = (v or "") if not isinstance(v, (list, dict)) else ""
                v = str(v).strip()
                return None if v.lower() in ("", "none", "null") else v
            rec["abbrev"] = norm(d.get("abbrev"))
            rec["alias"] = norm(d.get("alias"))
            rec["evidence"] = str(d.get("evidence") or "")[:200]
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)[:120]
        with lock:
            with open(PROBE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return "ok"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    print("probe done")
    return 0


def _wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h


def report() -> int:
    rows = [json.loads(l) for l in open(ATTESTED, encoding="utf-8")]
    probes = {}
    if PROBE.exists():
        for l in open(PROBE, encoding="utf-8"):
            r = json.loads(l)
            if "error" not in r:
                probes[r["key"]] = r
    by_g = defaultdict(list)
    for r in rows:
        by_g[r["graph"]].append(r)

    lines = ["# Applicability ceiling — per graph × strategy (2026-08)",
             "",
             f"Attested = exact full scan (kb curated + simplekg). LLM supply = "
             f"opus-5 abstention probe on rows lacking any attested form, "
             f"discounted by the A/B-measured proposal precision "
             f"({PRECISION:.0%}). Alias on synthetic graphs is 0 by design.",
             "",
             "| graph | rows | now:abbrev | attested abbrev | probe abbrev [CI] | **ceil abbrev** | now:alias | attested alias | probe alias [CI] | **ceil alias** |",
             "|---|--:|--:|--:|---|--:|--:|--:|---|--:|"]
    print(f"{'graph':20s} {'rows':>5s}  {'ceil_abbrev':>11s}  {'ceil_alias':>10s}   (now: abbrev / alias)")
    tot = {"n": 0, "ca": 0.0, "cl": 0.0, "na": 0, "nl": 0}
    for g in sorted(by_g):
        rs = by_g[g]
        n = len(rs)
        syn = g in SYNTHETIC_GRAPHS
        out = {}
        for kind in ("abbrev", "alias"):
            now = sum(1 for r in rs if r["strategy"] == kind)
            att = sum(1 for r in rs if r["strategy"] != kind and r[f"attested_{kind}"])
            pool = [r for r in rs if r["strategy"] != kind
                    and not (r["attested_abbrev"] or r["attested_alias"])]
            probed = [probes.get(f"{g}|{r['entity']}") for r in pool]
            probed = [p for p in probed if p is not None]
            hits = sum(1 for p in probed if p.get(kind))
            p_rate, lo, hi = _wilson(hits, len(probed))
            llm_share = PRECISION * p_rate * (len(pool) / n) if n else 0
            ceil = (now + att) / n + llm_share if n else 0
            if kind == "alias" and syn:
                ceil = now / n   # policy: no aliases for fabricated entities
                p_rate = lo = hi = 0.0
                att = 0
            out[kind] = (now, att, p_rate, lo, hi, len(probed), ceil)
        (na, aa, pa, loa, hia, nna, ca) = out["abbrev"]
        (nl, al, pl, lol, hil, nnl, cl) = out["alias"]
        syn_tag = " *(syn)*" if syn else ""
        lines.append(
            f"| {g}{syn_tag} | {n} | {100*na/n:.1f}% | {100*aa/n:.1f}% | "
            f"{100*pa:.0f}% [{100*loa:.0f},{100*hia:.0f}] n={nna} | **{100*ca:.1f}%** | "
            f"{100*nl/n:.1f}% | {100*al/n:.1f}% | "
            f"{100*pl:.0f}% [{100*lol:.0f},{100*hil:.0f}] n={nnl} | **{100*cl:.1f}%** |")
        print(f"{g:20s} {n:5d}  {100*ca:10.1f}%  {100*cl:9.1f}%   "
              f"(now: {100*na/n:.1f}% / {100*nl/n:.1f}%)")
        tot["n"] += n
        tot["ca"] += ca * n
        tot["cl"] += cl * n
        tot["na"] += na
        tot["nl"] += nl
    N = tot["n"]
    lines.append(f"| **ALL** | {N} | {100*tot['na']/N:.1f}% | | | "
                 f"**{100*tot['ca']/N:.1f}%** | {100*tot['nl']/N:.1f}% | | | "
                 f"**{100*tot['cl']/N:.1f}%** |")
    print(f"{'ALL':20s} {N:5d}  {100*tot['ca']/N:10.1f}%  {100*tot['cl']/N:9.1f}%   "
          f"(now: {100*tot['na']/N:.1f}% / {100*tot['nl']/N:.1f}%)")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwritten: {REPORT}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--sample-per-graph", type=int, default=60)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    if args.probe:
        return probe(args.sample_per_graph, args.workers)
    if args.report:
        return report()
    return attested()


if __name__ == "__main__":
    raise SystemExit(main())
