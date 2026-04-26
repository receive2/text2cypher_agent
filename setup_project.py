#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_project.py
================
One-click project setup.  Run this once after pointing the project at a new
Neo4j database and all required files will be generated automatically.

Steps executed (in order):
  1  Verify .env contains all required environment variables
  2  Test Neo4j connectivity
  3  Export schema to CSV files (schema_nodes.csv, schema_relations.csv)
  4  Generate schema_meta.json (LLM-inferred metadata: id_property, topics)
  5  Create Neo4j fulltext indexes for every node + relationship property
  6  Generate @tool functions  (generated_node_tools.py, generated_rel_tools.py)
  7  Generate config.py from scratch (system prompts + schema constants)
  8  Build the FAISS tool-selection index (faiss_tools_auto/)

Usage
-----
  python setup_project.py
  python setup_project.py --database my_db
  python setup_project.py --skip-faiss        # skip FAISS build (needs OpenAI key)
  python setup_project.py --verbose

Environment variables  (loaded from .env)
-----------------------------------------
  NEO4J_URI          bolt / neo4j+s URI  (required)
  NEO4J_USERNAME                         (required)
  NEO4J_PASSWORD                         (required)
  NEO4J_DATABASE     default: neo4j
  OPENAI_API_KEY                         (required for steps 6 and 7)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from typing import List

from dotenv import load_dotenv

load_dotenv(".env", override=True)


# ──────────────────────────────────────────────────────────────────────────────
# Console helpers
# ──────────────────────────────────────────────────────────────────────────────

_WIDTH = 70


def _header(title: str) -> None:
    print(f"\n{'─' * _WIDTH}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'─' * _WIDTH}", flush=True)


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}", flush=True)


def _warn(msg: str) -> None:
    print(f"  ⚠  {msg}", flush=True)


def _fail(msg: str) -> None:
    print(f"\n  ✗  {msg}", flush=True)


