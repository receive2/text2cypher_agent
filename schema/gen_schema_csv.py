#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_schema_csv.py
=================
Introspects a live Neo4j database and writes two CSV files that document
the complete graph schema:

  schema_nodes.csv
      One row per (node label × property) pair.

      Columns:
        label           – node label, e.g. ``Movie``
        property        – property name, e.g. ``title``
        property_types  – Neo4j data type(s), e.g. ``String``
        mandatory       – True / False
        node_count      – total nodes with this label
        non_null_count  – nodes where this property is not null
        fill_pct        – non_null_count / node_count  (e.g. ``94.7%``)
        sample_values   – up to N representative values (pipe-separated)

  schema_relations.csv
      One row per (rel_type × from_label × to_label × property) combination.
      Property-less (structural) relationships still get a row with empty
      property columns.

      Columns:
        rel_type        – relationship type, e.g. ``ACTED_IN``
        from_label      – start-node label, e.g. ``Person``
        to_label        – end-node label, e.g. ``Movie``
        property        – relationship property (empty if none)
        property_types  – Neo4j data type(s)
        mandatory       – True / False
        rel_count       – total relationships of this type
        sample_values   – up to N representative values

Usage
-----
  python gen_schema_csv.py
  python gen_schema_csv.py --nodes-output nodes.csv --rels-output rels.csv
  python gen_schema_csv.py --database movies --samples 5

Environment variables  (loaded from .env)
-----------------------------------------
  NEO4J_URI          bolt / neo4j+s URI            (required)
  NEO4J_USERNAME                                    (required)
  NEO4J_PASSWORD                                    (required)
  NEO4J_DATABASE     database name                 (default: neo4j)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Union

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from paths import SCHEMA_NODES_CSV, SCHEMA_RELS_CSV

load_dotenv()


# ──────────────────────────────────────────────────────────────────────────────
# Environment & driver helpers
# ──────────────────────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Set it in .env or your system environment."
        )
    return v


