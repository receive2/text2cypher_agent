#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_project.py
================
One-click project setup.  Run this once after pointing the project at a new
Neo4j database and all required files will be generated automatically.

Steps executed (in order):
   1  Verify .env contains all required environment variables
   2  Test Neo4j connectivity (and probe Neo4j version >= 5.18)
   3  Export schema to CSV files (schema_nodes.csv, schema_relations.csv)
   4  Generate schema_meta.json (LLM-inferred metadata: id_property, topics)
   5  Create Neo4j fulltext indexes for every node + relationship property
   6  Backfill embeddings for every embeddable node property        [NEW]
   7  Create native vector indexes (one per embeddable property)    [NEW]
   8  Generate @tool functions  (generated_node_tools.py, generated_rel_tools.py)
   9  Generate prompts.py from scratch (system prompts + schema constants).
      ``config.py`` is NOT regenerated — it's user-managed and holds
      hyperparameters (LLM configs, VAL_LINK_MODE, SAMPLE_T, …).
  10  Build the FAISS tool-selection index (faiss_tools_auto/)

Console output is bounded — one summary line per step regardless of schema
size.  All per-item details are routed to ``setup_project.log``.  Use
``--verbose`` to mirror those details to the console.

Usage
-----
  python setup_project.py
  python setup_project.py --database my_db
  python setup_project.py --skip-faiss            # skip step 10
  python setup_project.py --skip-embeddings       # skip steps 6 + 7
  python setup_project.py --rediscover            # re-run auto-discovery
  python setup_project.py --reset-embeddings      # drop + null + re-embed
  python setup_project.py --yes                   # non-interactive (CI)
  python setup_project.py --verbose
  python setup_project.py --quiet                 # only step headers
  python setup_project.py --append-log            # append to setup_project.log

Environment variables  (loaded from .env)
-----------------------------------------
  NEO4J_URI          bolt / neo4j+s URI  (required)
  NEO4J_USERNAME                         (required)
  NEO4J_PASSWORD                         (required)
  NEO4J_DATABASE     default: neo4j
  OPENAI_API_KEY                         (required for steps 4, 6 (openai backend), 9, 10)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from typing import Callable, List, Optional

from dotenv import load_dotenv

from paths import (
    GENERATED_NODE_TOOLS,
    GENERATED_REL_TOOLS,
    PROMPTS,
    SCHEMA_META,
    SCHEMA_NODES_CSV,
    SCHEMA_RELS_CSV,
)

load_dotenv(".env", override=False)

# NOTE: setup_logging is imported here BEFORE any module that touches
# stdlib logging (embedding_helper, neo4j_search) or loguru (ner_agent_auto).
# configure() is called from main() — module-level imports of those
# submodules happen lazily inside step functions, so the bridge is always
# in place before any noisy module starts producing records.
from scripts import setup_logging

_LOG = logging.getLogger("setup_project")


# ──────────────────────────────────────────────────────────────────────────────
# Console helpers (UI — NOT routed through the logger)
# ──────────────────────────────────────────────────────────────────────────────

_WIDTH = 70
_NAME_COL = 30   # width reserved for the step-name column on the summary line


def _banner(title: str) -> None:
    border = "═" * _WIDTH
    sys.stdout.write(f"\n{border}\n")
    pad = (_WIDTH - len(title) - 2) // 2
    sys.stdout.write(f"{'═' * pad} {title} {'═' * pad}\n")
    sys.stdout.write(f"{border}\n")
    sys.stdout.flush()


def _warn_console(msg: str) -> None:
    """Always-visible warning. Distinct path from the logger so it shows
    even when the console handler is at WARNING and the logger record
    would be filtered."""
    sys.stdout.write(f"  ⚠  {msg}\n")
    sys.stdout.flush()


def _fail_console(msg: str) -> None:
    """Step-body failure path. Closes the dangling head line of the
    enclosing Step (if any) with ``✗`` so the layout stays aligned, then
    prints the indented error message on the following line."""
    sys.stdout.write(f"✗\n  {msg}\n")
    sys.stdout.flush()


# ──────────────────────────────────────────────────────────────────────────────
# Step context — one-line-per-step UI.  Per-item details routed to logger.
# ──────────────────────────────────────────────────────────────────────────────

