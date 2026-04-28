#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
switch_embedding_backend.py
===========================
One-click embedding-backend swap.

Use this AFTER you have already run the full `setup_project.py` once on
your database. It re-embeds every value with the currently selected
backend in `vector_config.py` and rebuilds the matching vector indexes —
WITHOUT touching `generated_*_tools.py`, `config.py`, or
`faiss_tools_auto/` (those are independent of which embedding backend
powers vector retrieval).

Works in either direction:
    OpenAI (1536d)  →  BGE (768d)
    BGE   (768d)    →  OpenAI (1536d)

Procedure (OpenAI → BGE):
    1. pip install sentence-transformers torch
    2. Edit vector_config.py:  EMBEDDING_BACKEND = "sentence_transformers"
    3. python switch_embedding_backend.py

Procedure (BGE → OpenAI):
    1. Edit vector_config.py:  EMBEDDING_BACKEND = "openai"
    2. python switch_embedding_backend.py
       (sentence-transformers stays installed; it's just unused)

Flags:
    --yes        skip the "type the backend name to confirm" prompt
    --database   override NEO4J_DATABASE from .env
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(".env", override=True)


_WIDTH = 70


def _hr():
    print("─" * _WIDTH, flush=True)


def _banner(title: str) -> None:
    print("\n" + "═" * _WIDTH, flush=True)
    pad = (_WIDTH - len(title) - 2) // 2
    print("═" * pad + f" {title} " + "═" * pad, flush=True)
    print("═" * _WIDTH, flush=True)


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}", flush=True)


def _warn(msg: str) -> None:
    print(f"  ⚠  {msg}", flush=True)