def _get_driver():
    """Build a Neo4j driver from environment variables."""
    return GraphDatabase.driver(
        _require_env("NEO4J_URI"),
        auth=(_require_env("NEO4J_USERNAME"), _require_env("NEO4J_PASSWORD")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# String-cleaning helpers
# ──────────────────────────────────────────────────────────────────────────────

def _clean_node_label(node_type: str) -> str:
    """
    Normalise a ``nodeType`` string from ``db.schema.nodeTypeProperties()``.

    Examples::

        ':Movie'           → 'Movie'
        ':`Person`'        → 'Person'
        ':Person:Employee' → 'Person'   (primary label only)
        'Movie'            → 'Movie'
    """
    s = node_type.strip().strip("`").lstrip(":").strip("`")
    # Multi-label: `:Person:Employee` — use the first one only.
    if ":" in s:
        s = s.split(":")[0]
    return s.strip()


def _clean_rel_type(raw: str) -> str:
    """Strip ``:`` prefix and backticks from a ``relType`` string."""
    return raw.strip().strip("`").lstrip(":").strip("`")


def _fmt_types(types: Any) -> str:
    """Format a ``propertyTypes`` list/scalar to a readable string."""
    if not types:
        return ""
    if isinstance(types, (list, tuple)):
        return ", ".join(str(t) for t in types)
    return str(types)


def _fmt_samples(values: List[Any], max_chars: int = 100) -> str:
    """Pipe-join a list of sample values, truncating if necessary."""
    parts = []
    for v in values:
        if v is None:
            continue
        s = str(v)
        if len(s) > 45:
            s = s[:42] + "…"
        parts.append(s)
    result = " | ".join(parts)
    if len(result) > max_chars:
        result = result[:max_chars - 1] + "…"
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Per-label / per-rel helpers
# ──────────────────────────────────────────────────────────────────────────────

def _node_count(session, label: str) -> int:
    safe = label.replace("`", "``")
    try:
        rec = session.run(f"MATCH (n:`{safe}`) RETURN count(n) AS cnt").single()
        return int(rec["cnt"]) if rec else 0
    except Exception:
        return -1


def _non_null_count(session, label: str, prop: str) -> int:
    safe = label.replace("`", "``")
    try:
        rec = session.run(
            f"MATCH (n:`{safe}`) WHERE n[$prop] IS NOT NULL RETURN count(n) AS cnt",
            prop=prop,
        ).single()
        return int(rec["cnt"]) if rec else 0
    except Exception:
        return -1


def _sample_node_values(session, label: str, prop: str, n: int) -> List[Any]:
    safe = label.replace("`", "``")
    try:
        rows = session.run(
            f"MATCH (n:`{safe}`) WHERE n[$prop] IS NOT NULL "
            "RETURN n[$prop] AS v ORDER BY rand() LIMIT $n",
            prop=prop, n=n,
        )
        return [r["v"] for r in rows]
    except Exception:
        return []


def _rel_count(session, rel_type: str) -> int:
    safe = rel_type.replace("`", "``")
    try:
        rec = session.run(
            f"MATCH ()-[r:`{safe}`]->() RETURN count(r) AS cnt"
        ).single()
        return int(rec["cnt"]) if rec else 0
    except Exception:
        return -1


def _sample_rel_values(session, rel_type: str, prop: str, n: int) -> List[Any]:
    safe = rel_type.replace("`", "``")
    try:
        rows = session.run(
            f"MATCH ()-[r:`{safe}`]->() WHERE r[$prop] IS NOT NULL "
            "RETURN r[$prop] AS v ORDER BY rand() LIMIT $n",
            prop=prop, n=n,
        )
        return [r["v"] for r in rows]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Node schema collection
# ──────────────────────────────────────────────────────────────────────────────

def collect_node_schema(
    driver,
    database: str,
    n_samples: int = 3,
) -> List[Dict[str, Any]]:
    """
    Return one dict per (node label × property) pair, enriched with
    node counts and sample values.

    Tries ``db.schema.nodeTypeProperties()`` (Neo4j 4.4+); falls back to
    scanning each label's ``keys(n)`` if the procedure is unavailable.

    Returns
    -------
    list of dicts, sorted by label then property.
    """
    # (label, prop, types_str, mandatory)
    schema_pairs: List[Tuple[str, str, str, bool]] = []
    seen_pairs:   Set[Tuple[str, str]]              = set()

    with driver.session(database=database) as session:

        # ── Primary: schema procedure ─────────────────────────────────────────
        try:
            records = list(session.run(
                "CALL db.schema.nodeTypeProperties() "
                "YIELD nodeType, propertyName, propertyTypes, mandatory "
                "RETURN nodeType, propertyName, propertyTypes, mandatory "
                "ORDER BY nodeType, propertyName"
            ))
            for r in records:
                label = _clean_node_label(str(r.get("nodeType") or ""))
                prop  = str(r.get("propertyName") or "").strip()
                if not label or not prop:
                    continue
                key = (label, prop)
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    schema_pairs.append((
                        label, prop,
                        _fmt_types(r.get("propertyTypes")),
                        bool(r.get("mandatory", False)),
                    ))

        except (Neo4jError, Exception):
            # ── Fallback: scan labels ─────────────────────────────────────────
            label_rows = list(session.run(
                "CALL db.labels() YIELD label RETURN label"
            ))
            for lr in label_rows:
                label = str(lr.get("label") or "").strip()
                if not label:
                    continue
                safe = label.replace("`", "``")
                for kr in session.run(
                    f"MATCH (n:`{safe}`) UNWIND keys(n) AS k RETURN DISTINCT k AS prop"
                ):
                    prop = str(kr.get("prop") or "").strip()
                    if prop:
                        key = (label, prop)
                        if key not in seen_pairs:
                            seen_pairs.add(key)
                            schema_pairs.append((label, prop, "", False))

        # ── Cache node counts (one query per label) ───────────────────────────
        label_counts: Dict[str, int] = {}
        for label in {lbl for lbl, _, _, _ in schema_pairs}:
            label_counts[label] = _node_count(session, label)

        # ── Enrich each (label, property) pair ────────────────────────────────
        rows: List[Dict[str, Any]] = []
        for label, prop, types_str, mandatory in schema_pairs:
            node_cnt     = label_counts.get(label, -1)
            non_null_cnt = _non_null_count(session, label, prop)
            fill_pct     = (
                f"{100 * non_null_cnt / node_cnt:.1f}%"
                if node_cnt > 0 and non_null_cnt >= 0
                else ""
            )
            samples = _sample_node_values(session, label, prop, n_samples)

            rows.append({
                "label":          label,
                "property":       prop,
                "property_types": types_str,
                "mandatory":      mandatory,
                "node_count":     node_cnt,
                "non_null_count": non_null_cnt,
                "fill_pct":       fill_pct,
                "sample_values":  _fmt_samples(samples),
            })

    return sorted(rows, key=lambda r: (r["label"], r["property"]))


# ──────────────────────────────────────────────────────────────────────────────
# Relation schema collection
# ──────────────────────────────────────────────────────────────────────────────

def collect_rel_schema(
    driver,
    database: str,
    n_samples: int = 3,
) -> List[Dict[str, Any]]:
    """
    Return one dict per (rel_type × from_label × to_label × property)
    combination.

    Property-less (structural) relationships produce a row with empty
    property/type/sample columns — they are included for completeness.

    Tries ``db.schema.relTypeProperties()`` first; falls back to scanning
    live relationships.

    Returns
    -------
    list of dicts, sorted by rel_type then from_label/to_label then property.
    """
    rows: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str, str]] = set()

    with driver.session(database=database) as session:

        # ── Step A: topology — (rel_type → [(from_label, to_label)]) ─────────
        topology: Dict[str, List[Tuple[str, str]]] = {}
        for r in session.run(
            "MATCH (a)-[r]->(b) "
            "RETURN DISTINCT type(r) AS relType, "
            "head(labels(a)) AS fromLabel, "
            "head(labels(b)) AS toLabel "
            "ORDER BY relType, fromLabel, toLabel"
        ):
            rt = _clean_rel_type(str(r.get("relType") or ""))
            fl = str(r.get("fromLabel") or "").strip()
            tl = str(r.get("toLabel")   or "").strip()
            if rt and fl and tl:
                topology.setdefault(rt, []).append((fl, tl))

        # ── Step B: relationship properties ───────────────────────────────────
        # rel_type → [(prop, types_str, mandatory)]
        rel_props: Dict[str, List[Tuple[str, str, bool]]] = {}

        try:
            records = list(session.run(
                "CALL db.schema.relTypeProperties() "
                "YIELD relType, propertyName, propertyTypes, mandatory "
                "WHERE propertyName IS NOT NULL "
                "RETURN relType, propertyName, propertyTypes, mandatory "
                "ORDER BY relType, propertyName"
            ))
            for r in records:
                rt   = _clean_rel_type(str(r.get("relType") or ""))
                prop = str(r.get("propertyName") or "").strip()
                if rt and prop:
                    rel_props.setdefault(rt, []).append((
                        prop,
                        _fmt_types(r.get("propertyTypes")),
                        bool(r.get("mandatory", False)),
                    ))

        except (Neo4jError, Exception):
            # Fallback: scan live relationship keys
            for r in session.run(
                "MATCH ()-[r]->() WHERE size(keys(r)) > 0 "
                "UNWIND keys(r) AS k "
                "RETURN DISTINCT type(r) AS relType, k AS prop "
                "ORDER BY relType, k"
            ):
                rt   = _clean_rel_type(str(r.get("relType") or ""))
                prop = str(r.get("prop") or "").strip()
                if rt and prop:
                    rel_props.setdefault(rt, []).append((prop, "", False))

        # ── Step C: cache relationship counts (one per rel type) ──────────────
        rel_counts: Dict[str, int] = {
            rt: _rel_count(session, rt) for rt in topology
        }

        # ── Step D: assemble rows ─────────────────────────────────────────────
        for rt in sorted(topology):
            rel_cnt = rel_counts.get(rt, -1)
            props   = rel_props.get(rt, [])

            for from_label, to_label in sorted(topology[rt]):
                if props:
                    for prop, types_str, mandatory in props:
                        key = (rt, from_label, to_label, prop)
                        if key in seen:
                            continue
                        seen.add(key)
                        samples = _sample_rel_values(session, rt, prop, n_samples)
                        rows.append({
                            "rel_type":       rt,
                            "from_label":     from_label,
                            "to_label":       to_label,
                            "property":       prop,
                            "property_types": types_str,
                            "mandatory":      mandatory,
                            "rel_count":      rel_cnt,
                            "sample_values":  _fmt_samples(samples),
                        })
                else:
                    # Structural relationship — no properties
                    key = (rt, from_label, to_label, "")
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "rel_type":       rt,
                        "from_label":     from_label,
                        "to_label":       to_label,
                        "property":       "",
                        "property_types": "",
                        "mandatory":      "",
                        "rel_count":      rel_cnt,
                        "sample_values":  "",
                    })

    return rows


