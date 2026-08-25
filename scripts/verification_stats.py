#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verification_stats.py
=====================
Compute the human-verification report from the filled annotator CSVs, per
docs/VERIFICATION_PROTOCOL.md. Pure-Python (no external deps).

Outputs, on the **validity** label, stratified by strategy / provenance /
dataset and overall:
  * Inter-annotator agreement — Krippendorff's alpha (nominal) + pairwise
    Cohen's kappa.
  * Validity rate (and corruption = 1 - validity) with Wilson 95% CIs.
  * Disagreement rate and the count still pending adjudication.
  * Final retained N (valid items, after dropping invalid / source-error).

Final per-item label:
  adjudicated value if provided (--adjudicated id,validity), else the agreed
  value when all raters concur, else "pending" (needs adjudication). An item is
  excluded as `source_error` if any rater flagged it.

Usage
-----
    python scripts/verification_stats.py \
        --key verification/verification_key.csv \
        --annotations verification/verification_annotator_*.csv \
        [--adjudicated verification/adjudicated.csv] \
        --out verification/report.md
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_VALID_CATS = {"valid", "invalid", "unsure"}


# ── statistics (pure python) ──────────────────────────────────────────────────

def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float, float]:
    """Return (p_hat, lo, hi) Wilson score interval for a binomial proportion."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def cohen_kappa(pairs: List[Tuple[str, str]]) -> Optional[float]:
    """Cohen's kappa over a list of (rater_a_label, rater_b_label) on co-rated items."""
    n = len(pairs)
    if n == 0:
        return None
    cats = sorted({c for ab in pairs for c in ab})
    po = sum(1 for a, b in pairs if a == b) / n
    pa = {c: sum(1 for a, _ in pairs if a == c) / n for c in cats}
    pb = {c: sum(1 for _, b in pairs if b == c) / n for c in cats}
    pe = sum(pa[c] * pb[c] for c in cats)
    return 1.0 if pe >= 1.0 else (po - pe) / (1 - pe)


def gwet_ac1(ratings_by_item: Dict[str, Dict[str, str]],
             categories: Optional[List[str]] = None) -> Optional[float]:
    """Gwet's AC1 (nominal) — a chance-corrected agreement coefficient that,
    unlike kappa/alpha, stays stable when one label dominates.

    Alpha/kappa estimate chance agreement from the observed marginals, so in a
    stratum where ~98% of items share a label the chance term approaches the
    observed agreement and the coefficient collapses toward zero (the
    "kappa paradox": high agreement, near-zero kappa). AC1 instead estimates
    chance agreement as the probability that a rater assigns a category *at
    random* among the categories in play, which does not degenerate under high
    prevalence.

    Formula (Gwet 2008), r raters per item, K categories:
        p_a = mean_i  sum_k r_ik(r_ik - 1) / (r_i(r_i - 1))
        pi_k = mean_i r_ik / r_i
        p_e = 1/(K-1) * sum_k pi_k(1 - pi_k)
        AC1 = (p_a - p_e) / (1 - p_e)

    **Caveat (report alongside alpha, never instead of it).** AC1's chance
    model assumes raters guess only on genuinely ambiguous items, so it is
    permissive in the opposite direction: annotators guessing at random on a
    high-prevalence stratum still score high (empirically ~0.94 on simulated
    random labels at 97% prevalence, where alpha correctly reports ~0). Alpha
    and AC1 therefore bracket reliability from below and above; neither alone
    is sufficient, and evidence that annotators were *engaged* must come from
    the strata where labels genuinely vary (there alpha is well-behaved) and
    from the calibration round.

    Items rated by fewer than 2 annotators are skipped. Returns None when
    fewer than two categories are in play or no item has >= 2 ratings.
    """
    items = [d for d in ratings_by_item.values() if len(d) >= 2]
    if not items:
        return None
    cats = list(categories) if categories else sorted(
        {v for d in items for v in d.values()})
    K = len(cats)
    if K < 2:
        return None
    n = len(items)
    p_a = 0.0
    pi = {c: 0.0 for c in cats}
    for d in items:
        labels = list(d.values())
        r_i = len(labels)
        for c in cats:
            r_ik = labels.count(c)
            p_a += r_ik * (r_ik - 1) / (r_i * (r_i - 1))
            pi[c] += r_ik / r_i
    p_a /= n
    for c in cats:
        pi[c] /= n
    p_e = sum(pi[c] * (1 - pi[c]) for c in cats) / (K - 1)
    if p_e >= 1:
        return None
    return (p_a - p_e) / (1 - p_e)


