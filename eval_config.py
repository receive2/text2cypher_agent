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

import os
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
#
# All 13 graphs below are deployed on the shared GCP VM at
# ``136.112.47.158`` (us-central1-a); each graph runs in its own Docker
# container distinguished by bolt port.  See ``docs/GRAPHS.md`` for the
# canonical schema (node labels, rel types) and node/relation counts.
#
# All graphs share the same Neo4j credentials.  Replace ``_NEO4J_PASSWORD``
# with the real password before running the harness — this file is
# gitignored so the live secret stays off the repo.
# The VM's external IP is ephemeral (it drifts on every stop/start). Override
# without editing this file via:  export EVAL_NEO4J_HOST=<current-ip>
# (Reaching this VM requires the corporate VPN DISCONNECTED — see the
# env-vpn-proxy memory.)  Reserve a static IP to stop the drift.
_NEO4J_HOST     = os.environ.get("EVAL_NEO4J_HOST", "34.9.85.21")
_NEO4J_USER     = "neo4j"
_NEO4J_PASSWORD = "37fhWZ746X9QCwxPUoU5"  # TODO: paste the shared neo4j password here


def _conn(port: int) -> GraphConn:
    """Build a :class:`GraphConn` for a graph on the shared VM."""
    return GraphConn(
        uri=f"bolt://{_NEO4J_HOST}:{port}",
        user=_NEO4J_USER,
        password=_NEO4J_PASSWORD,
    )


GRAPH_CONNS: dict[tuple[str, str], GraphConn] = {
    # ── CypherBench ────────────────────────────────────────────────────────
    ("cypherbench",  "company"):             _conn(15062),
    ("cypherbench",  "fictional_character"): _conn(15063),
    ("cypherbench",  "flight_accident"):     _conn(15064),
    ("cypherbench",  "geography"):           _conn(15065),
    ("cypherbench",  "movie"):               _conn(15066),
    ("cypherbench",  "nba"):                 _conn(15067),
    ("cypherbench",  "politics"):            _conn(15068),
    # ── Mind-the-Query ─────────────────────────────────────────────────────
    # NOTE: these graph keys are Mind-the-Query's OWN upstream short-names (the
    # labels of their Datasets/*.dump files), kept verbatim so the `graph` field
    # joins their released data — DO NOT rename (that would diverge from the
    # source benchmark). They are *not* descriptive: each is a standard Neo4j
    # graph-example dataset. Real identities (verified against the .dump names
    # and the live DB schemas):
    #   bloom50    → Neo4j Bloom bank-fraud demo (AccountHolder/BankAccount/CreditCard; bloom-50.dump)
    #   covid      → contact-tracing            (Person/Place/Visit/Region; contact-tracing-50.dump) — NOT a generic "covid" dataset
    #   er         → entity-resolution          (User/IpAddress/Movie; entity-resolution-50.dump)
    #   healthcare → healthcare-analytics       (Drug/Case/Reaction/Outcome — FDA adverse events; healthcare-analytics-50.dump)
    #   wwc        → wwc2019                     (Women's World Cup 2019; wwc2019-50.dump)
    ("mindthequery", "bloom50"):             _conn(15071),   # Bloom bank-fraud demo
    ("mindthequery", "bloom"):               _conn(15071),   # alias: test-data graph field is "bloom" (dump name is bloom50)
    ("mindthequery", "covid"):               _conn(15072),   # contact-tracing
    ("mindthequery", "er"):                  _conn(15073),   # entity-resolution
    ("mindthequery", "healthcare"):          _conn(15074),   # healthcare-analytics
    ("mindthequery", "wwc"):                 _conn(15075),   # wwc2019
    # ── ZOGRASCOPE ─────────────────────────────────────────────────────────
    ("zograscope",   "pole"):                _conn(15076),
}


# ── Augmented variants ───────────────────────────────────────────────────────
# Augmenting a dataset only rewrites the natural-language question; the
# gold Cypher and the underlying property graph are unchanged.  So every
# ``*_augmented`` pair reuses the exact same Neo4j connection as its
# base sibling.  We register the augmented pairs programmatically so a
# new base pair is automatically mirrored without a second hand-edit.
GRAPH_CONNS.update({
    (f"{ds}_augmented", graph): conn
    for (ds, graph), conn in list(GRAPH_CONNS.items())
})


# Which (dataset, graph) pairs to evaluate on the next run of eval_run.py.
# Edit this between runs to do partial evals; existing on-disk records
# persist and are picked up by ``eval_aggregate.py``.
#
# Default: every registered pair.  Comment out / shrink to do a partial
# eval; aggregation reads everything on disk regardless of what ran last.


EVAL_PAIRS: list[tuple[str, str]] = [
    ("cypherbench_augmented", "movie"),
]

