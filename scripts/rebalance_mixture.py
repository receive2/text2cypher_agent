#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebalance_mixture.py
====================
Close the typo over-representation by **lossless scarcity-first reallocation**
(the applicability-ceiling measurement in audit/APPLICABILITY_CEILING.md showed
supply >= the 22.5% targets; no rows need deleting).

Phases:
  --gate    Re-run the full candidate gate (shape rules + DB collision via the
            live graphs) over attested forms + ALL probe proposals ->
            audit/ceiling_gated.jsonl  (run after any new probe pass).
  --apply   Assign conversions under global quotas and rewrite the datasets.

Assignment policy (documented for the paper):
  * targets: alias/abbrev -> 22.5% of N, with +10% overshoot to absorb the
    expected human-census attrition of newly converted items;
  * abbrev first (scarcer supply), then alias;
  * donor preference: typo rows (the surplus) -> casing (floor: casing stays
    >= 10.0%) -> partial (floor: partial stays >= 18.0%);
  * dual-candidate rows go to whichever quota is hungrier at that moment;
  * every conversion re-passes shape + DB validity + boundary-aware splice at
    apply time; failures leave the row unchanged.
Provenance: forms found in the KB are tagged with their kb source
(no verification flag; they are Tier-1-censused via provenance); LLM-probed
forms carry evidence + proposer_model and needs_verification=True.

Backups: *.bak-rebalance. Log: audit/rebalance_log.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_REPO / ".env")

import eval_config as cfg  # noqa: E402
from data_augmentation import validity as V  # noqa: E402
from data_augmentation.kb_aliases import AliasProvider  # noqa: E402
from data_augmentation.pipeline import _replace_all  # noqa: E402
from data_augmentation.validity import Neo4jValueProvider  # noqa: E402
from grounding_probe import _classify as probe_classify  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
ATTESTED = _REPO / "audit" / "ceiling_attested.jsonl"
PROBE = _REPO / "audit" / "ceiling_probe.jsonl"
GATED = _REPO / "audit" / "ceiling_gated.jsonl"
LOG = _REPO / "audit" / "rebalance_log.csv"
_NL_KEYS = ("nl", "question", "nl_question")
SYN = {"pole", "er", "bloom"}
TARGET = 0.225
OVERSHOOT = 1.10
CASING_FLOOR = 0.100
PARTIAL_FLOOR = 0.180


def _canon(s):
    return re.sub(r"^the\s+", "", (s or "").strip().lower()).strip(" '\"")


def _conn_for(graph):
    for ds in ("cypherbench", "mindthequery", "zograscope"):
        if (ds, graph) in cfg.GRAPH_CONNS:
            return cfg.GRAPH_CONNS[(ds, graph)]
    raise KeyError(graph)


class Ctx:
    def __init__(self):
        self.drivers, self.providers, self.kb = {}, {}, {}

    def db(self, g):
        if g not in self.providers:
            c = _conn_for(g)
            self.drivers[g] = GraphDatabase.driver(c.uri, auth=(c.user, c.password))
            self.providers[g] = Neo4jValueProvider(self.drivers[g], "neo4j")
        return self.providers[g]

    def aliases(self, g):
        if g not in self.kb:
            self.kb[g] = AliasProvider(graph=g)
        return self.kb[g]

    def close(self):
        for d in self.drivers.values():
            d.close()