def krippendorff_alpha_nominal(ratings_by_item: Dict[str, Dict[str, str]]) -> Optional[float]:
    """
    Nominal Krippendorff's alpha over items with >=2 ratings.
    ``ratings_by_item[item] = {annotator: label}``.
    """
    units = [list(d.values()) for d in ratings_by_item.values() if len(d) >= 2]
    if not units:
        return None
    cats = sorted({v for u in units for v in u})
    idx = {c: i for i, c in enumerate(cats)}
    K = len(cats)
    o = [[0.0] * K for _ in range(K)]          # coincidence matrix
    for u in units:
        m = len(u)
        if m < 2:
            continue
        w = 1.0 / (m - 1)
        for i in range(m):
            for j in range(m):
                if i != j:
                    o[idx[u[i]]][idx[u[j]]] += w
    n_c = [sum(row) for row in o]
    n = sum(n_c)
    if n <= 1:
        return None
    trace = sum(o[c][c] for c in range(K))
    do_sum = n - trace                          # Σ_{c≠k} o_ck
    de_sum = n * n - sum(x * x for x in n_c)     # Σ_{c≠k} n_c n_k
    if de_sum == 0:
        return 1.0
    return 1.0 - (n - 1) * do_sum / de_sum


# ── IO ────────────────────────────────────────────────────────────────────────

def _annotator_name(path: str) -> str:
    m = re.search(r"annotator[_-]?([A-Za-z0-9]+)", os.path.basename(path))
    return m.group(1) if m else Path(path).stem


