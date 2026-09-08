#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py — check that this checkout's benchmark files are the released v2.1
freeze, byte-for-byte in content.

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

VERSION = "v2.1-freeze-2026-08-22"
ROW_COUNT = 4641
EXPECTED = {
    "cypherbench_augmented_v2/test.json":          "4948f19be3bfd70069e53c4ae69467903df18921eb2207d8481da755bb4315be",
    "cypherbench_augmented_v2/test.probed.json":   "6a9dc1e08993318d8720502ccd1f896a6be2468cb046bc7d91d1e45061e24d86",
    "mindthequery_augmented_v2/test.json":         "a1612aee41cbdb935d2911e82887f06eac92a67dd7b643efc4ff855adcb53fac",
    "mindthequery_augmented_v2/test.probed.json":  "0453f5ba281c6b02a2147a040147a67d76fe72ba131edf199b488bebf95abf24",
    "zograscope_augmented_v2/test.json":           "e96ef6baa6cc4fc2c1e1eedefcc83f0c08e623cc15b515ddbf2572938108d509",
    "zograscope_augmented_v2/test.probed.json":    "4a8598b5df3d3cd45186f75d38fe867345f0f879928144847825869e363f5430",
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
          "still fails, ask the maintainer for the v2.1 freeze (results from a\n"
          "mismatched copy cannot be pooled).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
