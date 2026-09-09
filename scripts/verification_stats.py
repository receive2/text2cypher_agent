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

Calibration exclusion (pre-registered):
  items that appeared in ANY calibration round are excluded from ALL reported
  measurements — annotators received guideline feedback on them (or at least
  had the file), so their main-queue labels are not independent. By default
  both calibration_50.csv (current set) and calibration_legacy_ids.csv (the
  set shipped in the retired 2026-08-22/23 packages, which all annotators
  received) are auto-detected next to --key; override with
  --calibration PATH [PATH ...], or pass a bare --calibration to disable
  (not recommended).

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
    if pe >= 1.0:
        # Both raters used a single, identical category on every co-rated
        # item: observed and expected agreement are both 1, so kappa is 0/0.
        # Report it as undefined rather than 1.0 — perfect agreement with no
        # label variance carries no information about reliability.
        return None
    return (po - pe) / (1 - pe)


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
    return {r["id"]: r for r in csv.DictReader(open(path, encoding="utf-8-sig"))}


def _norm(v: str) -> str:
    return (v or "").strip().lower()


def resolve_calibration_paths(key_path: str, calibration_arg) -> List[str]:
    """Pre-registered exclusion list. ``calibration_arg`` is argparse's value for
    --calibration: None = auto-detect next to --key, [] = disabled, else explicit."""
    if calibration_arg is None:
        key_dir = os.path.dirname(os.path.abspath(key_path))
        return [p for p in (os.path.join(key_dir, "calibration_50.csv"),
                            os.path.join(key_dir, "calibration_legacy_ids.csv"))
                if os.path.exists(p)]
    return [p for p in calibration_arg if p]


