#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_unchecked_validity.py
==============================
Re-run the DB validity checks for the v2 edits that shipped ``validity ==
"unchecked"`` (the generation-time extractor could not resolve a (label, prop)
for the entity, so the value set was empty and collision/uniqueness/margin
never executed — see data_augmentation/validity.py).

Resolution fallback: instead of parsing the gold Cypher, ask the live graph
directly *where the canonical value is stored* — over **node** properties AND
**relationship** properties (the original extractor only handles node
patterns, which is why zograscope/pole dominates the unchecked set). Every
(kind, label/type, prop) whose values contain the canonical string becomes a
resolution context; the edit must pass ``check_validity`` in ALL contexts
(conservative).

Outcomes per edit
-----------------
* ``auto_ok_casing``   — casing edits: identity-preserving, vacuously safe.
* ``ok_backfilled``    — resolved and passed the strategy's checks.
* ``fail:<reason>``    — resolved and FAILED (collision / not_unique / margin)
                          → recommend drop (see the drop list).
* ``unresolved``       — canonical value not found anywhere in the graph
                          → conservative: recommend drop or human review.

Read-only w.r.t. the datasets: writes ``audit/unchecked_backfill.jsonl`` and a
markdown summary; never edits test.json.

Usage:  python scripts/backfill_unchecked_validity.py [--graph pole] [--out audit/unchecked_backfill.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import eval_config as cfg  # noqa: E402
from data_augmentation.validity import InMemoryValueProvider, check_validity  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}


def _load_unchecked(only_graph: Optional[str]) -> List[dict]:
    out = []
    for ds, path in _DATASETS.items():
        rows = json.load(open(path, encoding="utf-8"))
        for i, x in enumerate(rows):
            meta = x.get("_aug_meta") or {}
            edits = meta.get("edits") or []
            if not edits:
                continue
            e = edits[0]
            if e.get("validity") != "unchecked":
                continue
            graph = meta.get("graph") or x.get("graph", "")
            if only_graph and graph != only_graph:
                continue
            out.append({
                "row_id": f"{ds}:{i}",
                "source_id": str(x.get("id") or x.get("qid") or ""),
                "dataset": ds, "graph": graph,
                "strategy": e.get("strategy"), "source": e.get("source"),
                "from": e.get("from"), "to": e.get("to"),
            })
    return out


def _conn_for(ds: str, graph: str):
    for key in ((ds, graph), (ds.replace("_augmented", ""), graph)):
        if key in cfg.GRAPH_CONNS:
            return cfg.GRAPH_CONNS[key]
    raise KeyError(f"no GRAPH_CONNS entry for {(ds, graph)}")