def _fail(msg: str) -> None:
    print(f"\n  ✗  {msg}", flush=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="One-click swap between OpenAI and BGE embedding backends.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--database",
        default=os.getenv("NEO4J_DATABASE", "neo4j"),
        metavar="DB",
        help="Neo4j database (overrides NEO4J_DATABASE in .env)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt (CI / scripting).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    database = args.database

    _banner("Embedding Backend Swap")

    # ── Step 1: load the requested backend from vector_config.py ─────────────
    print("\n  Step 1 / 5 — Reading vector_config.py", flush=True)
    _hr()
    try:
        import vector_config as vc
        importlib.reload(vc)
    except Exception as e:
        _fail(f"Could not import vector_config.py: {e}")
        sys.exit(1)

    target_backend = vc.EMBEDDING_BACKEND
    target_model   = vc.EMBEDDING_MODEL_NAME
    target_dim     = vc.EMBEDDING_DIMENSIONS

    if target_backend not in ("openai", "sentence_transformers"):
        _fail(f"Unknown EMBEDDING_BACKEND={target_backend!r} in vector_config.py. "
              f"Set it to 'openai' or 'sentence_transformers' and re-run.")
        sys.exit(1)

    _ok(f"Target backend = {target_backend!r}")
    _ok(f"Target model   = {target_model}  (dim={target_dim})")

    spec = list(vc.EMBEDDABLE_PROPERTIES)
    if not spec:
        _fail("EMBEDDABLE_PROPERTIES is empty in vector_config.py. "
              "Run `python setup_project.py` first to discover them.")
        sys.exit(1)
    _ok(f"{len(spec)} (label, property) pair(s) to re-embed")

    # ── Step 2: pre-flight (deps + Neo4j env + dim probe) ────────────────────
    print("\n  Step 2 / 5 — Pre-flight checks", flush=True)
    _hr()

    if target_backend == "sentence_transformers":
        try:
            import sentence_transformers  # noqa: F401
            import torch                   # noqa: F401
        except ImportError:
            _fail("sentence-transformers / torch not installed.\n"
                  "    Install with:  pip install sentence-transformers torch")
            sys.exit(1)
        _ok("sentence-transformers + torch installed")
    elif target_backend == "openai":
        if not os.getenv("OPENAI_API_KEY") and not (
            os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY")
        ):
            _fail("OPENAI_API_KEY (or Azure equivalent) is required for the "
                  "openai backend. Set it in .env and re-run.")
            sys.exit(1)
        _ok("OpenAI credentials found")

    for v in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        if not os.getenv(v):
            _fail(f"Missing required env var: {v}")
            sys.exit(1)
    _ok(f"Neo4j env vars present  (database={database!r})")

    # Reset cached singletons BEFORE verify_backend — without this, an OpenAI
    # client cached by a previous run can still be used after we've switched
    # to BGE, and the dim sanity check fails confusingly.
    import embedding_helper as eh
    eh.reset_caches()

    try:
        eh.verify_backend()
    except Exception as e:
        _fail(f"Backend verification failed: {e}")
        sys.exit(1)
    _ok(f"verify_backend OK  (dim={target_dim} confirmed live)")

    # ── Confirmation gate ────────────────────────────────────────────────────
    print(
        f"\n  About to:\n"
        f"    1. drop existing vector indexes\n"
        f"    2. clear existing embedding properties on every relevant node\n"
        f"    3. re-embed all distinct values with {target_backend!r}\n"
        f"    4. recreate vector indexes (dim={target_dim})\n",
        flush=True,
    )
    if not args.yes:
        ans = input(
            f"  Type the backend name to confirm  [{target_backend}] : "
        ).strip()
        if ans != target_backend:
            _warn("Confirmation mismatch — aborting.")
            sys.exit(1)

    # ── Step 3: drop old vector indexes + null old embeddings ────────────────
    print("\n  Step 3 / 5 — Dropping old indexes + clearing embeddings", flush=True)
    _hr()

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    try:
        # 5.18 sanity probe — same gate setup_project.py uses.
        try:
            eh.check_neo4j_version(driver, database)
        except RuntimeError as ve:
            _fail(str(ve))
            sys.exit(1)

        dropped = eh.drop_vector_indexes(driver, database, spec)
        for iname in dropped:
            _ok(f"dropped index {iname}")
        if not dropped:
            _ok("no existing vector indexes to drop")

        n_null = eh.null_embedding_properties(driver, database, spec)
        _ok(f"cleared embeddings on {n_null} node(s)")

        # ── Step 4: backfill with the new backend ─────────────────────────────
        print(f"\n  Step 4 / 5 — Re-embedding with {target_backend!r}", flush=True)
        _hr()

        t0 = time.time()
        summary = eh.backfill_embeddings(driver, database, spec)
        for (label, prop), stats in summary.items():
            _ok(f"{label}.{prop}: embedded={stats['embedded']} "
                f"distinct={stats['distinct_values']} "
                f"elapsed={stats['elapsed_s']:.2f}s")
        _ok(f"total backfill elapsed = {time.time() - t0:.2f}s")

        # ── Step 5: create new vector indexes ─────────────────────────────────
        print("\n  Step 5 / 5 — Creating vector indexes", flush=True)
        _hr()

        results = eh.create_vector_indexes(driver, database, spec)
        for name, status in results.items():
            _ok(f"{status:<8s}  {name}")

    finally:
        driver.close()

    # ── Final summary ────────────────────────────────────────────────────────
    _banner("Swap Complete")
    print(
        f"\n  Active backend     : {target_backend!r}\n"
        f"  Model              : {target_model}\n"
        f"  Dimension          : {target_dim}\n"
        f"  Vector indexes     : {len(results)} ready\n"
        f"\n  generated_node_tools.py / generated_rel_tools.py / config.py /\n"
        f"  faiss_tools_auto/  were NOT regenerated (intentionally —\n"
        f"  they are independent of the embedding backend).\n"
        f"\n  Try a query:\n"
        f"    python ner_agent_auto.py \"Your question here\" --verbose\n",
        flush=True,
    )


if __name__ == "__main__":
    main()
