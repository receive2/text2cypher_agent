#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py — check that this checkout's benchmark files are the released v2.3
verified freeze, byte-for-byte in content.

Run this BEFORE starting any experiment. Results from a mismatched copy cannot
be pooled with anyone else's.

    python benchmarks/verify.py        # -> "VERIFIED" or a list of mismatches

Hashes are canonical (sha256 over key-sorted JSON), so reformatting or key
reordering does not cause a false alarm — and does not hide a real change
either. They are the same hashes the release manifest records; the full
provenance chain is re-derivable with scripts/rebuild_from_manifest.py.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

VERSION = "v2.3-verified-2026-09-22"
ROW_COUNT = 4590
EXPECTED = {
    "cypherbench_augmented_v2/test.json":          "13dcfd41a4468625007d12600378c20886debaf72b2c4fe8a57a18e15228f666",
    "cypherbench_augmented_v2/test.probed.json":   "606977f8766338da5ff4ee9375dc8c421be47e27ae541bb624593d6d3b517181",
    "mindthequery_augmented_v2/test.json":         "a5f49acad52d83ce714e75dd8672246c66bc31598ed2e6bb6f16f199ca9364b0",
    "mindthequery_augmented_v2/test.probed.json":  "ba53b001974a158995922828e429a56f79fce4b846832b43857734e9c8a7e609",
    "zograscope_augmented_v2/test.json":           "1a2b60095fa2c71beffb6eaed492fbed198d0ce6d8434707e3b5195da98d9e75",
    "zograscope_augmented_v2/test.probed.json":    "5ca5ab505540292005208c0e9d5458d23565759d159bf20263e305ebc958cb14",
}


def canonical_hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def main() -> int:
    bad, missing, rows = [], [], 0
    for rel, want in sorted(EXPECTED.items()):
        p = HERE / rel
        if not p.exists():
            missing.append(rel)
            continue
        obj = json.loads(p.read_text(encoding="utf-8"))
        if rel.endswith("/test.json"):
            rows += len(obj)
        got = canonical_hash(obj)
        # manifest stores a truncated digest for some entries; compare on the
        # shorter of the two so a truncated expectation still discriminates.
        n = min(len(got), len(want))
        if got[:n] != want[:n]:
            bad.append((rel, want[:16], got[:16]))

    print(f"benchmarks {VERSION} — expected {ROW_COUNT} perturbed questions")
    for rel in missing:
        print(f"  MISSING  {rel}")
    for rel, want, got in bad:
        print(f"  MISMATCH {rel}\n           expected {want}…  got {got}…")
    if not missing and not bad:
        print(f"  all 6 files match; {rows} rows")
        print("VERIFIED — safe to run experiments and pool results.")
        return 0
    print("\nFAILED — do NOT run experiments with this copy. Re-pull the repo; if it\n"
          "still fails, ask the maintainer for the v2.3 verified release (results from a\n"
          "mismatched copy cannot be pooled).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
