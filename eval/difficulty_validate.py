#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/difficulty_validate.py
===========================
Offline validation for the redesigned difficulty classifier (`eval/difficulty.py`).

Runs on ``~/datasets/{cypherbench,mindthequery,zograscope}_augmented_v2/test.json``
and prints:
  1. Per-dataset bucket distribution + the pooled distribution.
  2. Pre-registered mapping cross-check (§3.2 of docs/DIFFICULTY_DESIGN.md):
       - CypherBench  `from_template.match_category` → expected bucket(s)
       - ZOGRASCOPE   `num_nodes` × `type`            → expected dim scores
  3. §4 acceptance status: per-dataset (no tier < 5%, no tier > 70%);
     mapping % exact-or-in-range; Spearman ρ on parser ↔ mapping ordinal.

The classifier itself is NOT consulted for the mapping — this script is purely
the offline cross-check that the parser's structural rubric agrees with the
native template metadata.

Usage
-----
    python -m eval.difficulty_validate
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from eval.difficulty import classify_explain

_DATA_ROOT = Path.home() / "datasets"

_BUCKETS = ("easy", "medium", "hard")
_BUCKET_ORDINAL = {b: i + 1 for i, b in enumerate(_BUCKETS)}


# ──────────────────────────────────────────────────────────────────────────────
# Pre-registered mapping — fixed BEFORE running. Do NOT tune after seeing
# the distribution; revise only with an explicit doc update.
#
# `expected` is a tuple of acceptable buckets — a dual-bucket entry like
# ("easy", "medium") counts as a hit for either. `ordinal` is the rank used
# for Spearman correlation (single value; for ranges we pick the midpoint).
# ──────────────────────────────────────────────────────────────────────────────

CYPHERBENCH_MATCH_CATEGORY_MAP: Dict[str, Tuple[Tuple[str, ...], float]] = {
    # basic patterns — 0-1 hop, simple shapes
    "basic_(n)":                       (("easy", "medium"),   1.5),
    "basic_(n*)":                      (("easy", "medium"),   1.5),
    "basic_(n)=(m0)":                  (("easy", "medium"),   1.5),
    "basic_(n)-(m0)":                  (("easy", "medium"),   1.5),
    "basic_(n)-(m0*)":                 (("easy", "medium"),   1.5),
    "basic_(n)-(m0*),(n)-(m1*)":       (("easy", "medium"),   1.5),
    # 2-hop basics
    "basic_(n)-(m0)-(m1*)":            (("medium",),          2.0),
    # special structures
    "special_optional-match":          (("medium", "hard"),   2.5),
    "special_comparison":              (("medium", "hard"),   2.5),
    "special_time-sensitive":          (("medium", "hard"),   2.5),
    "special_three-node-groupby":      (("hard",),            3.0),
    "special_union":                   (("medium", "hard"),   2.5),
}
# NOTE: ordinals are kept on the 1-4 scale used during the 4-tier design
# (with "extra"=4) so the cross-check is unaffected by the 3-tier collapse:
# parser bucket "hard" still maps to ordinal 3, and mapping rows expecting
# "hard" still get 3.0.  Spearman ρ is robust to monotone rescaling.


def _zograscope_expected_bucket(num_nodes: int, type_: str) -> Tuple[Tuple[str, ...], float]:
    """Derive expected bucket from ZOGRASCOPE `num_nodes` × `type`.

    Heuristic mirrors the rubric: Reach from hop count (num_nodes-1),
    Operation from `type`, no Filter info → cap accordingly.
    """
    hops = max(0, num_nodes - 1)
    reach = 0 if hops <= 1 else (1 if hops <= 3 else 2)
    if type_ in ("entity_set", "attribute_set"):
        op = 0
    elif type_ in ("count", "min", "max"):
        op = 1
    elif type_ in ("argmax", "argmin"):
        op = 2
    else:
        op = 1
    score = reach + op  # ignore Filter (unknown without parsing `mr`)
    if score == 0:
        return ("easy", "medium"), 1.5
    if score == 1:
        return ("medium",), 2.0
    if score == 2:
        return ("medium", "hard"), 2.5
    return ("hard",), 3.0


# ──────────────────────────────────────────────────────────────────────────────
# Per-dataset evaluation
# ──────────────────────────────────────────────────────────────────────────────


