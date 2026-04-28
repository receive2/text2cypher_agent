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
   9  Generate config.py from scratch (system prompts + schema constants)
  10  Build the FAISS tool-selection index (faiss_tools_auto/)

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
    _header("Step 1 / 10 — Checking environment variables")

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

    # Active embedding backend determines which step needs which credential.
    import vector_config as vc
    backend = vc.EMBEDDING_BACKEND
    _ok(f"Embedding backend = {backend!r}  "
        f"(model={vc.EMBEDDING_MODEL_NAME}, dim={vc.EMBEDDING_DIMENSIONS})")

    if has_openai:
        _ok("LLM credentials found (OpenAI / Azure OpenAI)")
    else:
        _warn("No OPENAI_API_KEY or Azure OpenAI credentials found. "
              "Steps 4, 9 and 10 will fail "
              "(LLM-driven schema metadata, prompt generation, FAISS).")
        if backend == "openai":
            _warn("Step 6 (embedding backfill) also requires OPENAI_API_KEY "
                  "because EMBEDDING_BACKEND='openai'. Switch to "
                  "'sentence_transformers' in vector_config.py to embed "
                  "without an API key.")

    return database


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 — Test Neo4j connectivity
# ──────────────────────────────────────────────────────────────────────────────

def step_test_connection(database: str) -> None:
    _header("Step 2 / 10 — Testing Neo4j connection")

    from neo4j import GraphDatabase
    from embedding_helper import check_neo4j_version

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

        # Fail fast on Neo4j < 5.18 — native vector indexes are required
        # by steps 6 and 7. Steps 1-5 work on older versions, but the
        # whole pipeline is gated here for portability across deployments.
        try:
            major, minor, patch = check_neo4j_version(driver, database)
            _ok(f"Neo4j version {major}.{minor}.{patch} (>= 5.18 required)")
        except RuntimeError as ve:
            _fail(str(ve))
            sys.exit(1)
    except SystemExit:
        raise
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
    _header("Step 3 / 10 — Exporting schema to CSV")

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
    _header("Step 4 / 10 — Generating schema_meta.json (LLM inference)")

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
    _header("Step 5 / 10 — Creating Neo4j fulltext indexes")

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
# Step 6 — Backfill embeddings   [NEW]
# ──────────────────────────────────────────────────────────────────────────────

# OpenAI text-embedding-3-small price (April 2026): $0.02 / 1M tokens.
# Source of truth: https://openai.com/api/pricing — kept here as a constant
# so the cost estimator below has no magic numbers in step code.
_OPENAI_EMBED_USD_PER_1M_TOKENS = 0.02
# Average characters per token on English text — rough but deliberately
# conservative.  Off by < 30% on most strings.
_AVG_CHARS_PER_TOKEN = 4.0
# Cost ceiling above which we require explicit confirmation (unless --yes).
_COST_PROMPT_THRESHOLD_USD = 1.00


