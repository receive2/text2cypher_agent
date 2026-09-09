#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regenerate_partials.py
======================
Re-apply the PATCHED partial rules (status-sentence guard, edge-punctuation
tokenization, bare-number/too-short/unbalanced output guards, DB-grounded
distinctive-token requirement — see data_augmentation/augmenters/partial_name.py)
to every **algorithmic partial** edit in the v2 datasets.

Per row:
  1. If the CURRENT perturbed form already satisfies the new rules (output
     guards + distinctive token + DB checks) → keep unchanged (minimal churn).
  2. Else regenerate with the patched augmenter (LLM disabled).
  3. Else fall back to another **algorithmic** strategy (typo, then casing) —
     never attested/LLM, so the human-verification census does not grow.
  4. Else drop the row (logged).

Everything runs against the live graphs (Neo4jValueProvider). Deterministic via
row_rng(DEFAULT_SEED, dataset, row_id). Applies to test.json and (in lockstep)
test.probed.json; regenerated edits get a fresh `grounding_probe` class.
Writes audit/partial_regen_log.csv. Backups: *.bak-partial-regen (once).

Usage:  python scripts/regenerate_partials.py [--dry-run]
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
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import eval_config as cfg  # noqa: E402
from data_augmentation import validity as V  # noqa: E402
from data_augmentation.augmenters import STRATEGY_REGISTRY, AugContext  # noqa: E402
from data_augmentation.augmenters.partial_name import (  # noqa: E402
    _TOKEN_RE, _clean, _distinctive_token, partial_eligible,
)
from data_augmentation.config import DEFAULT_SEED, SYNTHETIC_GRAPHS  # noqa: E402
from data_augmentation.pipeline import _replace_all, row_rng  # noqa: E402
from data_augmentation.validity import Neo4jValueProvider  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

sys.path.insert(0, str(_REPO / "scripts"))
from grounding_probe import _classify as probe_classify  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
_NL_KEYS = ("nl", "question", "nl_question")
_LLM_OFF = SimpleNamespace(enabled=False)


def _conn_for(graph: str):
    for ds in ("cypherbench", "mindthequery", "zograscope"):
        if (ds, graph) in cfg.GRAPH_CONNS:
            return cfg.GRAPH_CONNS[(ds, graph)]
    raise KeyError(graph)


class Providers:
    """One driver + cached ValueProvider per graph."""
    def __init__(self):
        self._drv, self._prov = {}, {}

    def get(self, graph: str) -> Neo4jValueProvider:
        if graph not in self._prov:
            c = _conn_for(graph)
            self._drv[graph] = GraphDatabase.driver(c.uri, auth=(c.user, c.password))
            self._prov[graph] = Neo4jValueProvider(self._drv[graph], "neo4j")
        return self._prov[graph]

    def close(self):
        for d in self._drv.values():
            d.close()


def _current_ok(frm: str, to: str, label, prop, provider) -> bool:
    """Does the EXISTING perturbed form satisfy the new rules?"""
    toks = _TOKEN_RE.findall(frm)
    if not partial_eligible(frm):
        return False
    if _clean(to.split(), frm) != to:          # output guards, verbatim survival
        return False
    vals = provider.values(label, prop) if provider else None
    distinctive = _distinctive_token(toks, vals)
    if distinctive and distinctive.lower() not in to.lower():
        return False
    ok, reason = V.check_validity("partial", to, frm, label, prop, provider)
    return ok and reason != V.UNCHECKED


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    providers = Providers()
    log, actions = [], Counter()
    try:
        for ds, path in _DATASETS.items():
            p = Path(path)
            probed_p = p.with_name("test.probed.json")
            rows = json.load(open(p, encoding="utf-8"))
            probed = json.load(open(probed_p, encoding="utf-8"))
            keep, keep_pr = [], []
            for x, xp in zip(rows, probed):
                meta = x.get("_aug_meta") or {}
                e = (meta.get("edits") or [{}])[0]
                if not (e.get("strategy") == "partial" and e.get("source") == "algorithmic"):
                    keep.append(x); keep_pr.append(xp)
                    continue
                graph = meta.get("graph", "")
                frm, old_to = e.get("from", ""), e.get("to", "")
                label, prop = e.get("label"), e.get("prop")
                original_nl = meta.get("original_nl") or ""
                if not (frm and original_nl and prop):
                    actions["skipped_no_meta"] += 1     # backfill-verified rows w/o (label,prop)
                    keep.append(x); keep_pr.append(xp)
                    continue
                provider = providers.get(graph)
                if _current_ok(frm, old_to, label, prop, provider):
                    actions["kept"] += 1
                    keep.append(x); keep_pr.append(xp)
                    continue

                # regenerate: patched partial, then typo, then casing
                rng = row_rng(DEFAULT_SEED, ds, x.get("id") or x.get("qid") or frm)
                ctx = AugContext(nl=original_nl, rng=rng, llm=_LLM_OFF,
                                 label=label, prop=prop, entity_type="name",
                                 graph=graph,
                                 synthetic_domain=graph in SYNTHETIC_GRAPHS,
                                 values=provider, aliases=None)
                new_edit = None
                for strat in ("partial", "typo", "casing"):
                    prop_obj = STRATEGY_REGISTRY[strat]().apply(frm, ctx)
                    if prop_obj is None or prop_obj.surface == frm:
                        continue
                    ok, reason = V.check_validity(strat, prop_obj.surface, frm,
                                                  label, prop, provider)
                    if not ok or reason == V.UNCHECKED:
                        continue
                    new_nl = _replace_all(original_nl, frm, prop_obj.surface)
                    if new_nl is None:
                        continue
                    new_edit = (strat, prop_obj.surface, new_nl, reason)
                    break

                if new_edit is None:
                    actions["dropped"] += 1
                    log.append([ds, graph, str(x.get("id") or x.get("qid") or ""),
                                frm, old_to, "dropped", "", ""])
                    continue
                strat, new_to, new_nl, reason = new_edit
                act = "regen_partial" if strat == "partial" else f"fallback_{strat}"
                actions[act] += 1
                log.append([ds, graph, str(x.get("id") or x.get("qid") or ""),
                            frm, old_to, act, new_to, reason])
                for row, twin in ((x, xp),):
                    for obj in (row, twin):
                        m = obj.get("_aug_meta") or {}
                        ed = (m.get("edits") or [{}])[0]
                        ed.update({"strategy": strat, "to": new_to, "validity": reason,
                                   "regenerated": "partial_rules_v2.1"})
                        if "grounding_probe" in ed:
                            ed["grounding_probe"] = probe_classify(frm, new_to)
                    for k in _NL_KEYS:
                        if isinstance(row.get(k), str) and row[k] != original_nl:
                            row[k] = new_nl
                        if isinstance(twin.get(k), str) and twin[k] != original_nl:
                            twin[k] = new_nl
                keep.append(x); keep_pr.append(xp)

            print(f"{ds}: {len(rows)} -> {len(keep)}")
            if not args.dry_run:
                for src, data in ((p, keep), (probed_p, keep_pr)):
                    bak = src.with_suffix(src.suffix + ".bak-partial-regen")
                    if not bak.exists():
                        shutil.copy2(src, bak)
                    json.dump(data, open(src, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
    finally:
        providers.close()

    print("\nactions:", dict(actions))
    out = _REPO / "audit" / "partial_regen_log.csv"
    if not args.dry_run:
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["dataset", "graph", "source_id", "from", "old_to",
                        "action", "new_to", "validity"])
            w.writerows(log)
        print(f"log: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