# ──────────────────────────────────────────────────────────────────────────────
# CSV writers
# ──────────────────────────────────────────────────────────────────────────────

NODE_FIELDS = [
    "label", "property", "property_types", "mandatory",
    "node_count", "non_null_count", "fill_pct", "sample_values",
]

REL_FIELDS = [
    "rel_type", "from_label", "to_label",
    "property", "property_types", "mandatory",
    "rel_count", "sample_values",
]


def write_nodes_csv(rows: List[Dict[str, Any]], path: Union[str, Path]) -> None:
    """Write node schema rows to *path*."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NODE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_rels_csv(rows: List[Dict[str, Any]], path: Union[str, Path]) -> None:
    """Write relation schema rows to *path*."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ──────────────────────────────────────────────────────────────────────────────
# Pretty-print summary to stdout
# ──────────────────────────────────────────────────────────────────────────────

def _print_node_summary(rows: List[Dict[str, Any]]) -> None:
    """Print a compact table of node schema to stdout."""
    print(f"\n{'LABEL':<22} {'PROPERTY':<22} {'TYPES':<14} "
          f"{'NODES':>7} {'NON-NULL':>8} {'FILL':>7}  SAMPLE")
    print("─" * 100)
    for r in rows:
        print(
            f"{r['label']:<22} {r['property']:<22} {r['property_types']:<14} "
            f"{r['node_count']:>7} {r['non_null_count']:>8} {r['fill_pct']:>7}  "
            f"{r['sample_values'][:45]}"
        )


