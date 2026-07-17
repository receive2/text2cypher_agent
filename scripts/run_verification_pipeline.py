#!/usr/bin/env python3
"""
run_verification_pipeline.py
============================
End-to-end orchestrator for the needs-verification human-review workflow.

Pipeline
--------
  1. Preflight       Check that OPENAI_API_KEY is set and packages are installed.
  2. Auto-verify     For each needs_verification row across all 3 benchmarks:
                       a) DuckDuckGo search for the from->to entity rewrite
                       b) LLM (default: gpt-4o-mini) assigns
                          low/medium/high confidence + a reason
                       c) Checkpoint to verification_progress.jsonl (resume-safe)
  3. Build Excel     Render benchmarks/needs_verification_review.xlsx with:
                       - colour-coded auto_confidence column
                       - auto_reason + evidence_urls
                       - google_search hyperlink
                       - human_verification dropdown (CORRECT/INCORRECT/UNSURE)
  4. Summary         Print confidence distribution + output paths.

Usage
-----
  python scripts/run_verification_pipeline.py                  # full run
  python scripts/run_verification_pipeline.py --limit 50       # smoke test
  python scripts/run_verification_pipeline.py --excel-only     # rebuild Excel
                                                               # from checkpoint
  python scripts/run_verification_pipeline.py --reset          # wipe + restart

Architecture
------------
  scripts/walmart_llm.py            : Generic OpenAI-compatible LLM client
  scripts/auto_verify.py            : DDG search + LLM + checkpoint + Excel
  scripts/run_verification_pipeline : THIS FILE - orchestrates the above

Inputs
------
  benchmarks/<dataset>/needs_verification.jsonl   (3 datasets, 814 rows total)
  benchmarks/<dataset>/test.json                  (for original_nl lookup)
  OPENAI_API_KEY env var (or .env file)

Outputs
-------
  benchmarks/verification_progress.jsonl          (per-row checkpoint)
  benchmarks/needs_verification_review.xlsx       (final human-review sheet)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parent.parent
SCRIPTS    = REPO_ROOT / "scripts"
BENCHMARKS = REPO_ROOT / "benchmarks"

CHECKPOINT  = BENCHMARKS / "verification_progress.jsonl"
OUTPUT_XLSX = BENCHMARKS / "needs_verification_review.xlsx"

DATASETS = [
    "cypherbench_augmented_v2",
    "mindthequery_augmented_v2",
    "zograscope_augmented_v2",
]


# -- Step 1: Preflight --------------------------------------------------------

def _preflight() -> None:
    print("-" * 70)
    print(" Step 1/4 -- Preflight checks")
    print("-" * 70)

    errors = []

    # OPENAI_API_KEY check
    import os
    if not os.getenv("OPENAI_API_KEY") and not (
        os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY")
    ):
        errors.append(
            "Missing API key: set OPENAI_API_KEY (or AZURE_OPENAI_ENDPOINT + "
            "AZURE_OPENAI_API_KEY for Azure) in your environment or .env file."
        )
    else:
        print("  OK  LLM API key found in environment")

    # Required Python packages
    required = ["openai", "openpyxl"]
    for pkg in required:
        try:
            __import__(pkg)
            print(f"  OK  Package installed: {pkg}")
        except ImportError:
            errors.append(f"Missing package: {pkg}  ->  pip install {pkg}")

    # Input data
    for ds in DATASETS:
        nv = BENCHMARKS / ds / "needs_verification.jsonl"
        tj = BENCHMARKS / ds / "test.json"
        if not nv.exists():
            errors.append(f"Missing input: {nv}")
        if not tj.exists():
            errors.append(f"Missing input: {tj}")
    if not errors:
        print(f"  OK  Input files found for {len(DATASETS)} datasets")

    # Helper scripts
    for s in ("walmart_llm.py", "auto_verify.py"):
        if not (SCRIPTS / s).exists():
            errors.append(f"Missing helper: scripts/{s}")
        else:
            print(f"  OK  Helper script: {s}")

    if errors:
        print("\nPreflight failed:")
        for e in errors:
            print(f"   FAIL  {e}")
        sys.exit(1)

    # Total input row count
    total = 0
    for ds in DATASETS:
        nv = BENCHMARKS / ds / "needs_verification.jsonl"
        with nv.open() as fh:
            total += sum(1 for _ in fh)
    print(f"  ->  {total} rows queued across {len(DATASETS)} datasets")


# -- Step 2 + 3: Auto-verify + Excel -----------------------------------------

def _run_auto_verify(limit: int, reset: bool, excel_only: bool, delay: float) -> None:
    print()
    print("-" * 70)
    print(" Step 2/4 -- Auto-verify (DDG search + LLM assessment)")
    print(" Step 3/4 -- Build Excel (handled inside auto_verify.py)")
    print("-" * 70)

    cmd = [sys.executable, str(SCRIPTS / "auto_verify.py"),
           "--delay", str(delay)]
    if limit:
        cmd += ["--limit", str(limit)]
    if reset:
        cmd += ["--reset"]
    if excel_only:
        cmd += ["--excel-only"]

    print(f"  $ {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(f"\nauto_verify.py failed with exit code {result.returncode}")
        sys.exit(result.returncode)


# -- Step 4: Summary ----------------------------------------------------------

def _summary() -> None:
    print()
    print("-" * 70)
    print(" Step 4/4 -- Summary")
    print("-" * 70)

    if not CHECKPOINT.exists():
        print("  No checkpoint found -- nothing to summarise.")
        return

    rows = [json.loads(line) for line in CHECKPOINT.open()]
    total = len(rows)
    counts = Counter(r["confidence"] for r in rows)

    def pct(n: int) -> str:
        return f"{n / total * 100:5.1f}%" if total else "  n/a"

    print(f"  Total assessed      : {total}")
    print(f"    HIGH (green)      : {counts['high']:>4}   ({pct(counts['high'])})")
    print(f"    MEDIUM (yellow)   : {counts['medium']:>4}   ({pct(counts['medium'])})")
    print(f"    LOW (red)         : {counts['low']:>4}   ({pct(counts['low'])})")
    print()
    print(f"  Checkpoint file     : {CHECKPOINT.relative_to(REPO_ROOT)}")
    print(f"  Final Excel sheet   : {OUTPUT_XLSX.relative_to(REPO_ROOT)}")
    if OUTPUT_XLSX.exists():
        size_kb = OUTPUT_XLSX.stat().st_size / 1024
        print(f"                        ({size_kb:.1f} KB)")
    print()
    print("  Next step -> open the Excel in Numbers / Excel and review the")
    print("  'human_verification' column. Rows marked LOW are the")
    print("  highest-priority candidates for human attention.")
    print()


# -- Main ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N rows (0 = all)")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe checkpoint and restart from scratch")
    parser.add_argument("--excel-only", action="store_true",
                        help="Skip search/LLM; rebuild Excel from existing checkpoint")
    parser.add_argument("--delay", type=float, default=2.5,
                        help="Seconds between DDG searches (default 2.5)")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip preflight checks")
    args = parser.parse_args()

    print()
    print("=" * 70)
    print("  Text-to-Cypher  ::  Needs-Verification Auto-Review Pipeline")
    print("=" * 70)

    if not args.skip_preflight:
        _preflight()

    _run_auto_verify(
        limit=args.limit,
        reset=args.reset,
        excel_only=args.excel_only,
        delay=args.delay,
    )
    _summary()


if __name__ == "__main__":
    main()