class GraphIndex:
    """Per-graph: schema discovery, canonical-value resolution, value pulls."""

    def __init__(self, driver, database: str = "neo4j"):
        self._drv = driver
        self._db = database
        self._contexts: Optional[List[Tuple[str, str, str]]] = None  # (kind, label, prop)
        self._values: Dict[Tuple[str, str, str], frozenset] = {}

    def _run(self, q: str, **params):
        with self._drv.session(database=self._db) as s:
            return [r.data() for r in s.run(q, **params)]

    def contexts(self) -> List[Tuple[str, str, str]]:
        if self._contexts is not None:
            return self._contexts
        ctx: List[Tuple[str, str, str]] = []
        for r in self._run("CALL db.schema.nodeTypeProperties() "
                           "YIELD nodeLabels, propertyName, propertyTypes "
                           "RETURN nodeLabels, propertyName, propertyTypes"):
            types = r["propertyTypes"] or []
            for lbl in r["nodeLabels"]:
                if "String" in types:
                    ctx.append(("node", lbl, r["propertyName"]))
                if any("StringArray" in t or "List" in t for t in types):
                    ctx.append(("node_arr", lbl, r["propertyName"]))
        for r in self._run("CALL db.schema.relTypeProperties() "
                           "YIELD relType, propertyName, propertyTypes "
                           "RETURN relType, propertyName, propertyTypes"):
            types = r["propertyTypes"] or []
            rt = (r["relType"] or "").strip(":`")
            if r["propertyName"]:
                if "String" in types:
                    ctx.append(("rel", rt, r["propertyName"]))
                if any("StringArray" in t or "List" in t for t in types):
                    ctx.append(("rel_arr", rt, r["propertyName"]))
        self._contexts = sorted(set(ctx))
        return self._contexts

    def resolve(self, canonicals: List[str]) -> Dict[str, List[Tuple[str, str, str]]]:
        """value(lower) -> contexts where it is stored (ci match)."""
        want = {c.lower() for c in canonicals}
        hits: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
        for kind, lbl, prop in self.contexts():
            if kind == "node":
                q = (f"MATCH (n:`{lbl}`) WHERE n.`{prop}` IS NOT NULL "
                     f"WITH DISTINCT toLower(toString(n.`{prop}`)) AS v "
                     f"WHERE v IN $want RETURN v")
            elif kind == "node_arr":
                q = (f"MATCH (n:`{lbl}`) WHERE n.`{prop}` IS NOT NULL "
                     f"UNWIND n.`{prop}` AS e "
                     f"WITH DISTINCT toLower(toString(e)) AS v "
                     f"WHERE v IN $want RETURN v")
            elif kind == "rel":
                q = (f"MATCH ()-[r:`{lbl}`]->() WHERE r.`{prop}` IS NOT NULL "
                     f"WITH DISTINCT toLower(toString(r.`{prop}`)) AS v "
                     f"WHERE v IN $want RETURN v")
            else:  # rel_arr
                q = (f"MATCH ()-[r:`{lbl}`]->() WHERE r.`{prop}` IS NOT NULL "
                     f"UNWIND r.`{prop}` AS e "
                     f"WITH DISTINCT toLower(toString(e)) AS v "
                     f"WHERE v IN $want RETURN v")
            for r in self._run(q, want=list(want)):
                hits[r["v"]].append((kind, lbl, prop))
        return hits

    def values(self, ctx: Tuple[str, str, str]) -> frozenset:
        if ctx in self._values:
            return self._values[ctx]
        kind, lbl, prop = ctx
        if kind == "node":
            q = (f"MATCH (n:`{lbl}`) WHERE n.`{prop}` IS NOT NULL "
                 f"RETURN DISTINCT toString(n.`{prop}`) AS v")
        elif kind == "node_arr":
            q = (f"MATCH (n:`{lbl}`) WHERE n.`{prop}` IS NOT NULL "
                 f"UNWIND n.`{prop}` AS e RETURN DISTINCT toString(e) AS v")
        elif kind == "rel":
            q = (f"MATCH ()-[r:`{lbl}`]->() WHERE r.`{prop}` IS NOT NULL "
                 f"RETURN DISTINCT toString(r.`{prop}`) AS v")
        else:  # rel_arr
            q = (f"MATCH ()-[r:`{lbl}`]->() WHERE r.`{prop}` IS NOT NULL "
                 f"UNWIND r.`{prop}` AS e RETURN DISTINCT toString(e) AS v")
        vals = frozenset(r["v"] for r in self._run(q) if isinstance(r["v"], str) and r["v"].strip())
        self._values[ctx] = vals
        return vals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default=None)
    ap.add_argument("--out", default="audit/unchecked_backfill.jsonl")
    args = ap.parse_args()

    edits = _load_unchecked(args.graph)
    print(f"unchecked edits to backfill: {len(edits)}")

    by_graph: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for e in edits:
        by_graph[(e["dataset"], e["graph"])].append(e)

    results: List[dict] = []
    for (ds, graph), items in sorted(by_graph.items()):
        casings = [e for e in items if e["strategy"] == "casing"]
        rest = [e for e in items if e["strategy"] != "casing"]
        for e in casings:
            results.append({**e, "result": "auto_ok_casing", "contexts": []})
        if not rest:
            print(f"  {ds}/{graph}: {len(casings)} casing auto-ok, 0 to query")
            continue
        conn = _conn_for(ds, graph)
        drv = GraphDatabase.driver(conn.uri, auth=(conn.user, conn.password))
        try:
            gi = GraphIndex(drv, getattr(conn, "database", None) or "neo4j")
            resolution = gi.resolve([e["from"] for e in rest])
            n_ok = n_fail = n_unres = 0
            for e in rest:
                ctxs = resolution.get((e["from"] or "").lower(), [])
                if not ctxs:
                    results.append({**e, "result": "unresolved", "contexts": []})
                    n_unres += 1
                    continue
                verdicts = []
                for ctx in ctxs:
                    provider = InMemoryValueProvider({(ctx[1], ctx[2]): gi.values(ctx)})
                    ok, reason = check_validity(e["strategy"], e["to"], e["from"],
                                                ctx[1], ctx[2], provider)
                    verdicts.append((ctx, ok, reason))
                bad = [v for v in verdicts if not v[0] or v[2] == "unchecked"]
                hard_fail = [v for v in verdicts if not v[0]]
                if hard_fail:
                    reason = hard_fail[0][2]
                    results.append({**e, "result": f"fail:{reason}",
                                    "contexts": [list(v[0]) for v in verdicts],
                                    "detail": [[list(c), o, r] for c, o, r in verdicts]})
                    n_fail += 1
                elif bad:
                    results.append({**e, "result": "unresolved",
                                    "contexts": [list(v[0]) for v in verdicts]})
                    n_unres += 1
                else:
                    results.append({**e, "result": "ok_backfilled",
                                    "contexts": [list(v[0]) for v in verdicts]})
                    n_ok += 1
            print(f"  {ds}/{graph}: {len(casings)} casing | ok {n_ok} | fail {n_fail} | unresolved {n_unres}")
        finally:
            drv.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    c = Counter(r["result"].split(":")[0] for r in results)
    cf = Counter(r["result"] for r in results if r["result"].startswith("fail"))
    print("\n== summary ==")
    for k, v in c.most_common():
        print(f"  {v:4d}  {k}")
    if cf:
        print("  fail reasons:", dict(cf))
    drop = [r for r in results if r["result"].startswith("fail") or r["result"] == "unresolved"]
    print(f"\nrecommend-drop (fail + unresolved): {len(drop)}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