def _read_key(path: str) -> Dict[str, Dict[str, str]]:
    return {r["id"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def _norm(v: str) -> str:
    return (v or "").strip().lower()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", required=True)
    ap.add_argument("--annotations", nargs="+", required=True,
                    help="filled annotator CSVs (globs allowed)")
    ap.add_argument("--adjudicated", default=None, help="optional id,validity CSV")
    ap.add_argument("--out", default=None, help="write the markdown report here (else stdout)")
    args = ap.parse_args(argv)

    key = _read_key(args.key)
    files: List[str] = []
    for patt in args.annotations:
        files.extend(sorted(glob.glob(patt)) or [patt])

    # ratings[id][annotator] = validity ; plus naturalness / source_error flags
    val: Dict[str, Dict[str, str]] = defaultdict(dict)
    src_err: Dict[str, bool] = defaultdict(bool)
    for f in files:
        ann = _annotator_name(f)
        for row in csv.DictReader(open(f, encoding="utf-8")):
            rid = row["id"]
            v = _norm(row.get("validity"))
            if v in _VALID_CATS:
                val[rid][ann] = v
            if _norm(row.get("source_error")) in ("yes", "y", "true", "1"):
                src_err[rid] = True

    adjudicated: Dict[str, str] = {}
    if args.adjudicated and os.path.exists(args.adjudicated):
        for row in csv.DictReader(open(args.adjudicated, encoding="utf-8")):
            adjudicated[row["id"]] = _norm(row.get("validity"))

    _CATS = sorted({v for d in val.values() for v in d.values()}) or ["valid", "invalid"]

    # ── final per-item label ─────────────────────────────────────────────────
    final: Dict[str, str] = {}     # id -> valid/invalid/source_error/pending
    n_double = n_disagree = 0
    for rid, raters in val.items():
        if src_err.get(rid):
            final[rid] = "source_error"
            continue
        labels = list(raters.values())
        if len(raters) >= 2:
            n_double += 1
            if len(set(labels)) > 1:
                n_disagree += 1
        if rid in adjudicated and adjudicated[rid] in _VALID_CATS:
            f = adjudicated[rid]
        elif labels and len(set(labels)) == 1 and labels[0] in ("valid", "invalid"):
            f = labels[0]
        else:
            f = "pending"           # disagreement or agreed-unsure -> adjudicate
        final[rid] = f

    # ── aggregation helper ───────────────────────────────────────────────────
    def stratum_rows(keyfn):
        groups: Dict[str, List[str]] = defaultdict(list)
        for rid in val:
            groups[keyfn(key.get(rid, {}))].append(rid)
        out = []
        for g, ids in sorted(groups.items()):
            valid = sum(1 for i in ids if final[i] == "valid")
            invalid = sum(1 for i in ids if final[i] == "invalid")
            serr = sum(1 for i in ids if final[i] == "source_error")
            pend = sum(1 for i in ids if final[i] == "pending")
            resolved = valid + invalid
            p, lo, hi = wilson_ci(valid, resolved)
            sub = {i: val[i] for i in ids}
            kr = krippendorff_alpha_nominal(sub)
            ac1 = gwet_ac1(sub, _CATS)
            # Raw pairwise agreement on double-annotated items. Reported
            # ALONGSIDE alpha because alpha is deflated in high-prevalence
            # strata (the "kappa paradox"): when ~97% of items share one
            # label, chance agreement is already ~97%, so alpha can be near
            # zero despite near-perfect agreement.
            dbl_ids = [i for i in ids if len(val[i]) >= 2]
            agree = sum(1 for i in dbl_ids if len(set(val[i].values())) == 1)
            raw = (agree / len(dbl_ids)) if dbl_ids else None
            out.append((g, len(ids), resolved, valid, invalid, serr, pend, p, lo, hi,
                        kr, ac1, raw, len(dbl_ids)))
        return out

    def fmt_rows(rows):
        L = ["| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |",
             "|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|"]
        for g, n, res, v, inv, se, pe, p, lo, hi, kr, ac1, raw, ndbl in rows:
            ci = "—" if res == 0 else f"{100*p:.1f}% [{100*lo:.1f}, {100*hi:.1f}]"
            a = "—" if kr is None else f"{kr:.3f}"
            g1 = "—" if ac1 is None else f"{ac1:.3f}"
            ra = "—" if raw is None else f"{100*raw:.1f}% ({ndbl})"
            L.append(f"| {g} | {n} | {res} | {v} | {inv} | {se} | {pe} | {ci} | {a} | {g1} | {ra} |")
        return "\n".join(L)

    # overall pairwise Cohen kappa
    anns = sorted({a for d in val.values() for a in d})
    kappa_lines = []
    for a, b in combinations(anns, 2):
        pairs = [(d[a], d[b]) for d in val.values() if a in d and b in d]
        k = cohen_kappa(pairs)
        kappa_lines.append(f"  - {a}–{b}: kappa={k:.3f} (n={len(pairs)})" if k is not None
                           else f"  - {a}–{b}: (no co-rated items)")
    alpha_all = krippendorff_alpha_nominal(val)
    ac1_all = gwet_ac1(val, _CATS)

    total = len(val)
    final_valid = sum(1 for f in final.values() if f == "valid")

    # ── render ───────────────────────────────────────────────────────────────
    R = []
    R.append("# Human Verification — Results\n")
    R.append(f"- Items annotated: **{total}** ({len(anns)} annotators: {', '.join(anns)})")
    R.append(f"- Double-annotated: {n_double}; disagreements: {n_disagree} "
             f"({100*n_disagree/max(n_double,1):.1f}% of double-annotated) → adjudication")
    R.append(f"- Still **pending** adjudication: {sum(1 for f in final.values() if f=='pending')}")
    R.append(f"- Source-error rows (dropped): {sum(1 for f in final.values() if f=='source_error')}")
    R.append(f"- **Final retained N (valid): {final_valid}**\n")
    R.append("## Inter-annotator agreement (validity)\n")
    R.append("> Alpha and raw agreement are both reported per stratum. In "
             "high-prevalence strata (where nearly all items share one label) "
             "chance agreement is already very high, so alpha is deflated by "
             "construction. **Gwet's AC1** is chance-corrected but does not "
             "degenerate under high prevalence; it is however permissive in the "
             "opposite direction (random labelling of a highly skewed stratum "
             "still scores high). Read alpha and AC1 as a lower and upper "
             "bracket on reliability: alpha is the primary figure wherever "
             "labels genuinely vary, AC1 documents agreement where alpha is "
             "degenerate, and raw agreement is reported for transparency. "
             "`n_2` is the number of double-annotated items in that stratum.\n")
    R.append(f"- Krippendorff's alpha (nominal, all items): "
             f"**{'—' if alpha_all is None else f'{alpha_all:.3f}'}**")
    R.append(f"- Gwet's AC1 (nominal, all items): "
             f"**{'—' if ac1_all is None else f'{ac1_all:.3f}'}**")
    R.append("- Pairwise Cohen's kappa:")
    R.extend(kappa_lines)
    R.append("\n## Validity by strategy\n")
    R.append(fmt_rows(stratum_rows(lambda m: m.get("strategy", "?"))))
    R.append("\n## Validity by provenance\n")
    R.append(fmt_rows(stratum_rows(lambda m: m.get("provenance", "?"))))
    R.append("\n## Validity by dataset\n")
    R.append(fmt_rows(stratum_rows(lambda m: m.get("dataset", "?"))))
    R.append("\n## Validity by strategy × provenance\n")
    R.append(fmt_rows(stratum_rows(lambda m: f"{m.get('strategy','?')} / {m.get('provenance','?')}")))
    R.append("\n## Overall\n")
    R.append(fmt_rows(stratum_rows(lambda m: "ALL")))
    report = "\n".join(R) + "\n"

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(report)
        print(f"Wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
