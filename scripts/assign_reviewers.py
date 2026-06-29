#!/usr/bin/env python3
"""
assign_reviewers.py
===================
Rebuilds benchmarks/needs_verification_review.xlsx with a new
'assigned_reviewer' column.

Assignment rules
----------------
- Only LOW and MEDIUM confidence rows are assigned for human review.
- HIGH confidence rows get an empty reviewer cell.
- LOW rows and MEDIUM rows are distributed SEPARATELY (round-robin after
  a seeded shuffle) so each reviewer gets a proportional mix of both.
- Priyanka receives a small fixed quota from each pool; the remainder is
  split equally among the other five reviewers.

Reviewer roster
---------------
  Primary (equal share): Puneeth, Chaitanya, Ashvi, Pei, Ayush
  Lite reviewer          : Priyanka (small quota)

Determinism
-----------
random.seed(42) — re-running produces the same assignment.

Usage
-----
  python scripts/assign_reviewers.py
  python scripts/assign_reviewers.py --priyanka-quota 8   # default 8
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.parse
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
BENCHMARKS  = REPO_ROOT / "benchmarks"
CHECKPOINT  = BENCHMARKS / "verification_progress.jsonl"
OUTPUT_XLSX = BENCHMARKS / "needs_verification_review.xlsx"

DATASETS = [
    "cypherbench_augmented_v2",
    "mindthequery_augmented_v2",
    "zograscope_augmented_v2",
]

# ── Reviewers ─────────────────────────────────────────────────────────────────
PRIMARY_REVIEWERS = ["Puneeth", "Chaitanya", "Ashvi", "Pei", "Ayush"]
LITE_REVIEWER     = "Priyanka"
# Priyanka's quota per confidence tier (medium + low kept proportional)
# Default: 4 medium + 4 low = 8 total.  Adjust with --priyanka-quota.


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_original_nl() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ds in DATASETS:
        rows = json.loads((BENCHMARKS / ds / "test.json").read_text())
        for r in rows:
            mapping[r["id"]] = r.get("_aug_meta", {}).get("original_nl") or r["nl"]
    return mapping


def _load_rows(orig_nl: dict[str, str]) -> list[dict]:
    rows = []
    for ds in DATASETS:
        with (BENCHMARKS / ds / "needs_verification.jsonl").open() as fh:
            for line in fh:
                r = json.loads(line)
                rows.append({
                    "dataset":      ds,
                    "graph":        r.get("graph", ""),
                    "qid":          r.get("qid", ""),
                    "strategy":     r.get("strategy", ""),
                    "original_nl":  orig_nl.get(r.get("qid", ""), ""),
                    "augmented_nl": r.get("nl", ""),
                    "from":         r.get("from", ""),
                    "to":           r.get("to", ""),
                })
    return rows


def _load_checkpoint() -> dict[str, dict]:
    done: dict[str, dict] = {}
    if CHECKPOINT.exists():
        with CHECKPOINT.open() as fh:
            for line in fh:
                obj = json.loads(line)
                done[obj["qid"]] = obj
    return done


# ── Reviewer assignment ───────────────────────────────────────────────────────

def _build_assignment(results: dict[str, dict], priyanka_quota: int) -> dict[str, str]:
    """
    Return {qid: reviewer_name} for all LOW and MEDIUM rows.

    Strategy
    --------
    1. Bucket qids by confidence tier.
    2. Shuffle each bucket with seed 42 (deterministic).
    3. Pull priyanka_quota items from each bucket for Priyanka.
       If a bucket has fewer rows than the quota, give Priyanka all of them.
    4. Distribute the remainder round-robin across PRIMARY_REVIEWERS.
    """
    rng = random.Random(42)

    by_conf: dict[str, list[str]] = defaultdict(list)
    for qid, res in results.items():
        conf = res.get("confidence", "high")
        if conf in ("medium", "low"):
            by_conf[conf].append(qid)

    # Shuffle each tier independently for a fair mix
    for tier in by_conf:
        rng.shuffle(by_conf[tier])

    assignment: dict[str, str] = {}

    # Split quota evenly across medium and low
    # e.g. quota=8 → 4 medium + 4 low; quota=10 → 5 medium + 5 low
    half = priyanka_quota // 2

    for tier in ("medium", "low"):
        pool = by_conf.get(tier, [])
        q    = min(half, len(pool))
        # Assign Priyanka's slice
        for qid in pool[:q]:
            assignment[qid] = LITE_REVIEWER
        # Round-robin the rest across primary reviewers
        remainder = pool[q:]
        for i, qid in enumerate(remainder):
            assignment[qid] = PRIMARY_REVIEWERS[i % len(PRIMARY_REVIEWERS)]

    return assignment


# ── Excel generation ──────────────────────────────────────────────────────────

def _build_excel(rows: list[dict], results: dict[str, dict], assignment: dict[str, str]) -> None:
    HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
    EVEN_FILL   = PatternFill("solid", fgColor="EBF3FB")
    ODD_FILL    = PatternFill("solid", fgColor="FFFFFF")
    CONF_COLORS = {
        "high":   PatternFill("solid", fgColor="C6EFCE"),
        "medium": PatternFill("solid", fgColor="FFEB9C"),
        "low":    PatternFill("solid", fgColor="FFC7CE"),
    }
    WRAP   = Alignment(wrap_text=True, vertical="top")
    CENTER = Alignment(horizontal="center", vertical="top", wrap_text=True)
    BORDER = Border(
        bottom=Side(style="thin", color="BDD7EE"),
        right=Side(style="thin", color="BDD7EE"),
    )

    COLUMNS = [
        ("dataset",             22),
        ("graph",               16),
        ("qid",                 36),
        ("strategy",            12),
        ("original_nl",         52),
        ("augmented_nl",        52),
        ("from",                28),
        ("to",                  24),
        ("auto_confidence",     18),
        ("auto_reason",         60),
        ("evidence_urls",       40),
        ("google_search",       18),
        ("assigned_reviewer",   22),   # NEW
        ("human_verification",  22),
        ("notes",               40),
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Verification"

    headers = [c for c, _ in COLUMNS]
    for col_idx, (header, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font      = HEADER_FONT
        cell.fill      = HEADER_FILL
        cell.alignment = CENTER
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[1].height = 24

    CONF_COL     = headers.index("auto_confidence")    + 1
    GOOGLE_COL   = headers.index("google_search")      + 1
    REVIEWER_COL = headers.index("assigned_reviewer")  + 1
    VERIFY_COL   = headers.index("human_verification") + 1

    for row_idx, r in enumerate(rows, start=2):
        base_fill = EVEN_FILL if row_idx % 2 == 0 else ODD_FILL
        res  = results.get(r["qid"], {})
        conf = res.get("confidence", "")
        urls = res.get("evidence_urls", [])

        values = [
            r["dataset"],
            r["graph"],
            r["qid"],
            r["strategy"],
            r["original_nl"],
            r["augmented_nl"],
            r["from"],
            r["to"],
            conf,
            res.get("reason", ""),
            " | ".join(urls),
            "🔍 Search",
            assignment.get(r["qid"], ""),   # assigned_reviewer
            "",                              # human_verification
            "",                              # notes
        ]

        for col_idx, value in enumerate(values, start=1):
            cell           = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.fill      = base_fill
            cell.border    = BORDER
            cell.alignment = WRAP

        # Confidence colour
        conf_cell = ws.cell(row=row_idx, column=CONF_COL)
        if conf in CONF_COLORS:
            conf_cell.fill = CONF_COLORS[conf]
        conf_cell.alignment = CENTER

        # Google hyperlink
        q     = urllib.parse.quote_plus(f'"{r["from"]}" "{r["to"]}" {r["graph"]}')
        gcell = ws.cell(row=row_idx, column=GOOGLE_COL)
        gcell.hyperlink = f"https://www.google.com/search?q={q}"
        gcell.value     = "🔍 Search"
        gcell.font      = Font(color="0563C1", underline="single")
        gcell.alignment = CENTER

        # Reviewer cell — centre-align
        ws.cell(row=row_idx, column=REVIEWER_COL).alignment = CENTER

        ws.row_dimensions[row_idx].height = 52

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    dv = DataValidation(
        type="list",
        formula1='"CORRECT,INCORRECT,UNSURE"',
        allow_blank=True,
        showDropDown=False,
        showErrorMessage=True,
        errorTitle="Invalid value",
        error="Choose CORRECT, INCORRECT, or UNSURE.",
    )
    ws.add_data_validation(dv)
    last = len(rows) + 1
    dv.add(f"{get_column_letter(VERIFY_COL)}2:{get_column_letter(VERIFY_COL)}{last}")

    wb.save(OUTPUT_XLSX)
    print(f"Excel written → {OUTPUT_XLSX}")


# ── Summary ───────────────────────────────────────────────────────────────────

def _print_summary(assignment: dict[str, str], results: dict[str, dict]) -> None:
    from collections import Counter
    reviewer_counts: Counter = Counter(assignment.values())
    conf_by_reviewer: dict[str, Counter] = defaultdict(Counter)
    for qid, reviewer in assignment.items():
        conf_by_reviewer[reviewer][results[qid]["confidence"]] += 1

    print()
    print("  Reviewer assignment summary")
    print(f"  {'Reviewer':<14}  {'Total':>5}  {'Medium':>7}  {'Low':>5}")
    print(f"  {'─'*14}  {'─'*5}  {'─'*7}  {'─'*5}")
    all_reviewers = PRIMARY_REVIEWERS + [LITE_REVIEWER]
    for r in all_reviewers:
        total  = reviewer_counts.get(r, 0)
        medium = conf_by_reviewer[r].get("medium", 0)
        low    = conf_by_reviewer[r].get("low", 0)
        print(f"  {r:<14}  {total:>5}  {medium:>7}  {low:>5}")
    print(f"  {'─'*14}  {'─'*5}  {'─'*7}  {'─'*5}")
    print(f"  {'TOTAL':<14}  {sum(reviewer_counts.values()):>5}")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--priyanka-quota", type=int, default=8,
                        help="Total rows assigned to Priyanka (split evenly medium/low). Default 8.")
    args = parser.parse_args()

    print("Loading data …")
    orig_nl = _load_original_nl()
    rows    = _load_rows(orig_nl)
    results = _load_checkpoint()
    print(f"  {len(rows)} rows  |  {len(results)} assessed")

    print("Building reviewer assignment …")
    assignment = _build_assignment(results, priyanka_quota=args.priyanka_quota)
    _print_summary(assignment, results)

    print("Building Excel …")
    _build_excel(rows, results, assignment)
    print("Done.")


if __name__ == "__main__":
    main()