def step_backfill_embeddings(
    database: str,
    *,
    rediscover: bool,
    reset: bool,
    yes: bool,
) -> None:
    """
    Discover embeddable properties (or load the curated list), then run
    the corpus-side backfill so every distinct value gets an embedding.

    Behaviour:
      • If `vector_config.EMBEDDABLE_PROPERTIES` is empty (or `--rediscover`),
        run discovery, print the candidates, prompt for confirmation
        (unless `--yes`), and rewrite the EMBEDDABLE_PROPERTIES block in
        `vector_config.py` in place.
      • If `--reset-embeddings`, drop existing vector indexes and null
        out embedding properties before backfill.
      • OpenAI backend: dry-run cost estimate; require confirmation if
        the estimate exceeds $1 (unless `--yes`).
      • sentence-transformers backend: print rough time estimate and the
        active device.
      • Calls `embedding_helper.backfill_embeddings(...)`.
    """
    _header("Step 6 / 10 — Backfilling embeddings")

    # Re-import each call so the module reflects any in-place rewrites.
    import importlib
    import vector_config as vc
    importlib.reload(vc)

    from neo4j import GraphDatabase
    from embedding_helper import (
        backfill_embeddings, discover_embeddable_properties,
        drop_vector_indexes, estimate_distinct_values,
        null_embedding_properties, reset_caches, sample_avg_lengths,
        verify_backend,
    )

    # Clear cached backend instances. Critical for ablation runs that
    # swap EMBEDDING_BACKEND between setup invocations: without this, the
    # OpenAI client / ST model from the previous run is silently reused
    # and verify_backend() fails with a misleading dim-mismatch.
    reset_caches()

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(uri, auth=(user, pwd))

    try:
        # ── Discovery (if needed) ─────────────────────────────────────────
        spec = list(vc.EMBEDDABLE_PROPERTIES)
        if not spec or rediscover:
            if rediscover and spec:
                _ok("--rediscover passed; ignoring existing "
                    "EMBEDDABLE_PROPERTIES and re-running discovery.")
            else:
                _ok("EMBEDDABLE_PROPERTIES is empty — running auto-discovery "
                    "from schema_meta.json.")

            discovered = discover_embeddable_properties(
                "schema_meta.json", driver=driver, database=database,
            )
            if not discovered:
                _warn("Auto-discovery returned no embeddable properties. "
                      "Either schema_meta.json is missing text-like "
                      "properties or every candidate was filtered. "
                      "Skipping backfill.")
                return

            print("\n  Discovered embeddable properties:", flush=True)
            for entry in discovered:
                print(f"    • {entry['label']}.{entry['property']}  "
                      f"→ index {_index_name(entry)}", flush=True)

            if not yes:
                ans = input(
                    "\n  Persist this list to vector_config.py? [Y/n/edit] "
                ).strip().lower()
                if ans == "edit":
                    _fail("Manual edit requested — open vector_config.py, "
                          "set EMBEDDABLE_PROPERTIES, then re-run setup.")
                    sys.exit(1)
                if ans and ans not in ("y", "yes"):
                    _warn("Aborted by user.")
                    sys.exit(1)

            _rewrite_embeddable_block("vector_config.py", discovered)
            _ok(f"Wrote {len(discovered)} entries to "
                f"vector_config.py:EMBEDDABLE_PROPERTIES")

            importlib.reload(vc)
            spec = list(vc.EMBEDDABLE_PROPERTIES)

        # ── Reset (if asked) ──────────────────────────────────────────────
        if reset:
            _warn("--reset-embeddings: dropping existing vector indexes + "
                  "nulling embedding properties before backfill.")
            dropped = drop_vector_indexes(driver, database, spec)
            for n in dropped:
                _ok(f"  dropped index {n}")
            n_null = null_embedding_properties(driver, database, spec)
            _ok(f"  cleared embeddings on {n_null} node(s)")

        # ── Pre-flight: backend dim check ─────────────────────────────────
        try:
            verify_backend()
        except Exception as e:
            _fail(f"Embedding backend verification failed: {e}")
            sys.exit(1)

        # ── Cost / time estimate ──────────────────────────────────────────
        counts = estimate_distinct_values(driver, database, spec)
        total_distinct = sum(counts.values())
        print(f"\n  Distinct values per property:", flush=True)
        for (label, prop), n in counts.items():
            print(f"    • {label}.{prop}: {n}", flush=True)
        print(f"  Total: {total_distinct} distinct values", flush=True)

        if vc.EMBEDDING_BACKEND == "openai":
            # Per-property avg-char from a small live sample (sample_avg_lengths
            # uses native valueType() to skip non-string values). Falls back
            # to the old 30-char constant for any (label, property) the
            # sampler couldn't measure (e.g. label has 0 nodes carrying that
            # prop in the first 200-row sample window).
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
            _ok(f"Estimated cost: ~${est_cost:.4f} "
                f"(model={vc.EMBEDDING_MODEL_NAME}, "
                f"sampled avg_chars per prop)")
            if est_cost > _COST_PROMPT_THRESHOLD_USD and not yes:
                ans = input(
                    f"  Estimated cost exceeds ${_COST_PROMPT_THRESHOLD_USD:.2f}. "
                    f"Proceed? [y/N] "
                ).strip().lower()
                if ans not in ("y", "yes"):
                    _warn("Aborted by user.")
                    sys.exit(1)
        elif vc.EMBEDDING_BACKEND == "sentence_transformers":
            from embedding_helper import _st_active_device
            device = _st_active_device()
            # Rough heuristic: ~200 strings/s on CPU, ~1500 on GPU/MPS.
            rate = 1500 if device in ("cuda", "mps") else 200
            est_s = total_distinct / max(1, rate)
            _ok(f"Active device: {device}  "
                f"(rough estimate: ~{est_s:.1f}s for {total_distinct} values)")
        else:
            _warn(f"Unknown EMBEDDING_BACKEND: {vc.EMBEDDING_BACKEND!r}")

        # ── Backfill ──────────────────────────────────────────────────────
        summary = backfill_embeddings(driver, database, spec)
        for (label, prop), stats in summary.items():
            _ok(f"{label}.{prop}: embedded={stats['embedded']} "
                f"distinct={stats['distinct_values']} "
                f"elapsed={stats['elapsed_s']:.2f}s")

    finally:
        driver.close()


