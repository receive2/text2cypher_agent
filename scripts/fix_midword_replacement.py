#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_midword_replacement.py
==========================
Repair the mid-word replacement corruption ("us" replaced inside "users" ->
"United Statesers").  ``pipeline._occurrences`` was substring-based; it is now
word-boundary-aware (trailing plural ``s`` allowed).  This script recomputes
every row's question text from ``_aug_meta.original_nl`` with the fixed
``_replace_all`` and:

  * unchanged  -> row untouched;
  * changed    -> question text updated in test.json + test.probed.json;
  * no valid occurrence left (the surface only ever appeared mid-word) ->
    row DROPPED (its question cannot carry the perturbation).

Backups: *.bak-midword-fix (once). Log: audit/midword_fix_log.csv.
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import Counter
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
_NL_KEYS = ("nl", "question", "nl_question")


def main() -> int:
    log, actions = [], Counter()
    for ds, path in _DATASETS.items():
        p = Path(path)
        probed_p = p.with_name("test.probed.json")
        rows = json.load(open(p, encoding="utf-8"))
        probed = json.load(open(probed_p, encoding="utf-8"))
        keep, keep_pr = [], []
        for x, xp in zip(rows, probed):
            meta = x.get("_aug_meta") or {}
            e = (meta.get("edits") or [{}])[0]
            frm, to = e.get("from"), e.get("to")
            original_nl = meta.get("original_nl") or ""
            if not (frm and to and original_nl):
                actions["skipped_no_meta"] += 1
                keep.append(x); keep_pr.append(xp)
                continue
            new_nl = _replace_all(original_nl, frm, to)
            cur_nl = next((x[k] for k in _NL_KEYS if isinstance(x.get(k), str)), "")
            if new_nl is None:
                # surface never occurs at a word boundary -> unperturbable
                actions["dropped_unperturbable"] += 1
                log.append([ds, meta.get("graph", ""), str(x.get("id") or x.get("qid") or ""),
                            e.get("strategy"), frm, to, "dropped", cur_nl[:120]])
                continue
            if new_nl == cur_nl:
                actions["unchanged"] += 1
                keep.append(x); keep_pr.append(xp)
                continue
            actions["repaired"] += 1
            log.append([ds, meta.get("graph", ""), str(x.get("id") or x.get("qid") or ""),
                        e.get("strategy"), frm, to, "repaired", new_nl[:120]])
            for obj in (x, xp):
                for k in _NL_KEYS:
                    if isinstance(obj.get(k), str) and obj[k] != (obj.get("_aug_meta") or {}).get("original_nl"):
                        obj[k] = new_nl
            keep.append(x); keep_pr.append(xp)

        print(f"{ds}: {len(rows)} -> {len(keep)}")
        for src, data in ((p, keep), (probed_p, keep_pr)):
            bak = src.with_suffix(src.suffix + ".bak-midword-fix")
            if not bak.exists():
                shutil.copy2(src, bak)
            json.dump(data, open(src, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)

    out = _REPO / "audit" / "midword_fix_log.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "graph", "source_id", "strategy", "from", "to",
                    "action", "new_or_old_nl"])
        w.writerows(log)
    print("\nactions:", dict(actions))
    print(f"log: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
