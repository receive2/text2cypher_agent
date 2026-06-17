#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_fcav.py
=============
Build the FCAV baseline's per-graph VectorDB for every ``(dataset, graph)``
pair in :data:`eval_config.EVAL_PAIRS`, and fold each index into that graph's
setup-artifact archive so the evaluation harness's ``swap_in`` restores the
right FCAV index per graph.

Per pair:
  1. ``swap_in`` the graph's existing archive into the live tree (so the
     re-archive below stays consistent with the graph's other artifacts).
  2. Connect via :func:`eval_config.conn_for`, extract distinct
     ``(value, label, key)`` triples for identifying string properties,
     embed them, and write the FAISS index to ``generated/fcav/``.
  3. ``archive_current`` folds ``generated/fcav/`` (an optional swap dir) into
     ``setup_artifacts/<dataset>__<graph>/``.

Usage
-----
    # edit eval_config.EVAL_PAIRS to the graphs you want, then:
    python setup_fcav.py [--include-descriptions] [--embedding-model NAME]

Embedding backend defaults to ``vector_config`` (``text-embedding-3-small``).
``--embedding-model`` overrides the model for this build (recorded in each
manifest). Prerequisite: each graph already has a base archive (from
``scripts/setup_and_archive.py``) so ``swap_in`` works.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
load_dotenv(".env", override=False)

import eval_config as cfg
from eval.artifact_swap import swap_in, archive_current
from fcav import build_fcav_index, FCAV_DIR


def main() -> int:
    ap = argparse.ArgumentParser(description="Build per-graph FCAV VectorDBs over EVAL_PAIRS.")
    ap.add_argument("--include-descriptions", action="store_true",
                    help="also embed description / all string props (much larger index)")
    ap.add_argument("--embedding-model", default=None,
                    help="override vector_config.EMBEDDING_MODEL_NAME for this build")
    args = ap.parse_args()

    import vector_config as vc
    if args.embedding_model:
        vc.EMBEDDING_MODEL_NAME = args.embedding_model
        print(f"[setup_fcav] embedding model overridden → {args.embedding_model}")

    pairs = list(getattr(cfg, "EVAL_PAIRS", []) or [])
    if not pairs:
        sys.exit("[setup_fcav] eval_config.EVAL_PAIRS is empty — nothing to build.")

    done, failed = [], None
    for dataset, graph in pairs:
        print(f"\n[setup_fcav] ▶ {dataset}__{graph}")
        try:
            swap_in(dataset, graph)                       # 1. restore graph's archive
            conn = cfg.conn_for(dataset, graph)           # 2. connect + build
            driver = GraphDatabase.driver(conn.uri, auth=(conn.user, conn.password))
            try:
                m = build_fcav_index(driver, conn.database,
                                     include_descriptions=args.include_descriptions)
            finally:
                driver.close()
            archive_current(dataset, graph, force=True)   # 3. fold fcav into archive
            print(f"[setup_fcav] ✓ {dataset}__{graph}: {m['count']} values, dim {m['dimensions']}, "
                  f"{m['embedding_backend']}/{m['embedding_model']}")
            done.append((dataset, graph))
        except Exception as exc:  # noqa: BLE001
            failed = (dataset, graph, str(exc))
            logging.getLogger("t2c.fcav").error("✗ %s__%s: %s", dataset, graph, exc)
            break

    print(f"\n[setup_fcav] done: {len(done)} built" + (f", FAILED at {failed[0]}__{failed[1]}: {failed[2]}" if failed else ""))
    print(f"[setup_fcav] live index dir: {FCAV_DIR}")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