def _banner(title: str) -> None:
    border = "═" * _WIDTH
    print(f"\n{border}", flush=True)
    pad = (_WIDTH - len(title) - 2) // 2
    print(f"{'═' * pad} {title} {'═' * pad}", flush=True)
    print(f"{border}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 — Verify .env
# ──────────────────────────────────────────────────────────────────────────────

_REQUIRED_VARS = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"]
_OPTIONAL_VARS = ["NEO4J_DATABASE", "OPENAI_API_KEY", "OPENAI_BASE_URL",
                  "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
                  "AZURE_OPENAI_DEPLOYMENT"]


def step_check_env() -> str:
    """Return the database name after validating env vars."""
    _header("Step 1 / 8 — Checking environment variables")

    missing = [v for v in _REQUIRED_VARS if not os.getenv(v)]
    if missing:
        for v in missing:
            _fail(f"Missing required env var: {v}")
        print(
            "\n  Create a .env file in the project root with:\n"
            "    NEO4J_URI=bolt://localhost:7687\n"
            "    NEO4J_USERNAME=neo4j\n"
            "    NEO4J_PASSWORD=your-password\n"
            "    NEO4J_DATABASE=neo4j\n"
            "    OPENAI_API_KEY=sk-...",
            flush=True,
        )
        sys.exit(1)

    for v in _REQUIRED_VARS:
        val = os.getenv(v, "")
        masked = val[:6] + "..." + val[-4:] if len(val) > 10 else "***"
        _ok(f"{v} = {masked}")

    database = os.getenv("NEO4J_DATABASE", "neo4j")
    _ok(f"NEO4J_DATABASE = {database!r}")

    has_openai = bool(
        os.getenv("OPENAI_API_KEY") or
        (os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY"))
    )
    if has_openai:
        _ok("LLM credentials found (OpenAI / Azure OpenAI)")
    else:
        _warn("No OPENAI_API_KEY or Azure OpenAI credentials found. "
              "Steps 6 and 7 will fail.")

    return database


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 — Test Neo4j connectivity
# ──────────────────────────────────────────────────────────────────────────────

def step_test_connection(database: str) -> None:
    _header("Step 2 / 8 — Testing Neo4j connection")

    from neo4j import GraphDatabase

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    print(f"  Connecting to {uri!r} …", flush=True)
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        with driver.session(database=database) as session:
            result = session.run("RETURN 1 AS ok").single()
            if result and result["ok"] == 1:
                _ok(f"Connected to database {database!r}")
            # Show node label counts for a quick sanity check
            rows = list(session.run(
                "CALL db.labels() YIELD label RETURN label ORDER BY label"
            ))
            labels = [r["label"] for r in rows]
            _ok(f"Node labels found: {labels}")
    except Exception as e:
        _fail(f"Connection failed: {e}")
        print(
            "\n  Check:\n"
            "    • NEO4J_URI is correct (bolt://, neo4j://, neo4j+s://)\n"
            "    • Neo4j is running and reachable\n"
            "    • NEO4J_USERNAME / NEO4J_PASSWORD are correct\n"
            f"   • Database {database!r} exists",
            flush=True,
        )
        sys.exit(1)
    finally:
        driver.close()


# ──────────────────────────────────────────────────────────────────────────────
# Step 3 — Export schema to CSV
# ──────────────────────────────────────────────────────────────────────────────

def step_export_schema(database: str) -> None:
    _header("Step 3 / 8 — Exporting schema to CSV")

    from neo4j import GraphDatabase
    from gen_schema_csv import collect_node_schema, collect_rel_schema, \
        write_nodes_csv, write_rels_csv

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        node_rows = collect_node_schema(driver, database, n_samples=3)
        rel_rows  = collect_rel_schema(driver, database,  n_samples=3)
    finally:
        driver.close()

    write_nodes_csv(node_rows, "schema_nodes.csv")
    write_rels_csv(rel_rows,   "schema_relations.csv")

    _ok(f"{len(node_rows):>3d} (label × property) pairs  →  schema_nodes.csv")
    _ok(f"{len(rel_rows):>3d} relation rows              →  schema_relations.csv")


# ──────────────────────────────────────────────────────────────────────────────
# Step 4 — Generate schema_meta.json (LLM-inferred metadata)
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_schema_meta() -> None:
    _header("Step 4 / 8 — Generating schema_meta.json (LLM inference)")

    from gen_schema_meta import generate_schema_meta

    meta = generate_schema_meta(
        nodes_csv = "schema_nodes.csv",
        rels_csv  = "schema_relations.csv",
        output    = "schema_meta.json",
        language  = os.getenv("TOOL_GEN_LANGUAGE", "en"),
    )

    n_labels = len(meta.get("nodes", {}))
    n_rels   = len(meta.get("relationships", {}))
    _ok(f"{n_labels} label(s) + {n_rels} rel type(s)  →  schema_meta.json")


# ──────────────────────────────────────────────────────────────────────────────
# Step 5 — Create fulltext indexes
# ──────────────────────────────────────────────────────────────────────────────

def step_create_indexes(database: str) -> None:
    _header("Step 5 / 8 — Creating Neo4j fulltext indexes")

    import csv
    from neo4j_search import (
        set_neo4j_graph, initialize_graph,
        _ensure_fulltext_index, _ensure_fulltext_rel_index,
    )

    # Point neo4j_search at the correct database
    graph = initialize_graph(database)
    set_neo4j_graph(graph)

    # ── Node property indexes ─────────────────────────────────────────────────
    node_props: List[tuple] = []
    try:
        with open("schema_nodes.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                label = row.get("label", "").strip()
                prop  = row.get("property", "").strip()
                if label and prop:
                    node_props.append((label, prop))
    except FileNotFoundError:
        _warn("schema_nodes.csv not found — skipping node indexes. "
              "Did Step 3 complete?")

    created_node = 0
    for label, prop in node_props:
        try:
            _ensure_fulltext_index(label, prop)
            created_node += 1
        except Exception as e:
            _warn(f"  Could not create index for {label}.{prop}: {e}")

    if created_node:
        _ok(f"{created_node} node fulltext index(es) ready")

    # ── Relationship property indexes ─────────────────────────────────────────
    rel_props: List[tuple] = []
    try:
        with open("schema_relations.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rt   = row.get("rel_type", "").strip()
                prop = row.get("property", "").strip()
                if rt and prop:
                    rel_props.append((rt, prop))
    except FileNotFoundError:
        _warn("schema_relations.csv not found — skipping rel indexes.")

    created_rel = 0
    seen_rel: set = set()
    for rt, prop in rel_props:
        key = (rt, prop)
        if key in seen_rel:
            continue
        seen_rel.add(key)
        try:
            _ensure_fulltext_rel_index(rt, prop)
            created_rel += 1
        except Exception as e:
            _warn(f"  Could not create index for {rt}.{prop}: {e}")

    if created_rel:
        _ok(f"{created_rel} relationship fulltext index(es) ready")

    if not created_node and not created_rel:
        _warn("No indexes were created — check Neo4j write permissions.")


# ──────────────────────────────────────────────────────────────────────────────
# Step 6 — Generate @tool files
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_tools(database: str) -> None:
    _header("Step 6 / 8 — Generating @tool functions")

    from neo4j import GraphDatabase
    from gen_tools import (
        _get_driver,
        list_node_pairs,
        list_rel_property_pairs,
        list_structural_relations,
        generate_node_tools_file,
        generate_rel_tools_file,
    )

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        node_pairs      = list_node_pairs(driver, database)
        rel_prop_pairs  = list_rel_property_pairs(driver, database)
        structural_rels = list_structural_relations(driver, database)
    finally:
        driver.close()

    n_node = generate_node_tools_file(node_pairs, "generated_node_tools.py")
    n_rel  = generate_rel_tools_file(rel_prop_pairs, structural_rels,
                                     "generated_rel_tools.py")

    _ok(f"{n_node:>3d} node tools  →  generated_node_tools.py")
    _ok(f"{n_rel:>3d} rel  tools  →  generated_rel_tools.py")


# ──────────────────────────────────────────────────────────────────────────────
# Step 7 — Generate config.py
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_config(database: str) -> None:
    _header("Step 7 / 8 — Generating config.py")

    from gen_system_prompt import generate_all

    generate_all(
        database  = database,
        output    = "config.py",
        n_samples = 3,
        write     = True,
        verbose   = False,
    )
    _ok("config.py written with NER_SP, TEXT2CYPHER_SP, QA_SP, "
        "PROMPT_ALIGNER_SP, and schema constants")


# ──────────────────────────────────────────────────────────────────────────────
# Step 8 — Build FAISS tool-selection index
# ──────────────────────────────────────────────────────────────────────────────

def step_build_faiss() -> None:
    _header("Step 8 / 8 — Building FAISS tool-selection index")

    from ner_agent_auto import rebuild_tools_faiss

    n = rebuild_tools_faiss()
    _ok(f"{n} tools indexed  →  faiss_tools_auto/")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="One-click project setup for a new Neo4j database.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--database",
        default=os.getenv("NEO4J_DATABASE", "neo4j"),
        metavar="DB",
        help="Neo4j database name (overrides NEO4J_DATABASE in .env)",
    )
    p.add_argument(
        "--skip-faiss",
        action="store_true",
        help="Skip Step 7 (FAISS index build) — useful when no OpenAI key yet",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Pass verbose=True to sub-steps for extra debug output",
    )
    return p.parse_args()


def main() -> None:
    _banner("Text-to-Cypher Project Setup")
    print(f"  Python  : {sys.executable}", flush=True)
    print(f"  CWD     : {os.getcwd()}", flush=True)

    args     = _parse_args()
    database = args.database

    # ⚠ Step order matters — DO NOT reorder:
    #   Step 3 (schema CSV)   → writes schema_nodes.csv, schema_relations.csv
    #   Step 4 (schema meta)  → reads CSVs, writes schema_meta.json (LLM)
    #   Step 6 (gen tools)    → reads schema_meta.json, writes generated_*_tools.py
    #   Step 7 (gen config)   → imports generated tools to build NER_SP, writes config.py
    #   Step 8 (FAISS)        → imports generated tools (which import config.py)
    steps = [
        ("Check environment",         lambda: step_check_env()),
        ("Test Neo4j connection",     lambda: step_test_connection(database)),
        ("Export schema to CSV",      lambda: step_export_schema(database)),
        ("Generate schema_meta.json", lambda: step_generate_schema_meta()),
        ("Create fulltext indexes",   lambda: step_create_indexes(database)),
        ("Generate @tool files",      lambda: step_generate_tools(database)),
        ("Generate config.py",        lambda: step_generate_config(database)),
    ]

    if not args.skip_faiss:
        steps.append(("Build FAISS index", lambda: step_build_faiss()))

    failed: List[str] = []

    for name, fn in steps:
        try:
            result = fn()
            # step_check_env returns the db name; use it for subsequent steps
            if name == "Check environment" and isinstance(result, str):
                database = result
        except SystemExit:
            raise
        except Exception as exc:
            _fail(f"{name} failed: {exc}")
            if args.verbose:
                traceback.print_exc()
            failed.append(name)
            print("  Skipping remaining steps that depend on this one.",
                  flush=True)
            break

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─' * _WIDTH}", flush=True)
    if not failed:
        _banner("Setup Complete")
        print(
            "\n  Everything is ready.  Try a query:\n\n"
            '    python ner_agent_auto.py "Your question here" --verbose\n',
            flush=True,
        )
    else:
        _banner("Setup Incomplete")
        print(
            f"\n  Failed step: {failed[0]}\n"
            "  Fix the issue above and re-run:\n\n"
            "    python setup_project.py\n",
            flush=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