def _index_name(entry: dict) -> str:
    """Tiny shim so the discovery preview line doesn't import embedding_helper twice."""
    from embedding_helper import index_name_for
    return index_name_for(entry["label"], entry["property"])


def _rewrite_embeddable_block(path: str, entries: list) -> None:
    """
    Rewrite the `EMBEDDABLE_PROPERTIES = [...]` block in `vector_config.py`
    in place. Preserves everything else verbatim.

    Two regex passes:

      1. STRICT — closing ``]`` alone in column 0. This is the canonical
         layout produced by this function on a fresh database.
      2. PERMISSIVE — closing ``]`` anywhere on a line, allowing trailing
         whitespace / comma. Catches files that have been touched by a
         formatter (Black, Ruff, IDE auto-format) since the last setup run.

    If both miss, raise a clear error AND echo the discovered entries to
    stdout so the user can paste them in by hand without re-running
    discovery.

    A timestamped ``.bak`` is written before any change so a regex misfire
    can never silently destroy a hand-edited config — restore with
    ``cp vector_config.py.bak vector_config.py``.

    NOTE: Comments embedded INSIDE the EMBEDDABLE_PROPERTIES block are
    discarded across rediscovery — the block is rebuilt from scratch.
    Important comments belong above the block (which is preserved verbatim).
    """
    import re as _re
    import shutil

    with open(path, encoding="utf-8") as f:
        text = f.read()

    # Strict — closing ] on its own line at column 0.
    strict = _re.search(
        r"^EMBEDDABLE_PROPERTIES\s*=\s*\[.*?^\]\s*$",
        text,
        flags=_re.MULTILINE | _re.DOTALL,
    )
    # Permissive — closing ] anywhere, possibly followed by spaces / a
    # trailing comment. Non-greedy on the body so the FIRST ] following the
    # opening [ is matched (correct because the block contains no nested
    # lists in our schema).
    permissive = strict or _re.search(
        r"^EMBEDDABLE_PROPERTIES\s*=\s*\[.*?\][ \t]*(?:#[^\n]*)?$",
        text,
        flags=_re.MULTILINE | _re.DOTALL,
    )

    if not permissive:
        # Surface the discovered entries so the user can recover without
        # rerunning step 6's potentially-expensive discovery.
        msg = [
            f"Could not find EMBEDDABLE_PROPERTIES block in {path!r}.",
            "Neither the strict nor permissive regex matched. The file may",
            "have been heavily reformatted or the assignment was renamed.",
            "",
            "Paste the following into vector_config.py manually, then re-run:",
            "",
            "EMBEDDABLE_PROPERTIES = [",
        ]
        for e in entries:
            msg.append("    {")
            msg.append(f'        "entity_type":        "{e["entity_type"]}",')
            msg.append(f'        "label":              "{e["label"]}",')
            msg.append(f'        "property":           "{e["property"]}",')
            msg.append(f'        "embedding_property": "{e["embedding_property"]}",')
            msg.append("    },")
        msg.append("]")
        raise RuntimeError("\n".join(msg))

    if strict is None:
        _warn(f"_rewrite_embeddable_block: strict regex missed in {path!r}; "
              f"used permissive fallback. The file may have been reformatted.")

    # Backup BEFORE we touch the file. shutil.copy preserves perms.
    backup = path + ".bak"
    try:
        shutil.copy(path, backup)
    except OSError as e:
        # Refuse to silently overwrite without a backup — failing here is
        # safer than losing a hand-edited config.
        raise RuntimeError(
            f"Could not write backup {backup!r}: {e}. Aborting rewrite."
        ) from e

    lines = ["EMBEDDABLE_PROPERTIES = ["]
    for e in entries:
        lines.append("    {")
        lines.append(f'        "entity_type":        "{e["entity_type"]}",')
        lines.append(f'        "label":              "{e["label"]}",')
        lines.append(f'        "property":           "{e["property"]}",')
        lines.append(f'        "embedding_property": "{e["embedding_property"]}",')
        lines.append("    },")
    lines.append("]")
    new_block = "\n".join(lines)

    new_text = text[:permissive.start()] + new_block + text[permissive.end():]
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    _ok(f"Backup written: {backup}")


