#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_unchecked_curation.py
===========================
Apply the dispositions from the unchecked-edit backfill
(`audit/unchecked_backfill.jsonl`, see `audit/unchecked_backfill_summary.md`)
to the v2 datasets:

* leak classes **A–D** (dates/datetimes, structured-ID phrases, schema words /
  common nouns, CONTAINS fragments) → **delete the row** from `test.json` and
  `test.probed.json` (documented curation; logged);
* class **E** (unmatched, suspected format/unicode drift) → **hold**: leave the
  row untouched and emit `audit/unchecked_E_handcheck.csv` for a human verdict;
* `ok_backfilled` / `auto_ok_casing` → set `_aug_meta.edits[0].validity = "ok"`
  and record the provenance in `validity_backfill`.

Idempotent-ish: rows already curated are simply not matched again. Creates
one-time backups `test.json.bak-unchecked-curation` next to each file.

Usage:  python scripts/apply_unchecked_curation.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import eval_config as cfg  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
_BACKFILL = _REPO / "audit" / "unchecked_backfill.jsonl"
_MONTHS = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
_SCHEMA = {"accountholders", "accountholder", "moneytransfer", "moneytransfers", "purchases",
           "creditcards", "bankaccounts", "is_primary_suspect", "utc", "after", "tournament",
           "politicians", "country", "countries", "ceos", "crime participants", "home",
           "oceans", "aircraft manufacturers", "terrorist", "serial killer"}


def classify(from_val: str) -> str:
    f = from_val or ""
    fl = f.lower()
    if re.search(_MONTHS, fl) or re.search(r"\b\d{1,2}(st|nd|rd|th)\b.*\d{4}", fl) \
            or re.search(r"\d{4}-\d{2}-\d{2}", f):
        return "A_date_datetime_leak"
    if re.search(r"\d{2,}[-/.]\d{2,}", f) or re.search(r"\b(number|no\.?|id|badge|phone|nhs|account|card|ip)\b", fl) \
            or re.search(r"\d{5,}", f):
        return "B_id_descriptor_leak"
    if fl in _SCHEMA:
        return "C_schema_or_common_noun"
    if re.search(r"\.(com|jp|org|net)\b", fl) or fl == "com":
        return "D_fragment_literal"
    return "E_unmatched_maybe_format"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plans = {}  # row_id -> (action, record)
    for line in open(_BACKFILL, encoding="utf-8"):
        r = json.loads(line)
        if r["result"] == "unresolved":
            cls = classify(r["from"])
            action = "hold_E" if cls == "E_unmatched_maybe_format" else "drop"
        elif r["result"] in ("ok_backfilled", "auto_ok_casing"):
            cls, action = r["result"], "flip_ok"
        else:
            cls, action = r["result"], "none"
        plans[r["row_id"]] = (action, cls, r)

    log_rows, hold_rows = [], []
    for ds, path in _DATASETS.items():
        p = Path(path)
        rows = json.load(open(p, encoding="utf-8"))
        probed_p = p.with_name("test.probed.json")
        probed = json.load(open(probed_p, encoding="utf-8"))
        keep, keep_probed = [], []
        n_drop = n_flip = n_hold = 0
        for i, (x, xp) in enumerate(zip(rows, probed)):
            rid = f"{ds}:{i}"
            action, cls, rec = plans.get(rid, ("none", "", None))
            meta = x.get("_aug_meta") or {}
            edits = meta.get("edits") or []
            if action == "drop":
                n_drop += 1
                log_rows.append([ds, rec["graph"], rid, rec.get("source_id", ""), rec["strategy"],
                                 rec["source"], rec["from"], rec["to"], cls, "dropped"])
                continue
            if action == "flip_ok" and edits:
                edits[0]["validity"] = "ok"
                edits[0]["validity_backfill"] = cls
                pm = (xp.get("_aug_meta") or {}).get("edits") or []
                if pm:
                    pm[0]["validity"] = "ok"
                    pm[0]["validity_backfill"] = cls
                n_flip += 1
                log_rows.append([ds, rec["graph"], rid, rec.get("source_id", ""), rec["strategy"],
                                 rec["source"], rec["from"], rec["to"], cls, "validity->ok"])
            if action == "hold_E":
                n_hold += 1
                hold_rows.append({
                    "row_id": rid, "dataset": ds, "graph": rec["graph"],
                    "strategy": rec["strategy"], "source": rec["source"],
                    "original_entity": rec["from"], "perturbed_form": rec["to"],
                    "augmented_question": x.get("nl") or x.get("question") or x.get("nl_question") or "",
                    "verdict": "", "notes": "",
                })
                log_rows.append([ds, rec["graph"], rid, rec.get("source_id", ""), rec["strategy"],
                                 rec["source"], rec["from"], rec["to"], cls, "held_for_handcheck"])
            keep.append(x)
            keep_probed.append(xp)
        print(f"{ds}: {len(rows)} -> {len(keep)}  (drop {n_drop}, flip {n_flip}, hold {n_hold})")
        if not args.dry_run:
            for src, data in ((p, keep), (probed_p, keep_probed)):
                bak = src.with_suffix(src.suffix + ".bak-unchecked-curation")
                if not bak.exists():
                    shutil.copy2(src, bak)
                json.dump(data, open(src, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    out_log = _REPO / "audit" / "unchecked_curation_log.csv"
    out_hold = _REPO / "audit" / "unchecked_E_handcheck.csv"
    if not args.dry_run:
        with open(out_log, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["dataset", "graph", "row_id", "source_id", "strategy", "source",
                        "from", "to", "class", "action"])
            w.writerows(log_rows)
        with open(out_hold, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(hold_rows[0].keys()))
            w.writeheader()
            w.writerows(hold_rows)
    c = Counter(r[-1] for r in log_rows)
    print("\nactions:", dict(c))
    print(f"log: {out_log}\nE-class handcheck sheet: {out_hold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