def gate() -> int:
    ctx = Ctx()
    rows = [json.loads(l) for l in open(ATTESTED, encoding="utf-8")]
    probes = {}
    for l in open(PROBE, encoding="utf-8"):
        r = json.loads(l)
        if "error" not in r:
            probes[r["key"]] = r
    out, stats = [], defaultdict(Counter)
    for r in rows:
        g, ent = r["graph"], r["entity"]
        lbl, prop = r.get("label"), r.get("prop")
        rec = {**r}
        for kind in ("abbrev", "alias"):
            if kind == "alias" and g in SYN:
                rec[f"gated_{kind}"] = None
                continue
            cands = list(r.get(f"{kind}_forms") or [])
            p = probes.get(f"{g}|{ent}")
            if p and p.get(kind):
                cands.append(p[kind])
            passed = None
            for f in cands:
                if _canon(f) == _canon(ent):
                    continue
                if kind == "alias" and _canon(ent) and _canon(ent) in _canon(f):
                    continue
                ok, reason = V.check_validity(kind, f, ent, lbl, prop, ctx.db(g))
                if ok and reason != V.UNCHECKED:
                    passed = f
                    break
            rec[f"gated_{kind}"] = passed
        out.append(rec)
        stats[r["graph"]]["n"] += 1
        if rec.get("gated_abbrev"):
            stats[r["graph"]]["ab"] += 1
        if rec.get("gated_alias"):
            stats[r["graph"]]["al"] += 1
    ctx.close()
    with open(GATED, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    N = sum(s["n"] for s in stats.values())
    print(f"gate: {N} rows; gated abbrev {sum(s['ab'] for s in stats.values())}, "
          f"gated alias {sum(s['al'] for s in stats.values())} -> {GATED}")
    return 0


def apply_() -> int:
    rows = [json.loads(l) for l in open(GATED, encoding="utf-8")]
    probes = {}
    for l in open(PROBE, encoding="utf-8"):
        r = json.loads(l)
        if "error" not in r:
            probes[r["key"]] = r
    N = len(rows)
    cur = Counter(r["strategy"] for r in rows)
    goal = {k: min(int(N * TARGET * OVERSHOOT), N) for k in ("abbrev", "alias")}
    need = {k: max(0, goal[k] - cur[k]) for k in ("abbrev", "alias")}
    caps = {"casing": max(0, cur["casing"] - int(N * CASING_FLOOR) - 1),
            "partial": max(0, cur["partial"] - int(N * PARTIAL_FLOOR) - 1),
            "typo": 10**9}
    print(f"quotas: need abbrev +{need['abbrev']}, alias +{need['alias']}; "
          f"donor caps: {caps}")

    donors = [r for r in rows if r["strategy"] in ("typo", "casing", "partial")
              and (r.get("gated_abbrev") or r.get("gated_alias"))]
    # deterministic order: typo first, then casing, then partial; stable by id
    order = {"typo": 0, "casing": 1, "partial": 2}
    donors.sort(key=lambda r: (order[r["strategy"]], r["row_id"]))

    donated = Counter()
    plan = {}          # row_id -> (kind, form)
    for kind in ("abbrev", "alias"):     # abbrev first: scarcer
        for r in donors:
            if need[kind] <= 0:
                break
            rid = r["row_id"]
            if rid in plan:
                continue
            form = r.get(f"gated_{kind}")
            if not form:
                continue
            s = r["strategy"]
            if donated[s] >= caps[s]:
                continue
            plan[rid] = (kind, form)
            donated[s] += 1
            need[kind] -= 1
    print(f"planned conversions: {len(plan)} "
          f"(donated from: {dict(donated)}; unmet: {dict(need)})")

    ctx = Ctx()
    log, actions = [], Counter()
    for ds, path in _DATASETS.items():
        p = Path(path)
        probed_p = p.with_name("test.probed.json")
        data = json.load(open(p, encoding="utf-8"))
        probed = json.load(open(probed_p, encoding="utf-8"))
        for i, (x, xp) in enumerate(zip(data, probed)):
            rid = f"{ds}:{i}"
            if rid not in plan:
                continue
            kind, form = plan[rid]
            meta = x.get("_aug_meta") or {}
            e = (meta.get("edits") or [{}])[0]
            g = meta.get("graph", "")
            frm = e.get("from", "")
            original_nl = meta.get("original_nl") or ""
            # re-verify at apply time
            if kind == "alias" and _canon(frm) and _canon(frm) in _canon(form):
                actions["skip:contains_original"] += 1
                continue
            ok, reason = V.check_validity(kind, form, frm, e.get("label"),
                                          e.get("prop"), ctx.db(g))
            if not ok or reason == V.UNCHECKED:
                actions[f"skip:{reason}"] += 1
                continue
            new_nl = _replace_all(original_nl, frm, form)
            if new_nl is None:
                actions["skip:splice"] += 1
                continue
            # provenance: attested if the form is in the KB for this entity
            kb = ctx.aliases(g)
            pairs = kb.abbrevs(frm) if kind == "abbrev" else kb.aliases(frm)
            src = next((s for f2, s in pairs if _canon(f2) == _canon(form)), None)
            is_llm = src is None
            old_strat, old_to = e.get("strategy"), e.get("to")
            for obj in (x, xp):
                m = obj.get("_aug_meta") or {}
                ed = (m.get("edits") or [{}])[0]
                ed.update({"strategy": kind, "to": form,
                           "validity": reason,
                           "source": "llm" if is_llm else src,
                           "needs_verification": is_llm,
                           "regenerated": "rebalance_2026-08"})
                if is_llm:
                    ed["proposer_model"] = "claude-opus-5"
                    ed["evidence"] = (probes.get(f"{g}|{frm}") or {}).get("evidence", "")
                else:
                    ed.pop("proposer_model", None)
                    ed.pop("evidence", None)
                if "grounding_probe" in ed:
                    ed["grounding_probe"] = probe_classify(frm, form)
                for k in _NL_KEYS:
                    if isinstance(obj.get(k), str) and obj[k] != original_nl:
                        obj[k] = new_nl
            actions[f"converted:{old_strat}->{kind}:{'llm' if is_llm else 'attested'}"] += 1
            log.append([ds, g, rid, old_strat, frm, old_to, kind, form,
                        "llm" if is_llm else src, reason])
        for src_p, d in ((p, data), (probed_p, probed)):
            bak = src_p.with_suffix(src_p.suffix + ".bak-rebalance")
            if not bak.exists():
                shutil.copy2(src_p, bak)
            json.dump(d, open(src_p, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    ctx.close()
    with open(LOG, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "graph", "row_id", "old_strategy", "from",
                    "old_to", "new_strategy", "new_to", "source", "validity"])
        w.writerows(log)
    print("\nactions:", dict(actions))
    print(f"log: {LOG}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.gate:
        return gate()
    if args.apply:
        return apply_()
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
