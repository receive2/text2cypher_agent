#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebuild_from_manifest.py
========================
Reviewer-facing reproducibility check: reconstruct the released dataset from
the frozen decision manifest and verify it is identical to the released files.

The perturbed question is NOT copied from the manifest — it is **re-derived**
by applying the recorded edit (entity -> perturbed form) to the recorded
unperturbed question through the same word-boundary replacement + splice
grammar guard used at generation time. Everything else (gold Cypher, source
row, decision metadata) comes from the manifest verbatim. Equality is checked
per file via canonical sha256 (key-order-independent JSON).

    python scripts/rebuild_from_manifest.py                # verify against released files
    python scripts/rebuild_from_manifest.py --out DIR      # also write rebuilt files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import eval_config as cfg  # noqa: E402
from data_augmentation.pipeline import _replace_all  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
MANIFEST_V21 = Path.home() / "datasets" / "release_manifest_v2.1.jsonl"   # pre-verification freeze
MANIFEST = _REPO / "benchmarks" / "release_manifest_v2.2.jsonl"           # verified release (in-repo)


def canonical_hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_manifest(path) -> tuple[dict, list]:
    lines = open(path, encoding="utf-8").read().splitlines()
    header = json.loads(lines[0])
    assert header.get("_manifest_header"), "first line must be the manifest header"
    return header, [json.loads(l) for l in lines[1:]]


def build_rows(recs) -> dict:
    """Re-derive the released rows from manifest records.

    Returns ``{dataset: (rows, probed_rows)}`` in manifest order. The perturbed
    question is NOT copied — it is rebuilt from ``original_nl`` and the frozen
    edit through the same word-boundary replacement + splice guard used at
    generation time, so the manifest is the only input. This is the one place
    the row shape is defined; the verified-release freeze reuses it so a v2.2
    manifest verifies with exactly this code."""
    rebuilt = defaultdict(lambda: ([], []))
    for r in sorted(recs, key=lambda r: (r["dataset"], r["position"])):
        meta = r["aug_meta"]
        e = (meta.get("edits") or [{}])[0]
        original_nl = meta.get("original_nl") or ""
        nl = _replace_all(original_nl, e.get("from", ""), e.get("to", ""))
        assert nl is not None, f"derivation failed at {r['dataset']}:{r['position']}"
        row = {"dataset": r["dataset"], "graph": r["graph"], "id": r["id"],
               "nl": nl, "gold_cypher": r["gold_cypher"],
               "_aug_meta": meta, "_source_row": r["_source_row"]}
        pmeta = json.loads(json.dumps(meta))          # deep copy
        pedit = (pmeta.get("edits") or [{}])[0]
        if r.get("probed_grounding") is not None:
            pedit["grounding_probe"] = r["probed_grounding"]
        prow = {**row, "_aug_meta": pmeta, **(r.get("probed_extra_keys") or {})}
        rebuilt[r["dataset"]][0].append(row)
        rebuilt[r["dataset"]][1].append(prow)
    return rebuilt


def verify(header, rebuilt, out=None, datasets=None) -> bool:
    """Three-way check per file: the rows rebuilt from the manifest must hash
    to (a) the hash frozen in the manifest header AND (b) the released file
    currently on disk. (a) alone only proves the manifest is self-consistent;
    (b) is what a reviewer actually wants — that the files they downloaded are
    exactly what the frozen decisions produce. A missing on-disk file is
    reported and fails the check."""
    ok = True
    for ds, path in (datasets or _DATASETS).items():
        rows, prows = rebuilt[ds]
        for name, built in (("test.json", rows), ("test.probed.json", prows)):
            want = header["released_hashes"][f"{ds}/{name}"]
            got = canonical_hash(built)
            disk_path = Path(path).with_name(name)
            try:
                disk = canonical_hash(json.load(open(disk_path, encoding="utf-8")))
            except (OSError, ValueError):
                disk = None
            good = got == want and disk == got
            ok &= good
            state = ("OK " if good else
                     "FAIL(frozen)" if got != want else
                     "FAIL(disk missing)" if disk is None else "FAIL(disk)")
            print(f"  {state} {ds}/{name}: rebuilt={got[:16]}… frozen={want[:16]}… "
                  f"disk={'—' if disk is None else disk[:16] + '…'}")
            if out:
                o = Path(out) / ds
                o.mkdir(parents=True, exist_ok=True)
                json.dump(built, open(o / name, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="also write rebuilt files here")
    ap.add_argument("--manifest", default=str(MANIFEST),
                    help=f"decision manifest to rebuild from (default: the verified release, "
                         f"{MANIFEST}; the pre-verification freeze is {MANIFEST_V21})")
    args = ap.parse_args()

    header, recs = load_manifest(args.manifest)
    print(f"manifest {header['version']}: {len(recs)} rows")
    rebuilt = build_rows(recs)
    ok = verify(header, rebuilt, out=args.out)
    print(f"\n{len(recs)} perturbed questions re-derived from frozen decisions.")
    print("REBUILD VERIFIED — the released files are exactly what the frozen decisions produce."
          if ok else "MISMATCH — the files on disk are not the release this manifest describes.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
