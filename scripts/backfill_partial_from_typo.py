#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_partial_from_typo.py
=============================
Final mixture lever (external review item #2): convert every typo row whose
entity is partial-eligible AND yields a fully-gated partial form (patched
rules: distinctive token, output guards, DB uniqueness, boundary-aware splice)
into a **partial** row.  Deterministic (per-row seeded RNG, sorted order),
algorithmic provenance -> Tier-2 sampled, zero census growth.

The diagnostic measured 95 such rows (< the 208 needed for the 22.5% target):
this pass therefore fills partial **to measured supply exhaustion**, giving
partial the same defense as alias (supply ceiling, not an arbitrary floor).

Backups: *.bak-partial-backfill. Log: audit/partial_backfill_log.csv.
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_REPO / ".env")

import eval_config as cfg  # noqa: E402
from data_augmentation import validity as V  # noqa: E402
from data_augmentation.augmenters import STRATEGY_REGISTRY, AugContext  # noqa: E402
from data_augmentation.augmenters.partial_name import partial_eligible  # noqa: E402
from data_augmentation.config import DEFAULT_SEED, SYNTHETIC_GRAPHS  # noqa: E402
from data_augmentation.pipeline import _replace_all, row_rng  # noqa: E402
from grounding_probe import _classify as probe_classify  # noqa: E402
from rebalance_mixture import Ctx  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
_NL_KEYS = ("nl", "question", "nl_question")
LOG = _REPO / "audit" / "partial_backfill_log.csv"
_LLM_OFF = SimpleNamespace(enabled=False)


def main() -> int:
    ctx_db = Ctx()
    log, actions = [], Counter()
    try:
        for ds, path in _DATASETS.items():
            p = Path(path)
            probed_p = p.with_name("test.probed.json")
            data = json.load(open(p, encoding="utf-8"))
            probed = json.load(open(probed_p, encoding="utf-8"))
            for i, (x, xp) in enumerate(zip(data, probed)):
                meta = x.get("_aug_meta") or {}
                e = (meta.get("edits") or [{}])[0]
                if e.get("strategy") != "typo":
                    continue
                frm = e.get("from", "")
                onl = meta.get("original_nl") or ""
                if not (frm and onl and e.get("prop")):
                    continue
                if len(frm.split()) < 2 or not partial_eligible(frm):
                    continue
                g = meta.get("graph", "")
                rng = row_rng(DEFAULT_SEED, ds, x.get("id") or x.get("qid") or frm)
                actx = AugContext(nl=onl, rng=rng, llm=_LLM_OFF,
                                  label=e.get("label"), prop=e.get("prop"),
                                  entity_type="name", graph=g,
                                  synthetic_domain=g in SYNTHETIC_GRAPHS,
                                  values=ctx_db.db(g), aliases=None)
                po = STRATEGY_REGISTRY["partial"]().apply(frm, actx)
                if po is None or po.surface == frm or po.source == "llm":
                    continue
                ok, reason = V.check_validity("partial", po.surface, frm,
                                              e.get("label"), e.get("prop"),
                                              ctx_db.db(g))
                if not ok or reason == V.UNCHECKED:
                    continue
                new_nl = _replace_all(onl, frm, po.surface)
                if new_nl is None:
                    continue
                old_to = e.get("to")
                for obj in (x, xp):
                    m = obj.get("_aug_meta") or {}
                    ed = (m.get("edits") or [{}])[0]
                    ed.update({"strategy": "partial", "to": po.surface,
                               "validity": reason, "source": "algorithmic",
                               "needs_verification": False,
                               "regenerated": "partial_backfill_2026-08"})
                    ed.pop("proposer_model", None)
                    ed.pop("evidence", None)
                    if "grounding_probe" in ed:
                        ed["grounding_probe"] = probe_classify(frm, po.surface)
                    for k in _NL_KEYS:
                        if isinstance(obj.get(k), str) and obj[k] != onl:
                            obj[k] = new_nl
                actions["converted"] += 1
                log.append([ds, g, f"{ds}:{i}", frm, old_to, po.surface, reason])
            for src_p, d in ((p, data), (probed_p, probed)):
                bak = src_p.with_suffix(src_p.suffix + ".bak-partial-backfill")
                if not bak.exists():
                    shutil.copy2(src_p, bak)
                json.dump(d, open(src_p, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
    finally:
        ctx_db.close()
    with open(LOG, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "graph", "row_id", "from", "old_typo", "new_partial", "validity"])
        w.writerows(log)
    print("actions:", dict(actions))
    print(f"log: {LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
