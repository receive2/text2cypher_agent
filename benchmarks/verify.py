#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py — check that this checkout's benchmark files are the released v2.2
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

VERSION = "v2.2-verified-2026-09-09"
ROW_COUNT = 4611
EXPECTED = {
    "cypherbench_augmented_v2/test.json":          "535afb41c4498453a17b074371df89dbf5d3a70860dcaf5f747a18e61d623ff1",
    "cypherbench_augmented_v2/test.probed.json":   "f7b0906dbef27f9141a46c05d9217fe1fb0b67d6c2fdc488d886da7768602139",
    "mindthequery_augmented_v2/test.json":         "8b0c06e5f71b9f987402c382e04db96f4bfc54df8e1848d9f41f438eb0bd1e62",
    "mindthequery_augmented_v2/test.probed.json":  "a3408dbbedca96bade330f30b945a69535eea244bb3ecf9accb0f6961a35dda5",
    "zograscope_augmented_v2/test.json":           "6b224f4e89ab43532b2408dffd3d2266c46eca396891ab614e2c7ccdaddedd8d",
    "zograscope_augmented_v2/test.probed.json":    "df167bb62da65dc31b702766bf5c4e386c24da0a9a058b4555b87c7326aa0f54",
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
          "still fails, ask the maintainer for the v2.2 verified release (results from a\n"
          "mismatched copy cannot be pooled).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