class Step:
    """Bounded-output step UI.

    Default mode (1 line per step):
        ``  Step  N/T  <name>            ✓  (<metric>)``

    Verbose mode:
        Same head + tail line, plus every ``s.detail(...)`` echoed on
        the console (because the root console handler is at INFO level
        in --verbose).

    Quiet mode:
        ``  Step  N/T  <name>            ✓``  (no metric tail).
    """

    def __init__(self, n: int, total: int, name: str,
                 *, verbose: bool, quiet: bool) -> None:
        self.n = n
        self.total = total
        self.name = name
        self.verbose = verbose
        self.quiet = quiet
        self._metric: Optional[str] = None
        self._t0 = 0.0

    # public mutators ---------------------------------------------------

    def metric(self, value: str) -> None:
        """Set the trailing summary that appears after the ✓ in default mode."""
        self._metric = value

    def detail(self, msg: str, *args) -> None:
        """File-only by default; mirrored to console under --verbose."""
        _LOG.info(msg, *args)

    def debug(self, msg: str, *args) -> None:
        _LOG.debug(msg, *args)

    # context manager ---------------------------------------------------

    def _head(self) -> str:
        return f"  Step {self.n:>2d}/{self.total}  {self.name:<{_NAME_COL}s}  "

    def __enter__(self) -> "Step":
        self._t0 = time.monotonic()
        _LOG.info("=== Step %d/%d: %s ===", self.n, self.total, self.name)
        if self.verbose:
            # Verbose layout: header on its own line, details follow,
            # closing summary line at the end.
            sys.stdout.write(f"\n{self._head()}\n")
        else:
            sys.stdout.write(self._head())
        sys.stdout.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        dt = time.monotonic() - self._t0
        if exc_type is not None and exc_type is not SystemExit:
            _LOG.exception("Step %d/%d FAILED: %s (%.1fs)",
                           self.n, self.total, self.name, dt)
            tail = f"✗  {exc_val}"
            if self.verbose:
                sys.stdout.write(f"{self._head()}{tail}\n")
            else:
                sys.stdout.write(f"{tail}\n")
            sys.stdout.flush()
            return False  # propagate

        # SystemExit propagates from the step body after it printed its
        # own _fail_console(). _fail_console closed our dangling head
        # line with "✗" before the detail block, so we don't write
        # anything more here.
        if exc_type is SystemExit:
            return False

        tail_metric = "" if (self.quiet or not self._metric) else f"  ({self._metric})"
        line = f"✓{tail_metric}"
        if self.verbose:
            sys.stdout.write(f"{self._head()}{line}  ({dt:.1f}s)\n")
        else:
            sys.stdout.write(f"{line}\n")
        sys.stdout.flush()
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 — Verify .env
# ──────────────────────────────────────────────────────────────────────────────

_REQUIRED_VARS = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"]
_OPTIONAL_VARS = ["NEO4J_DATABASE", "OPENAI_API_KEY", "OPENAI_BASE_URL",
                  "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
                  "AZURE_OPENAI_DEPLOYMENT"]


