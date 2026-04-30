#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_config.py
==============
Single source of truth for the t2c text-to-Cypher evaluation harness
under the **per-graph** architecture.

This is *not* an argparse-driven CLI config — it's a plain Python module
that the user hand-edits between runs.  The harness is composed of three
scripts that all read from this module:

    setup_and_archive.py  -- one-time per-graph setup + artifact archive
    eval_run.py           -- runs evaluation in fresh subprocesses
    eval_aggregate.py     -- prints a bucketed table over everything on disk

Each evaluated graph lives in its own Docker container with its own URI
and credentials; ``GRAPH_CONNS`` is the registry.  ``EVAL_PAIRS`` is the
slice of that registry to actually run on the next ``python eval_run.py``.

Privacy note
------------
``GRAPH_CONNS`` is the **single source of truth for connection info**.
Credentials live here, not in ``.env``.  This file is gitignored
(see ``.gitignore``); if it was already committed you must
``git rm --cached eval_config.py`` to untrack the live copy without
deleting it from disk.

Edit, save, then run::

    python eval_run.py
    python eval_aggregate.py
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Connection registry ──────────────────────────────────────────────────────

@dataclass
class GraphConn:
    """
    Per-graph Neo4j connection.

    Each graph lives in its own Docker container, with its own bolt URI
    and credentials.  The default ``database`` is ``"neo4j"`` because the
    intra-container DB name is independent of the graph name itself —
    distinct graphs are distinguished by the URI / port, not by the DB
    name inside the container.
    """
    uri:      str
    user:     str
    password: str
    database: str = "neo4j"


# (dataset, graph) -> connection.  Graph names can collide across datasets
# (CypherBench's ``movie`` vs Mind-the-Query's ``movie`` are different
# datasets), so we key on the pair rather than on graph alone.
GRAPH_CONNS: dict[tuple[str, str], GraphConn] = {
    # Examples — uncomment and edit:
    # ("cypherbench",  "movie"):       GraphConn(uri="bolt://localhost:7687", user="neo4j", password="..."),
    # ("cypherbench",  "nba"):         GraphConn(uri="bolt://localhost:7688", user="neo4j", password="..."),
    # ("mindthequery", "bloom50"):     GraphConn(uri="bolt://localhost:7689", user="neo4j", password="..."),
    # ("zograscope",   "pole"):        GraphConn(uri="bolt://localhost:7690", user="neo4j", password="..."),
}


# Which (dataset, graph) pairs to evaluate on the next run of eval_run.py.
# Edit this between runs to do partial evals; existing on-disk records
# persist and are picked up by ``eval_aggregate.py``.
EVAL_PAIRS: list[tuple[str, str]] = [
    # ("cypherbench", "movie"),
]


# ── Test-set paths (per dataset, not per graph) ──────────────────────────────
# Datasets ship one combined test file that internally tags each example
# with its graph; the worker filters per-pair via ``graph_filter``.

# CypherBench: path to the test set JSON / JSONL.
CYPHERBENCH_PATH = "path/to/cypherbench_test.jsonl"

# Mind-the-Query: path to a single *.json file or to the
# ``Train_Test_Splits/Manual`` (or ``Automated``) directory; the loader
# walks it recursively and concatenates every ``*_test.json`` file it
# finds.  See :mod:`eval.metrics_MindTheQuery` for accepted layouts.
MINDTHEQUERY_PATH = "path/to/Mind-the-Query/Train_Test_Splits/Manual"

# ZOGRASCOPE: path to ``data/zograscope_test_v1.csv``.
ZOGRASCOPE_PATH = "path/to/ZOGRASCOPE/data/zograscope_test_v1.csv"


# ── Output dirs ──────────────────────────────────────────────────────────────

# Per-(dataset, graph) records + summary live here.  File naming:
#     <dataset>__<graph>.records.jsonl
#     <dataset>__<graph>.summary.json
OUT_DIR = "logs/eval"

# Archived per-graph setup outputs (one subdir per (dataset, graph) pair).
SETUP_ARTIFACTS_ROOT = "setup_artifacts"


# ── Run-time switches ────────────────────────────────────────────────────────

# Per-dataset cap on examples (None = all).  Applied independently for
# each (dataset, graph) pair after the graph filter.
LIMIT: int | None = None

# Verbose per-example log lines.
VERBOSE: bool = False


# ── Helpers ──────────────────────────────────────────────────────────────────

def conn_for(dataset: str, graph: str) -> GraphConn:
    """
    Look up the :class:`GraphConn` for a (dataset, graph) pair.

    Raises
    ------
    KeyError
        If the pair is missing, with a message listing every key
        currently registered in :data:`GRAPH_CONNS` so the caller can see
        what's available.
    """
    try:
        return GRAPH_CONNS[(dataset, graph)]
    except KeyError as exc:
        available = sorted(GRAPH_CONNS.keys())
        raise KeyError(
            f"No GraphConn registered for ({dataset!r}, {graph!r}). "
            f"Available pairs in eval_config.GRAPH_CONNS: {available}"
        ) from exc