# ──────────────────────────────────────────────────────────────────────────────
# Step 7 — Create vector indexes   [NEW]
# ──────────────────────────────────────────────────────────────────────────────

def step_create_vector_indexes(database: str) -> None:
    _header("Step 7 / 10 — Creating native vector indexes")

    import importlib
    import vector_config as vc
    importlib.reload(vc)

    spec = list(vc.EMBEDDABLE_PROPERTIES)
    if not spec:
        _warn("EMBEDDABLE_PROPERTIES is empty — nothing to index. "
              "(Did Step 6 run, or was --skip-embeddings passed?)")
        return

    from neo4j import GraphDatabase
    from embedding_helper import create_vector_indexes

    uri  = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USERNAME"]
    pwd  = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        # Pre-flight sanity check: skip any (label, property) whose carrier
        # nodes have 0 populated embeddings. CREATE VECTOR INDEX on an empty
        # corpus succeeds silently and every vector query then returns []
        # — a confusing zero-results failure mode for users who skipped /
        # crashed step 6 and ran step 7 in isolation.
        filtered: list = []
        sess_kwargs = {"database": database} if database else {}
        with driver.session(**sess_kwargs) as session:
            for entry in spec:
                if entry.get("entity_type", "node") != "node":
                    filtered.append(entry)   # rels passed through to be no-op'd downstream
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
                    _warn(f"{label}.{entry['property']}: 0 embedded nodes — "
                          f"skipping index. Did Step 6 run? "
                          f"Try `--reset-embeddings`.")
                    continue
                filtered.append(entry)

        if not filtered:
            _warn("No (label, property) has populated embeddings — no "
                  "vector indexes will be created.")
            return

        results = create_vector_indexes(driver, database, filtered)
    finally:
        driver.close()

    n_created = sum(1 for v in results.values() if v == "created")
    n_exists  = sum(1 for v in results.values() if v == "exists")
    for name, status in results.items():
        _ok(f"{status:<8s}  {name}")
    _ok(f"{n_created} created, {n_exists} already existed "
        f"(total {len(results)})")


# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# Step 8 — Generate @tool files (was step 6)
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_tools(database: str) -> None:
    _header("Step 8 / 10 — Generating @tool functions")

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
# Step 9 — Generate config.py (was step 7)
# ──────────────────────────────────────────────────────────────────────────────

def step_generate_config(database: str) -> None:
    _header("Step 9 / 10 — Generating config.py")

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
# Step 10 — Build FAISS tool-selection index (was step 8)
# ──────────────────────────────────────────────────────────────────────────────