_FULL_EVAL_PAIRS_13: list[tuple[str, str]] = [
    # ── CypherBench ────────────────────────────────────────────────────────
    ("cypherbench",            "company"),
    ("cypherbench",            "fictional_character"),
    ("cypherbench",            "flight_accident"),
    ("cypherbench",            "geography"),
    ("cypherbench",            "movie"),
    ("cypherbench",            "nba"),
    ("cypherbench",            "politics"),
    # ── Mind-the-Query ─────────────────────────────────────────────────────
    ("mindthequery",           "bloom50"),
    ("mindthequery",           "covid"),
    ("mindthequery",           "er"),
    ("mindthequery",           "healthcare"),
    ("mindthequery",           "wwc"),
    # ── ZOGRASCOPE ─────────────────────────────────────────────────────────
    ("zograscope",             "pole"),
]


# Important: list each base pair BEFORE its augmented sibling.
# scripts/setup_and_archive.py copies the base archive verbatim into
# the augmented archive directory (skipping setup_project.py + Neo4j
# embedding reset entirely), but only when the base archive already
# exists on disk — so base-first ordering avoids a redundant full setup.


# EVAL_PAIRS: list[tuple[str, str]] = [
#     ("zograscope",   "pole"),    
# ]


# ── Test-set paths (per dataset, not per graph) ──────────────────────────────
# Datasets ship one combined test file that internally tags each example
# with its graph; the worker filters per-pair via ``graph_filter``.

# CypherBench: path to the test set JSON / JSONL.

# Mind-the-Query: path to a single *.json file or to the
# ``Train_Test_Splits/Manual`` (or ``Automated``) directory; the loader
# walks it recursively and concatenates every ``*_test.json`` file it
# finds.  See :mod:`eval.metrics_MindTheQuery` for accepted layouts.

# ZOGRASCOPE: path to ``data/zograscope_test_v1.csv``.

# Test-set paths
CYPHERBENCH_PATH  = "/Users/q0w01lh/datasets/cypherbench/test.json"
MINDTHEQUERY_PATH = "/Users/q0w01lh/datasets/mindthequery/Train_Test_Splits/Manual"
ZOGRASCOPE_PATH   = "/Users/q0w01lh/datasets/zograscope/data/zograscope_test_v1.csv"

# Augmented test-set paths — populated by ``run_data_augmentation.py``.
# Each augmented dataset mirrors the source layout under a sibling
# ``<dataset>_augmented/`` directory.  The eval harness picks these up
# when an ``EVAL_PAIRS`` entry uses an ``*_augmented`` dataset name.
CYPHERBENCH_AUGMENTED_PATH  = "/Users/q0w01lh/datasets/cypherbench_augmented_v2/test.json"
MINDTHEQUERY_AUGMENTED_PATH = "/Users/q0w01lh/datasets/mindthequery_augmented_v2/test.json"
ZOGRASCOPE_AUGMENTED_PATH   = "/Users/q0w01lh/datasets/zograscope_augmented_v2/test.json"


# ── Output dirs ──────────────────────────────────────────────────────────────

# Per-(dataset, graph) records + summary live here.  File naming:
#     <dataset>__<graph>.records.jsonl
#     <dataset>__<graph>.summary.json
OUT_DIR = "logs/header5_movie"

# Archived per-graph setup outputs (one subdir per (dataset, graph) pair).
SETUP_ARTIFACTS_ROOT = "setup_artifacts"


# ── Run-time switches ────────────────────────────────────────────────────────

# Per-dataset cap on examples (None = all).  Applied independently for
# each (dataset, graph) pair after the graph filter.
#LIMIT: int | None = 100
LIMIT: int | None = 100

# Verbose per-example log lines.
VERBOSE: bool = True

# Intra-graph parallelism. Each (dataset, graph) pair's examples are split into
# SHARDS stride-shards run as SHARDS parallel worker processes against the same
# container, then merged — wall-clock ≈ 1/SHARDS. SHARDS=1 is the original
# single-process behaviour (byte-identical coverage). Graphs are still run
# sequentially (a single shared live artifact tree is swapped per graph), so
# only the examples WITHIN a graph parallelise. Raise/lower per your CPU + LLM
# rate limits.
SHARDS: int = 8

# Where generated reports are written: REPORT_DIR/<dataset>/<graph>.md and
# REPORT_DIR/<dataset>/_summary.md. Default "report".
REPORT_DIR: str = "report"



# python scripts/setup_and_archive.py
# python eval_run.py
# python eval_aggregate.py

#tail -f logs/eval/cypherbench_augmented__movie.records.jsonl | jq -c '{i:1,qid:.qid[:8],ea,psjs,t:.elapsed_total_sec}'

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