def _print_rel_summary(rows: List[Dict[str, Any]]) -> None:
    """Print a compact table of relation schema to stdout."""
    print(f"\n{'REL_TYPE':<20} {'FROM':<14} {'TO':<14} {'PROPERTY':<18} "
          f"{'TYPES':<12} {'COUNT':>7}  SAMPLE")
    print("─" * 110)
    for r in rows:
        print(
            f"{r['rel_type']:<20} {r['from_label']:<14} {r['to_label']:<14} "
            f"{r['property']:<18} {r['property_types']:<12} {str(r['rel_count']):>7}  "
            f"{r['sample_values'][:35]}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export Neo4j node + relation schema to CSV files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--nodes-output", default=str(SCHEMA_NODES_CSV), metavar="PATH",
        help="Output CSV for node schema",
    )
    p.add_argument(
        "--rels-output",  default=str(SCHEMA_RELS_CSV), metavar="PATH",
        help="Output CSV for relation schema",
    )
    p.add_argument(
        "--database", default=os.getenv("NEO4J_DATABASE", "neo4j"), metavar="DB",
        help="Neo4j database name",
    )
    p.add_argument(
        "--samples", type=int, default=3, metavar="N",
        help="Number of sample values to collect per property",
    )
    p.add_argument(
        "--print-summary", action="store_true",
        help="Print a human-readable schema table to stdout after writing CSVs",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    db   = args.database

    print(f"Connecting to Neo4j  (database={db!r}) …", flush=True)
    driver = _get_driver()

    try:
        print("Collecting node schema …", flush=True)
        node_rows = collect_node_schema(driver, db, n_samples=args.samples)
        print(f"  {len(node_rows):>4d} (label × property) pairs.", flush=True)

        print("Collecting relation schema …", flush=True)
        rel_rows  = collect_rel_schema(driver, db, n_samples=args.samples)
        print(f"  {len(rel_rows):>4d} relation rows.", flush=True)

    finally:
        driver.close()

    write_nodes_csv(node_rows, args.nodes_output)
    write_rels_csv(rel_rows,   args.rels_output)

    print(f"\n✓  Nodes CSV     → {args.nodes_output}", flush=True)
    print(f"✓  Relations CSV → {args.rels_output}",   flush=True)

    if args.print_summary:
        _print_node_summary(node_rows)
        _print_rel_summary(rel_rows)


if __name__ == "__main__":
    main()