def load_calibration_ids(paths: List[str]) -> set:
    ids: set = set()
    for p in paths:
        if not os.path.exists(p):
            sys.exit(f"--calibration file not found: {p}")
        ids |= {r["id"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
    return ids


def expand_paths(patterns: List[str]) -> List[str]:
    out: List[str] = []
    for patt in patterns:
        out.extend(sorted(glob.glob(patt)) or [patt])
    return out


def collect_labels(key_path: str, annotation_patterns: List[str],
                   adjudicated_path: Optional[str] = None,
                   calibration_arg=None) -> dict:
    """Single source of truth for per-item verdicts.

    Both the statistics report and the metric rescoring read verdicts from here,
    so the rows the paper says were dropped are exactly the rows the metrics
    were recomputed without. Returns a dict with: ``val`` (id -> annotator ->
    validity), ``src_err``, ``final`` (id -> valid/invalid/source_error/pending),
    ``cal_ids``, ``cal_ids_seen``, ``n_cal_excluded``, ``n_double``,
    ``n_disagree``, ``files``, ``cats``.
    """
    cal_paths = resolve_calibration_paths(key_path, calibration_arg)
    cal_ids = load_calibration_ids(cal_paths)
    files = expand_paths(annotation_patterns)

    val: Dict[str, Dict[str, str]] = defaultdict(dict)
    src_err: Dict[str, bool] = defaultdict(bool)
    n_cal_excluded = 0
    cal_ids_seen: set = set()
    for f in files:
        ann = _annotator_name(f)
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            rid = row["id"]
            if rid in cal_ids:
                n_cal_excluded += 1
                cal_ids_seen.add(rid)
                continue
            v = _norm(row.get("validity"))
            if v in _VALID_CATS:
                val[rid][ann] = v
            if _norm(row.get("source_error")) in ("yes", "y", "true", "1"):
                src_err[rid] = True

    adjudicated: Dict[str, str] = {}
    if adjudicated_path and os.path.exists(adjudicated_path):
        for row in csv.DictReader(open(adjudicated_path, encoding="utf-8-sig")):
            adjudicated[row["id"]] = _norm(row.get("validity"))

    final: Dict[str, str] = {}
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
            f = "pending"
        final[rid] = f

    return {"val": val, "src_err": src_err, "final": final, "cal_ids": cal_ids,
            "cal_ids_seen": cal_ids_seen, "n_cal_excluded": n_cal_excluded,
            "n_double": n_double, "n_disagree": n_disagree, "files": files,
            "cats": sorted({v for d in val.values() for v in d.values()}) or ["valid", "invalid"]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", required=True)
    ap.add_argument("--annotations", nargs="+", required=True,
                    help="filled annotator CSVs (globs allowed)")
    ap.add_argument("--adjudicated", default=None, help="optional id,validity CSV")
    ap.add_argument("--calibration", nargs="*", default=None,
                    help="calibration CSV(s) whose ids are excluded from all "
                         "measurements (default: calibration_50.csv and "
                         "calibration_legacy_ids.csv next to --key, if "
                         "present; pass a bare --calibration to disable)")
    ap.add_argument("--out", default=None, help="write the markdown report here (else stdout)")
    ap.add_argument("--json", default=None,
                    help="also write every reported figure as JSON here (consumed by "
                         "render_datasheet_tables.py and the release freeze)")
    args = ap.parse_args(argv)

    key = _read_key(args.key)

    got = collect_labels(args.key, args.annotations, args.adjudicated, args.calibration)
    cal_ids = got["cal_ids"]
    cal_ids_seen = got["cal_ids_seen"]
    n_cal_excluded = got["n_cal_excluded"]
    val = got["val"]
    final = got["final"]
    n_double, n_disagree = got["n_double"], got["n_disagree"]
    _CATS = got["cats"]

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
    kappa_json: Dict[str, dict] = {}
    for a, b in combinations(anns, 2):
        pairs = [(d[a], d[b]) for d in val.values() if a in d and b in d]
        k = cohen_kappa(pairs)
        kappa_json[f"{a}-{b}"] = {"kappa": k, "n": len(pairs)}
        if k is not None:
            kappa_lines.append(f"  - {a}–{b}: kappa={k:.3f} (n={len(pairs)})")
        elif pairs:
            kappa_lines.append(f"  - {a}–{b}: undefined — no label variance in either rater "
                               f"(all {len(pairs)} co-rated items agree)")
        else:
            kappa_lines.append(f"  - {a}–{b}: (no co-rated items)")
    alpha_all = krippendorff_alpha_nominal(val)
    ac1_all = gwet_ac1(val, _CATS)

    total = len(val)
    final_valid = sum(1 for f in final.values() if f == "valid")

    # ── render ───────────────────────────────────────────────────────────────
    R = []
    R.append("# Human Verification — Results\n")
    R.append(f"- Items annotated: **{total}** ({len(anns)} annotators: {', '.join(anns)})")
    if cal_ids:
        R.append(f"- Calibration items excluded from all measurements "
                 f"(pre-registered): {len(cal_ids)} ids on the exclusion list "
                 f"({len(cal_ids_seen)} present in the queue; "
                 f"{n_cal_excluded} judgments dropped)")
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

    if args.json:
        import json
        cols = ("stratum", "n", "resolved", "valid", "invalid", "source_error",
                "pending", "validity", "ci_lo", "ci_hi", "alpha", "ac1",
                "raw_agreement", "n_double")
        def table(rows):
            return [dict(zip(cols, r)) for r in rows]
        payload = {
            "items": total,
            "annotators": anns,
            "calibration_excluded_ids": len(cal_ids),
            "calibration_ids_in_queue": len(cal_ids_seen),
            "calibration_judgments_dropped": n_cal_excluded,
            "double_annotated": n_double,
            "disagreements": n_disagree,
            "pending": sum(1 for f in final.values() if f == "pending"),
            "source_error": sum(1 for f in final.values() if f == "source_error"),
            "invalid": sum(1 for f in final.values() if f == "invalid"),
            "retained_valid": final_valid,
            "alpha": alpha_all,
            "ac1": ac1_all,
            "kappa": kappa_json,
            "by_strategy": table(stratum_rows(lambda m: m.get("strategy", "?"))),
            "by_provenance": table(stratum_rows(lambda m: m.get("provenance", "?"))),
            "by_dataset": table(stratum_rows(lambda m: m.get("dataset", "?"))),
            "by_strategy_provenance": table(stratum_rows(
                lambda m: f"{m.get('strategy','?')} / {m.get('provenance','?')}")),
            "overall": table(stratum_rows(lambda m: "ALL")),
            "final_labels": final,
        }
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