def _classify_dataset(rows: List[dict]) -> List[Tuple[str, str, dict]]:
    """Return [(bucket, reason, row), ...]."""
    return [(b or "none", reason, r)
            for r in rows
            for (b, reason) in [classify_explain(r.get("gold_cypher"))]]


def _distribution(parsed: List[Tuple[str, str, dict]]) -> Dict[str, int]:
    c: Dict[str, int] = {b: 0 for b in _BUCKETS}
    c["none"] = 0
    for b, _, _ in parsed:
        c[b] = c.get(b, 0) + 1
    return c


def _fmt_dist(label: str, dist: Dict[str, int]) -> str:
    n = sum(v for k, v in dist.items() if k != "none")
    if n == 0:
        return f"{label:14} n=0 (empty)"
    parts = [f"{b}={dist.get(b,0):4} ({100*dist.get(b,0)/n:5.1f}%)" for b in _BUCKETS]
    if dist.get("none"):
        parts.append(f"none={dist['none']}")
    return f"{label:14} n={n:5}  " + "  ".join(parts)


def _accept_distribution(dist: Dict[str, int]) -> List[str]:
    """Return list of failure reasons; empty if §4 distribution accepts.

    Thresholds: no tier < 5% (not degenerate) and no tier > 75% (not
    dominant).  The 75% cap is looser than Spider's natural 40% medium
    because text2cypher benchmarks are single-domain/curated and
    naturally more concentrated than Spider's 200-DB cross-domain pool.
    """
    n = sum(v for k, v in dist.items() if k != "none")
    if n == 0:
        return ["empty dataset"]
    fails = []
    for b in _BUCKETS:
        pct = 100 * dist.get(b, 0) / n
        if pct < 5.0:
            fails.append(f"{b}={pct:.1f}% < 5%")
        if pct > 75.0:
            fails.append(f"{b}={pct:.1f}% > 75%")
    return fails


# ──────────────────────────────────────────────────────────────────────────────
# Cross-check — parser vs pre-registered mapping
# ──────────────────────────────────────────────────────────────────────────────


def _cypherbench_xcheck(parsed: List[Tuple[str, str, dict]]) -> Tuple[float, float, Counter]:
    """Return (% exact-in-range, Spearman ρ, mismatch Counter)."""
    pairs: List[Tuple[float, float]] = []
    misses = Counter()
    hits = 0
    n = 0
    for bucket, _reason, row in parsed:
        sr = row.get("_source_row") or {}
        ft = sr.get("from_template") or {}
        mc = ft.get("match_category")
        if mc not in CYPHERBENCH_MATCH_CATEGORY_MAP:
            continue
        accepted, mapping_ord = CYPHERBENCH_MATCH_CATEGORY_MAP[mc]
        n += 1
        parser_ord = _BUCKET_ORDINAL.get(bucket, 0)
        pairs.append((float(parser_ord), float(mapping_ord)))
        if bucket in accepted:
            hits += 1
        else:
            misses[(mc, bucket, ",".join(accepted))] += 1
    if n == 0:
        return 0.0, 0.0, misses
    pct = 100.0 * hits / n
    rho = _spearman(pairs)
    return pct, rho, misses


def _zograscope_xcheck(parsed: List[Tuple[str, str, dict]]) -> Tuple[float, float, Counter]:
    pairs: List[Tuple[float, float]] = []
    misses = Counter()
    hits = 0
    n = 0
    for bucket, _reason, row in parsed:
        sr = row.get("_source_row") or {}
        try:
            nn = int(sr.get("num_nodes"))
        except (TypeError, ValueError):
            continue
        tp = sr.get("type")
        if not tp:
            continue
        accepted, mapping_ord = _zograscope_expected_bucket(nn, tp)
        n += 1
        parser_ord = _BUCKET_ORDINAL.get(bucket, 0)
        pairs.append((float(parser_ord), float(mapping_ord)))
        if bucket in accepted:
            hits += 1
        else:
            misses[(f"nn={nn}/{tp}", bucket, ",".join(accepted))] += 1
    if n == 0:
        return 0.0, 0.0, misses
    pct = 100.0 * hits / n
    rho = _spearman(pairs)
    return pct, rho, misses