def step_check_env(s: Step) -> str:
    """Return the database name after validating env vars."""
    missing = [v for v in _REQUIRED_VARS if not os.getenv(v)]
    if missing:
        for v in missing:
            _fail_console(f"Missing required env var: {v}")
        sys.stdout.write(
            "\n  Create a .env file in the project root with:\n"
            "    NEO4J_URI=bolt://localhost:7687\n"
            "    NEO4J_USERNAME=neo4j\n"
            "    NEO4J_PASSWORD=your-password\n"
            "    NEO4J_DATABASE=neo4j\n"
            "    OPENAI_API_KEY=sk-...\n"
        )
        sys.stdout.flush()
        sys.exit(1)

    for v in _REQUIRED_VARS:
        val = os.getenv(v, "")
        masked = val[:6] + "..." + val[-4:] if len(val) > 10 else "***"
        s.detail("%s = %s", v, masked)

    database = os.getenv("NEO4J_DATABASE", "neo4j")
    s.detail("NEO4J_DATABASE = %r", database)

    has_openai = bool(
        os.getenv("OPENAI_API_KEY") or
        (os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY"))
    )

    # Active embedding backend determines which step needs which credential.
    import vector_config as vc
    backend = vc.EMBEDDING_BACKEND
    s.detail("Embedding backend = %r (model=%s, dim=%s)",
             backend, vc.EMBEDDING_MODEL_NAME, vc.EMBEDDING_DIMENSIONS)

    if has_openai:
        s.detail("LLM credentials found (OpenAI / Azure OpenAI)")
    else:
        _warn_console("No OPENAI_API_KEY or Azure OpenAI credentials found. "
                      "Steps 4, 9 and 10 will fail "
                      "(LLM-driven schema metadata, prompt generation, FAISS).")
        if backend == "openai":
            _warn_console("Step 6 (embedding backfill) also requires OPENAI_API_KEY "
                          "because EMBEDDING_BACKEND='openai'. Switch to "
                          "'sentence_transformers' in vector_config.py to embed "
                          "without an API key.")

    s.metric(f"backend={backend!r}")
    return database


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 — Test Neo4j connectivity
# ──────────────────────────────────────────────────────────────────────────────

def step_test_connection(s: Step, database: str) -> None:
    from neo4j import GraphDatabase
    from embedding.embedding_helper import check_neo4j_version

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    s.detail("Connecting to %r …", uri)
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        with driver.session(database=database) as session:
            result = session.run("RETURN 1 AS ok").single()
            if result and result["ok"] == 1:
                s.detail("Connected to database %r", database)
            rows = list(session.run(
                "CALL db.labels() YIELD label RETURN label ORDER BY label"
            ))
            labels = [r["label"] for r in rows]
            s.detail("Node labels found: %s", labels)

        try:
            major, minor, patch = check_neo4j_version(driver, database)
            s.detail("Neo4j version %d.%d.%d (>= 5.18 required)",
                     major, minor, patch)
            s.metric(f"{major}.{minor}.{patch}")
        except RuntimeError as ve:
            _fail_console(str(ve))
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        _fail_console(f"Connection failed: {e}")
        sys.stdout.write(
            "\n  Check:\n"
            "    • NEO4J_URI is correct (bolt://, neo4j://, neo4j+s://)\n"
            "    • Neo4j is running and reachable\n"
            "    • NEO4J_USERNAME / NEO4J_PASSWORD are correct\n"
            f"   • Database {database!r} exists\n"
        )
        sys.stdout.flush()
        sys.exit(1)
    finally:
        driver.close()


# ──────────────────────────────────────────────────────────────────────────────
# Step 3 — Export schema to CSV
# ──────────────────────────────────────────────────────────────────────────────

def step_export_schema(s: Step, database: str) -> None:
    from neo4j import GraphDatabase
    from schema.gen_schema_csv import collect_node_schema, collect_rel_schema, \
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

    SCHEMA_NODES_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_nodes_csv(node_rows, SCHEMA_NODES_CSV)
    write_rels_csv(rel_rows,   SCHEMA_RELS_CSV)

    s.detail("%d (label × property) pairs → schema_nodes.csv", len(node_rows))
    s.detail("%d relation rows → schema_relations.csv", len(rel_rows))
    s.metric(f"{len(node_rows)} nodes, {len(rel_rows)} rels")


# ──────────────────────────────────────────────────────────────────────────────
# Step 4 — Generate schema_meta.json (LLM-inferred metadata)
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_schema_meta(s: Step) -> None:
    from schema.gen_schema_meta import generate_schema_meta

    SCHEMA_META.parent.mkdir(parents=True, exist_ok=True)
    meta = generate_schema_meta(
        nodes_csv = SCHEMA_NODES_CSV,
        rels_csv  = SCHEMA_RELS_CSV,
        output    = SCHEMA_META,
        language  = os.getenv("TOOL_GEN_LANGUAGE", "en"),
    )

    n_labels = len(meta.get("nodes", {}))
    n_rels   = len(meta.get("relationships", {}))
    s.detail("%d label(s) + %d rel type(s) → schema_meta.json", n_labels, n_rels)
    s.metric(f"{n_labels} labels, {n_rels} rel types")


# ──────────────────────────────────────────────────────────────────────────────
# Step 5 — Create fulltext indexes
# ──────────────────────────────────────────────────────────────────────────────

def step_create_indexes(s: Step, database: str) -> None:
    import csv
    from neo4j_lib.neo4j_search import (
        set_neo4j_graph, initialize_graph,
        _ensure_fulltext_index, _ensure_fulltext_rel_index,
    )

    graph = initialize_graph(database)
    set_neo4j_graph(graph)

    # ── Node property indexes ─────────────────────────────────────────────────
    node_props: List[tuple] = []
    try:
        with open(SCHEMA_NODES_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                label = row.get("label", "").strip()
                prop  = row.get("property", "").strip()
                if label and prop:
                    node_props.append((label, prop))
    except FileNotFoundError:
        _warn_console(f"{SCHEMA_NODES_CSV} not found — skipping node indexes. "
                      "Did Step 3 complete?")

    created_node = 0
    for label, prop in node_props:
        try:
            _ensure_fulltext_index(label, prop)
            created_node += 1
        except Exception as e:
            _LOG.warning("Could not create index for %s.%s: %s", label, prop, e)

    if created_node:
        s.detail("%d node fulltext index(es) ready", created_node)

    # ── Relationship property indexes ─────────────────────────────────────────
    rel_props: List[tuple] = []
    try:
        with open(SCHEMA_RELS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rt   = row.get("rel_type", "").strip()
                prop = row.get("property", "").strip()
                if rt and prop:
                    rel_props.append((rt, prop))
    except FileNotFoundError:
        _warn_console("schema_relations.csv not found — skipping rel indexes.")

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
            _LOG.warning("Could not create index for %s.%s: %s", rt, prop, e)

    if created_rel:
        s.detail("%d relationship fulltext index(es) ready", created_rel)

    if not created_node and not created_rel:
        _warn_console("No indexes were created — check Neo4j write permissions.")

    s.metric(f"{created_node} node, {created_rel} rel")


# ──────────────────────────────────────────────────────────────────────────────
# Step 6 — Backfill embeddings   [NEW]
# ──────────────────────────────────────────────────────────────────────────────

# OpenAI text-embedding-3-small price (April 2026): $0.02 / 1M tokens.
_OPENAI_EMBED_USD_PER_1M_TOKENS = 0.02
_AVG_CHARS_PER_TOKEN = 4.0
_COST_PROMPT_THRESHOLD_USD = 1.00


def step_backfill_embeddings(
    s: Step,
    database: str,
    *,
    rediscover: bool,
    reset: bool,
    yes: bool,
) -> None:
    # Re-import each call so the module reflects any in-place rewrites.
    import importlib
    import vector_config as vc
    importlib.reload(vc)

    from neo4j import GraphDatabase
    from embedding.embedding_helper import (
        backfill_embeddings, discover_embeddable_properties,
        drop_vector_indexes, estimate_distinct_values,
        null_embedding_properties, reset_caches, sample_avg_lengths,
        verify_backend,
    )

    reset_caches()

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    t0 = time.monotonic()

    try:
        # ── Discovery (if needed) ─────────────────────────────────────────
        spec = list(vc.EMBEDDABLE_PROPERTIES)
        if not spec or rediscover:
            if rediscover and spec:
                s.detail("--rediscover passed; ignoring existing "
                         "EMBEDDABLE_PROPERTIES and re-running discovery.")
            else:
                s.detail("EMBEDDABLE_PROPERTIES is empty — running auto-discovery.")

            discovered = discover_embeddable_properties(
                SCHEMA_META, driver=driver, database=database,
            )
            if not discovered:
                _warn_console("Auto-discovery returned no embeddable properties. "
                              "Skipping backfill.")
                s.metric("skipped (no embeddable props)")
                return

            # File-only enumeration; console gets a single summary count.
            for entry in discovered:
                s.detail("discovered: %s.%s → index %s",
                         entry["label"], entry["property"], _index_name(entry))

            if not yes:
                # The interactive prompt MUST stay on the console.
                sys.stdout.write(
                    f"\n  Discovered {len(discovered)} embeddable propertie(s) "
                    f"(full list in log).\n"
                )
                sys.stdout.flush()
                ans = input(
                    "  Persist this list to vector_config.py? [Y/n/edit] "
                ).strip().lower()
                if ans == "edit":
                    _fail_console("Manual edit requested — open vector_config.py, "
                                  "set EMBEDDABLE_PROPERTIES, then re-run setup.")
                    sys.exit(1)
                if ans and ans not in ("y", "yes"):
                    _warn_console("Aborted by user.")
                    sys.exit(1)

            _rewrite_embeddable_block("vector_config.py", discovered)
            s.detail("Wrote %d entries to vector_config.py:EMBEDDABLE_PROPERTIES",
                     len(discovered))

            importlib.reload(vc)
            spec = list(vc.EMBEDDABLE_PROPERTIES)

        # ── Reset (if asked) ──────────────────────────────────────────────
        if reset:
            _warn_console("--reset-embeddings: dropping existing vector indexes + "
                          "nulling embedding properties before backfill.")
            dropped = drop_vector_indexes(driver, database, spec)
            for n in dropped:
                s.detail("dropped index %s", n)
            n_null = null_embedding_properties(driver, database, spec)
            s.detail("cleared embeddings on %d node(s)", n_null)

        # ── Pre-flight: backend dim check ─────────────────────────────────
        try:
            verify_backend()
        except Exception as e:
            _fail_console(f"Embedding backend verification failed: {e}")
            sys.exit(1)

        # ── Cost / time estimate ──────────────────────────────────────────
        counts = estimate_distinct_values(driver, database, spec)
        total_distinct = sum(counts.values())
        for (label, prop), n in counts.items():
            s.detail("distinct values: %s.%s = %d", label, prop, n)
        s.detail("Total distinct values across embeddable props: %d", total_distinct)

        est_cost: Optional[float] = None
        if vc.EMBEDDING_BACKEND == "openai":
            _DEFAULT_AVG_CHARS = 30.0
            label_set = sorted({e["label"] for e in spec})
            avg_lens  = sample_avg_lengths(driver, database, label_set)
            est_tokens = 0.0
            for e in spec:
                key = (e["label"], e["property"])
                n   = counts.get(key, 0)
                ac  = avg_lens.get(key) or _DEFAULT_AVG_CHARS
                est_tokens += n * ac / _AVG_CHARS_PER_TOKEN
            est_cost = est_tokens / 1_000_000 * _OPENAI_EMBED_USD_PER_1M_TOKENS
            s.detail("Estimated cost: ~$%.4f (model=%s, sampled avg_chars per prop)",
                     est_cost, vc.EMBEDDING_MODEL_NAME)
            if est_cost > _COST_PROMPT_THRESHOLD_USD and not yes:
                # Cost confirmation MUST stay visible on the console.
                sys.stdout.write(
                    f"\n  Estimated embedding cost: ~${est_cost:.4f} "
                    f"(threshold ${_COST_PROMPT_THRESHOLD_USD:.2f}).\n"
                )
                sys.stdout.flush()
                ans = input("  Proceed? [y/N] ").strip().lower()
                if ans not in ("y", "yes"):
                    _warn_console("Aborted by user.")
                    sys.exit(1)
        elif vc.EMBEDDING_BACKEND == "sentence_transformers":
            from embedding.embedding_helper import _st_active_device
            device = _st_active_device()
            rate = 1500 if device in ("cuda", "mps") else 200
            est_s = total_distinct / max(1, rate)
            s.detail("Active device: %s (rough estimate ~%.1fs for %d values)",
                     device, est_s, total_distinct)
        else:
            _warn_console(f"Unknown EMBEDDING_BACKEND: {vc.EMBEDDING_BACKEND!r}")

        # ── Backfill ──────────────────────────────────────────────────────
        summary = backfill_embeddings(driver, database, spec)
        n_embedded = 0
        for (label, prop), stats in summary.items():
            s.detail("%s.%s: embedded=%s distinct=%s elapsed=%.2fs",
                     label, prop, stats["embedded"],
                     stats["distinct_values"], stats["elapsed_s"])
            n_embedded += int(stats.get("embedded", 0))

        elapsed = time.monotonic() - t0
        if est_cost is not None:
            s.metric(f"${est_cost:.2f}, {_fmt_dur(elapsed)}, {n_embedded} values")
        else:
            s.metric(f"{_fmt_dur(elapsed)}, {n_embedded} values")

    finally:
        driver.close()


def _fmt_dur(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def _index_name(entry: dict) -> str:
    from embedding.embedding_helper import index_name_for
    return index_name_for(entry["label"], entry["property"])


def _rewrite_embeddable_block(path: str, entries: list) -> None:
    """
    Rewrite the ``EMBEDDABLE_PROPERTIES = [...]`` block in
    ``vector_config.py`` in place.

    Thin wrapper around
    :func:`scripts._vector_config_io.rewrite_embeddable_block` so the
    per-graph artifact-swap path (:mod:`eval.artifact_swap`) can share
    the exact same regex / backup behaviour without importing this
    module's orchestration code.  The shared helper writes ``<path>.bak``
    before mutation; behaviour is otherwise unchanged.
    """
    from scripts._vector_config_io import rewrite_embeddable_block as _impl
    _impl(path, entries)
    _LOG.info("Backup written: %s", path + ".bak")


# ──────────────────────────────────────────────────────────────────────────────
# Step 7 — Create vector indexes   [NEW]
# ──────────────────────────────────────────────────────────────────────────────

def step_create_vector_indexes(s: Step, database: str) -> None:
    import importlib
    import vector_config as vc
    importlib.reload(vc)

    spec = list(vc.EMBEDDABLE_PROPERTIES)
    if not spec:
        _warn_console("EMBEDDABLE_PROPERTIES is empty — nothing to index. "
                      "(Did Step 6 run, or was --skip-embeddings passed?)")
        s.metric("skipped (no spec)")
        return

    from neo4j import GraphDatabase
    from embedding.embedding_helper import create_vector_indexes

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        filtered: list = []
        sess_kwargs = {"database": database} if database else {}
        with driver.session(**sess_kwargs) as session:
            for entry in spec:
                if entry.get("entity_type", "node") != "node":
                    filtered.append(entry)
                    continue
                label    = entry["label"]
                emb_prop = entry["embedding_property"]
                safe_label = label.replace("`", "``")
                safe_emb   = emb_prop.replace("`", "``")
                row = session.run(
                    f"MATCH (n:`{safe_label}`) "
                    f"WHERE n.`{safe_emb}` IS NOT NULL "
                    f"RETURN count(*) AS n"
                ).single()
                n = int(row["n"]) if row else 0
                if n == 0:
                    _LOG.warning("%s.%s: 0 embedded nodes — skipping index. "
                                 "Did Step 6 run? Try --reset-embeddings.",
                                 label, entry["property"])
                    continue
                filtered.append(entry)

        if not filtered:
            _warn_console("No (label, property) has populated embeddings — no "
                          "vector indexes will be created.")
            s.metric("0 created (no populated embeddings)")
            return

        results = create_vector_indexes(driver, database, filtered)
    finally:
        driver.close()

    n_created = sum(1 for v in results.values() if v == "created")
    n_exists  = sum(1 for v in results.values() if v == "exists")
    for name, status in results.items():
        s.detail("%s  %s", status, name)
    s.metric(f"{n_created} created, {n_exists} existed")


# ──────────────────────────────────────────────────────────────────────────────
# Step 8 — Generate @tool files
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_tools(s: Step, database: str) -> None:
    from neo4j import GraphDatabase
    from tools.gen_tools import (
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

    GENERATED_NODE_TOOLS.parent.mkdir(parents=True, exist_ok=True)
    n_node = generate_node_tools_file(node_pairs, GENERATED_NODE_TOOLS)
    n_rel  = generate_rel_tools_file(rel_prop_pairs, structural_rels,
                                     GENERATED_REL_TOOLS)

    s.detail("%d node tools → %s", n_node, GENERATED_NODE_TOOLS)
    s.detail("%d rel  tools → %s", n_rel,  GENERATED_REL_TOOLS)
    s.metric(f"{n_node} node, {n_rel} rel")


# ──────────────────────────────────────────────────────────────────────────────
# Step 9 — Generate prompts.py
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_config(s: Step, database: str) -> None:
    from schema.gen_system_prompt import generate_all

    PROMPTS.parent.mkdir(parents=True, exist_ok=True)
    generate_all(
        database  = database,
        output    = PROMPTS,
        n_samples = 3,
        write     = True,
        verbose   = False,
    )
    s.detail("%s written with NER_SP, TEXT2CYPHER_SP, QA_SP, "
             "PROMPT_ALIGNER_SP, and schema constants "
             "(config.py left untouched — hyperparameters preserved)", PROMPTS)
    s.metric("ok")


# ──────────────────────────────────────────────────────────────────────────────
# Step 10 — Build FAISS tool-selection index
# ──────────────────────────────────────────────────────────────────────────────

def step_build_faiss(s: Step) -> None:
    """
    Build BOTH ``full`` and ``node_only`` FAISS tool-selection indexes
    unconditionally, regardless of the selected value-linking mode.

    Rationale
    ---------
    Setup is mode-agnostic on purpose: the resulting artifact archive
    must be a complete snapshot that works for every NER mode any
    downstream user might pick.  Coupling setup to a single user's
    value-linking mode choice means a stranger who clones the repo and flips
    the mode would silently get an archive missing the index they need.

    Cost is negligible — both indexes embed the same ~55 tool docstrings
    against the same OpenAI ``text-embedding-3-small`` model, so the
    second call is mostly cache hits on the embedding side and a tiny
    on-disk write (a few MB) on the FAISS side.  The ``no_ner`` mode
    is the only one that builds nothing (it raises in
    ``rebuild_tools_faiss``); we silently skip it.
    """
    from ner_agent_auto import rebuild_tools_faiss

    built: list[tuple[str, int]] = []
    for mode in ("full", "node_only"):
        try:
            n = rebuild_tools_faiss(mode=mode)
        except RuntimeError as exc:  # raised for "no_ner" — not applicable here
            s.detail("skipped mode=%s: %s", mode, exc)
            continue
        suffix = "" if mode == "full" else "_node_only"
        s.detail("%d tools indexed → faiss/tools_auto%s/", n, suffix)
        built.append((mode, n))

    s.metric(", ".join(f"{m}={n}" for m, n in built) or "none")


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
        help="Skip Step 10 (FAISS index build) — useful when no OpenAI key yet",
    )
    p.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip Steps 6 + 7 (embedding backfill + vector indexes).",
    )
    p.add_argument(
        "--rediscover",
        action="store_true",
        help="Force re-running auto-discovery in Step 6.",
    )
    p.add_argument(
        "--reset-embeddings",
        action="store_true",
        help="Drop existing vector indexes AND null out embedding properties "
             "before backfill.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip all interactive confirmation prompts (CI / scripting).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Mirror per-item log details to the console (INFO and above).",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only print step header lines (no trailing metric).",
    )
    p.add_argument(
        "--append-log",
        action="store_true",
        help="Append to setup_project.log instead of overwriting per run.",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    log_path = "setup_project.log"
    setup_logging.configure(
        log_path,
        append=args.append_log,
        verbose=args.verbose,
        quiet=args.quiet,
    )

    _banner("Text-to-Cypher Project Setup")
    sys.stdout.write(f"  Python  : {sys.executable}\n")
    sys.stdout.write(f"  CWD     : {os.getcwd()}\n")
    sys.stdout.write(f"  Full log: ./{log_path}\n\n")
    sys.stdout.flush()

    database = args.database

    # Build step list dynamically to reflect --skip-* flags. Late binding
    # on `database` is intentional: step_check_env reassigns it before any
    # downstream lambda fires.
    StepFn = Callable[[Step], object]
    steps_def: List[tuple] = [
        ("Check environment",         lambda s: step_check_env(s)),
        ("Test Neo4j connection",     lambda s: step_test_connection(s, database)),
        ("Export schema to CSV",      lambda s: step_export_schema(s, database)),
        ("Generate schema_meta.json", lambda s: step_generate_schema_meta(s)),
        ("Create fulltext indexes",   lambda s: step_create_indexes(s, database)),
    ]

    if not args.skip_embeddings:
        steps_def.append(
            ("Backfill embeddings",
             lambda s: step_backfill_embeddings(
                 s, database,
                 rediscover=args.rediscover,
                 reset=args.reset_embeddings,
                 yes=args.yes,
             )),
        )
        steps_def.append(
            ("Create vector indexes",
             lambda s: step_create_vector_indexes(s, database)),
        )

    steps_def.append(("Generate @tool files",   lambda s: step_generate_tools(s, database)))
    steps_def.append(("Generate prompts.py",    lambda s: step_generate_config(s, database)))

    if not args.skip_faiss:
        steps_def.append(("Build FAISS index",  lambda s: step_build_faiss(s)))

    total = len(steps_def)
    failed: List[str] = []

    for i, (name, fn) in enumerate(steps_def, 1):
        try:
            with Step(i, total, name, verbose=args.verbose, quiet=args.quiet) as s:
                result = fn(s)
                if name == "Check environment" and isinstance(result, str):
                    database = result
        except SystemExit:
            raise
        except Exception as exc:
            # Step.__exit__ already printed the ✗ line and logged the trace.
            if args.verbose:
                traceback.print_exc()
            failed.append(name)
            sys.stdout.write("  Skipping remaining steps that depend on this one.\n")
            sys.stdout.flush()
            break

    # ── Summary ───────────────────────────────────────────────────────────────
    sys.stdout.write(f"\n")
    if not failed:
        _banner("Setup Complete")
        _print_final_summary(database, args)
    else:
        _banner("Setup Incomplete")
        sys.stdout.write(
            f"\n  Failed step: {failed[0]}\n"
            f"  See ./{log_path} for full traceback.\n"
            "  Fix the issue above and re-run:\n\n"
            "    python setup_project.py\n\n"
        )
        sys.stdout.flush()
        sys.exit(1)


def _print_final_summary(database: str, args: argparse.Namespace) -> None:
    """Print active embedding backend, indexes, and ablation guidance.

    Bounded: we show counts on the console and dump the full vector-index
    list to the log file regardless of schema size.
    """
    vc = None
    try:
        import importlib
        import vector_config as vc  # type: ignore[no-redef]
        importlib.reload(vc)
    except Exception as exc:  # pragma: no cover - defensive
        _warn_console(f"Could not import vector_config.py for summary: {exc!r}. "
                      f"If you ran with --rediscover, restore from "
                      f"vector_config.py.bak and inspect.")
        vc = None  # type: ignore

    sys.stdout.write("\n")
    if vc is not None:
        sys.stdout.write(
            f"  Embedding backend  : {vc.EMBEDDING_BACKEND!r} "
            f"({vc.EMBEDDING_MODEL_NAME}, dim={vc.EMBEDDING_DIMENSIONS})\n"
        )
        sys.stdout.write(f"  Retrieval mode     : {vc.TOOL_RETRIEVAL_MODE!r}\n")

        if not args.skip_embeddings and vc.EMBEDDABLE_PROPERTIES:
            from embedding.embedding_helper import index_name_for
            node_entries = [e for e in vc.EMBEDDABLE_PROPERTIES
                            if e.get("entity_type") == "node"]
            sys.stdout.write(
                f"  Vector indexes     : {len(node_entries)} "
                f"(see {os.path.basename('setup_project.log')} for full list)\n"
            )
            for entry in node_entries:
                _LOG.info("vector index: %s",
                          index_name_for(entry["label"], entry["property"]))
        elif args.skip_embeddings:
            sys.stdout.write(
                "  Vector indexes     : skipped (--skip-embeddings)\n"
                "                       New nodes since the last embedding run\n"
                "                       will NOT be retrievable in vector / hybrid\n"
                "                       mode. Re-run without --skip-embeddings.\n"
            )

    sys.stdout.write(
        "\n  Ablation guide:\n"
        "    Switch retrieval mode by editing TOOL_RETRIEVAL_MODE in\n"
        "    vector_config.py to 'fuzzy' | 'vector' | 'hybrid'.\n"
        "\n  Try a query:\n"
        '    python ner_agent_auto.py "Your question here" --verbose\n\n'
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
