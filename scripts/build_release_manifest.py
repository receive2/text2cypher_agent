#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_release_manifest.py
=========================
Freeze the released dataset into a **decision manifest**: one record per row
carrying everything that determined it — the verbatim upstream source row, the
unperturbed question, the gold Cypher, and the final edit decision (entity,
strategy, perturbed form, provenance, evidence, gate verdicts). All
non-deterministic inputs (LLM proposals) are thereby frozen as data.

`scripts/rebuild_from_manifest.py` then reconstructs the dataset from the
manifest alone: the perturbed question is **re-derived** (word-boundary
replacement + splice guard), not copied, and the result is verified equal to
the released files (canonical sha256 per file). One command, reviewer-runnable.

The manifest also supersedes the per-wave curation logs as the complete
row-level provenance record.

Output: ~/datasets/release_manifest_v2.1.jsonl (+ prints canonical hashes).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import eval_config as cfg  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
MANIFEST = Path.home() / "datasets" / "release_manifest_v2.1.jsonl"


def canonical_hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def main() -> int:
    records = []
    hashes = {}
    for ds, path in _DATASETS.items():
        rows = json.load(open(path, encoding="utf-8"))
        probed = json.load(open(Path(path).with_name("test.probed.json"),
                                encoding="utf-8"))
        assert len(rows) == len(probed), ds
        hashes[f"{ds}/test.json"] = canonical_hash(rows)
        hashes[f"{ds}/test.probed.json"] = canonical_hash(probed)
        for i, (x, xp) in enumerate(zip(rows, probed)):
            meta = x["_aug_meta"]
            pmeta = xp["_aug_meta"]
            pe = (pmeta.get("edits") or [{}])[0]
            rec = {
                "dataset": ds,
                "position": i,
                "graph": x.get("graph"),
                "id": x.get("id"),
                "gold_cypher": x.get("gold_cypher"),
                "_source_row": x.get("_source_row"),
                "aug_meta": meta,                       # decision record (verbatim)
                "probed_grounding": pe.get("grounding_probe"),
                # any probed-only top-level keys beyond the shared schema
                "probed_extra_keys": {k: xp[k] for k in xp
                                      if k not in x and k != "_aug_meta"},
            }
            records.append(rec)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_manifest_header": True,
                             "version": "v2.1-freeze-2026-08-22",
                             "row_count": len(records),
                             "released_hashes": hashes},
                            ensure_ascii=False) + "\n")
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"manifest: {MANIFEST}  ({len(records)} rows)")
    for k, v in hashes.items():
        print(f"  {k}: {v[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