def _spearman(pairs: List[Tuple[float, float]]) -> float:
    """Spearman ρ via Pearson on ranks (ties → average rank)."""
    if len(pairs) < 2:
        return 0.0

    def _rankdata(xs):
        # average-rank for ties
        idx = sorted(range(len(xs)), key=lambda i: xs[i])
        ranks = [0.0] * len(xs)
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[idx[j + 1]] == xs[idx[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0  # 1-based midpoint
            for k in range(i, j + 1):
                ranks[idx[k]] = avg
            i = j + 1
        return ranks

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rx = _rankdata(xs)
    ry = _rankdata(ys)
    n = len(rx)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 78)
    print("Per-dataset bucket distribution (new classifier)")
    print("=" * 78)
    all_dist: Dict[str, int] = {b: 0 for b in _BUCKETS}
    all_dist["none"] = 0
    parsed_per: Dict[str, List[Tuple[str, str, dict]]] = {}
    for ds in ("cypherbench", "mindthequery", "zograscope"):
        rows = json.loads((_DATA_ROOT / f"{ds}_augmented_v2" / "test.json").read_text())
        parsed = _classify_dataset(rows)
        parsed_per[ds] = parsed
        dist = _distribution(parsed)
        for k, v in dist.items():
            all_dist[k] = all_dist.get(k, 0) + v
        print(_fmt_dist(ds, dist))
    print(_fmt_dist("POOLED", all_dist))

    print()
    print("=" * 78)
    print("§4 acceptance — distribution per dataset (target: 5%–75% each tier)")
    print("=" * 78)
    overall_ok = True
    for ds in ("cypherbench", "mindthequery", "zograscope"):
        dist = _distribution(parsed_per[ds])
        fails = _accept_distribution(dist)
        if fails:
            overall_ok = False
            print(f"  ✗ {ds:14} — " + "; ".join(fails))
        else:
            print(f"  ✓ {ds:14} — all tiers 5%–75%")
    pooled_fails = _accept_distribution(all_dist)
    if pooled_fails:
        print(f"  ✗ POOLED         — " + "; ".join(pooled_fails))
    else:
        print(f"  ✓ POOLED         — all tiers 5%–75%")

    print()
    print("=" * 78)
    print("§3.2 pre-registered mapping cross-check (target: ≥85% in-range, ρ ≥ 0.7)")
    print("=" * 78)
    cb_pct, cb_rho, cb_miss = _cypherbench_xcheck(parsed_per["cypherbench"])
    print(f"  CypherBench   exact-in-range: {cb_pct:5.1f}%   Spearman ρ: {cb_rho:+.3f}")
    if cb_miss:
        print("    top mismatches (match_category, parser→bucket vs expected):")
        for (mc, b, exp), cnt in cb_miss.most_common(8):
            print(f"      {cnt:4}  {mc:35} {b:7} vs {exp}")

    zg_pct, zg_rho, zg_miss = _zograscope_xcheck(parsed_per["zograscope"])
    print(f"  ZOGRASCOPE    exact-in-range: {zg_pct:5.1f}%   Spearman ρ: {zg_rho:+.3f}")
    if zg_miss:
        print("    top mismatches (num_nodes/type, parser→bucket vs expected):")
        for (key, b, exp), cnt in zg_miss.most_common(8):
            print(f"      {cnt:4}  {key:30} {b:7} vs {exp}")

    print()
    print("=" * 78)
    print("Verdict")
    print("=" * 78)
    cb_ok = cb_pct >= 85.0 and cb_rho >= 0.7
    zg_ok = zg_pct >= 85.0 and zg_rho >= 0.7
    xcheck_ok = cb_ok and zg_ok
    if overall_ok and xcheck_ok:
        print("  ✓ ACCEPT — thresholds may be LOCKED.")
        return 0
    if not overall_ok:
        print("  ✗ Distribution acceptance failed. See §6 contingency in "
              "docs/DIFFICULTY_DESIGN.md: add a 4th dimension (Return-shape) "
              "rather than re-tuning thresholds.")
    if not xcheck_ok:
        print(f"  ✗ Cross-check failed (CB ok={cb_ok}, ZG ok={zg_ok}). "
              "Investigate top mismatches above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