def step_build_faiss() -> None:
    _header("Step 10 / 10 — Building FAISS tool-selection index")

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
        help="Skip Step 10 (FAISS index build) — useful when no OpenAI key yet",
    )
    p.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip Steps 6 + 7 (embedding backfill + vector indexes). "
             "Use for fast iteration while staying on TOOL_RETRIEVAL_MODE='fuzzy'.",
    )
    p.add_argument(
        "--rediscover",
        action="store_true",
        help="Force re-running auto-discovery in Step 6 even if "
             "EMBEDDABLE_PROPERTIES is non-empty in vector_config.py.",
    )
    p.add_argument(
        "--reset-embeddings",
        action="store_true",
        help="Drop existing vector indexes AND null out embedding properties "
             "before backfill. Required when swapping embedding backends with "
             "different dimensions (e.g. 1536 → 768).",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip all interactive confirmation prompts (CI / scripting).",
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
    #   Step 3 (schema CSV)            → writes schema_nodes.csv, schema_relations.csv
    #   Step 4 (schema meta)           → reads CSVs, writes schema_meta.json (LLM)
    #   Step 5 (fulltext indexes)      → unchanged from legacy
    #   Step 6 (backfill embeddings)   → reads schema_meta.json AND
    #                                     EMBEDDABLE_PROPERTIES (auto-discover
    #                                     if empty); writes embedding_property
    #                                     onto every relevant node
    #   Step 7 (vector indexes)        → reads EMBEDDABLE_PROPERTIES; bulk-builds
    #                                     HNSW on top of populated embeddings
    #                                     (must run AFTER step 6)
    #   Step 8 (gen tools)             → reads schema_meta.json AND vector index
    #                                     names from EMBEDDABLE_PROPERTIES;
    #                                     writes generated_*_tools.py
    #   Step 9 (gen config)            → imports generated tools to build
    #                                     NER_SP, writes config.py
    #   Step 10 (FAISS)                → imports generated tools (which import
    #                                     config.py)
    steps: List[tuple] = [
        ("Check environment",         lambda: step_check_env()),
        ("Test Neo4j connection",     lambda: step_test_connection(database)),
        ("Export schema to CSV",      lambda: step_export_schema(database)),
        ("Generate schema_meta.json", lambda: step_generate_schema_meta()),
        ("Create fulltext indexes",   lambda: step_create_indexes(database)),
    ]

    if not args.skip_embeddings:
        steps.append(
            ("Backfill embeddings",
             lambda: step_backfill_embeddings(
                 database,
                 rediscover=args.rediscover,
                 reset=args.reset_embeddings,
                 yes=args.yes,
             )),
        )
        steps.append(
            ("Create vector indexes",
             lambda: step_create_vector_indexes(database)),
        )

    steps.append(("Generate @tool files",   lambda: step_generate_tools(database)))
    steps.append(("Generate config.py",     lambda: step_generate_config(database)))

    if not args.skip_faiss:
        steps.append(("Build FAISS index",  lambda: step_build_faiss()))

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
        _print_final_summary(database, args)
    else:
        _banner("Setup Incomplete")
        print(
            f"\n  Failed step: {failed[0]}\n"
            "  Fix the issue above and re-run:\n\n"
            "    python setup_project.py\n",
            flush=True,
        )
        sys.exit(1)


def _print_final_summary(database: str, args: argparse.Namespace) -> None:
    """Print active embedding backend, indexes, and ablation guidance."""
    vc = None
    try:
        import importlib
        import vector_config as vc  # type: ignore[no-redef]
        importlib.reload(vc)
    except Exception as exc:  # pragma: no cover - defensive
        # Loud, not silent: if vector_config can't even be imported here we
        # most likely just corrupted it (e.g. a regex misfire in
        # _rewrite_embeddable_block). The user needs to know — otherwise
        # the banner says "Setup Complete" while the config is broken.
        _warn(f"Could not import vector_config.py for summary: {exc!r}. "
              f"If you ran with --rediscover, restore from "
              f"vector_config.py.bak and inspect.")
        vc = None  # type: ignore

    print("", flush=True)
    if vc is not None:
        print(f"  Embedding backend  : {vc.EMBEDDING_BACKEND!r} "
              f"({vc.EMBEDDING_MODEL_NAME}, dim={vc.EMBEDDING_DIMENSIONS})",
              flush=True)
        print(f"  Retrieval mode     : {vc.TOOL_RETRIEVAL_MODE!r}", flush=True)

        if not args.skip_embeddings and vc.EMBEDDABLE_PROPERTIES:
            from embedding_helper import index_name_for
            print(f"  Vector indexes     :", flush=True)
            for entry in vc.EMBEDDABLE_PROPERTIES:
                if entry.get("entity_type") == "node":
                    print(f"                       "
                          f"• {index_name_for(entry['label'], entry['property'])}",
                          flush=True)
        elif args.skip_embeddings:
            # Footgun catcher: iterative experiments routinely re-run setup
            # with --skip-embeddings to save time, then forget that any
            # nodes added since the last embedding run won't be retrievable
            # in vector / hybrid mode (they have no embedding property and
            # therefore won't appear in `db.index.vector.queryNodes` results).
            print("  Vector indexes     : skipped (--skip-embeddings)",
                  flush=True)
            print("                       New nodes added since the last "
                  "embedding", flush=True)
            print("                       run will NOT be retrievable in "
                  "vector /", flush=True)
            print("                       hybrid mode. Re-run without "
                  "--skip-", flush=True)
            print("                       embeddings to refresh.", flush=True)

    print(
        "\n  Ablation guide:\n"
        "    Switch retrieval mode by editing TOOL_RETRIEVAL_MODE in\n"
        "    vector_config.py to 'fuzzy' | 'vector' | 'hybrid'.\n"
        "    No regeneration of generated_*_tools.py is required for the\n"
        "    node value-lookup tools — they read the config at call time.\n"
        "\n  Try a query:\n"
        '    python ner_agent_auto.py "Your question here" --verbose\n',
        flush=True,
    )


if __name__ == "__main__":
    main()
