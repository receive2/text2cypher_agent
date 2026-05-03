#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/_worker.py
===============
Subprocess entry point for evaluating one ``(dataset, graph)`` pair.

Why a subprocess?
-----------------
Python module caching makes in-process module reload unreliable for the
agent stack: ``from X import Y`` bindings go stale, the
``langchain_neo4j.Neo4jGraph`` driver caches a connection per process,
FAISS stores are cached at module level, and the auto-generated tools
(:mod:`generated.generated_node_tools`, :mod:`agent.prompts`) are
imported eagerly during ``ner_agent_auto`` startup.  Swapping artifacts
between graphs and re-importing in-process leaves dangling references
to the previous graph's modules.

A fresh subprocess sidesteps the whole problem: every (dataset, graph)
pair gets its own Python process, its own module table, and its own
Neo4j driver pointed at the right container.

Usage
-----
::

    python -m eval._worker <dataset> <graph> <test_path> \\
        <out_records> <out_summary> [--limit N] [--verbose]

Inputs
~~~~~~
* CLI args:   ``dataset``, ``graph``, ``test_path``, ``out_records``,
              ``out_summary`` (positional, in order), plus ``--limit``
              and ``--verbose`` flags.
* Env vars:   ``EVAL_NEO4J_URI`` / ``EVAL_NEO4J_USER`` /
              ``EVAL_NEO4J_PASSWORD`` / ``EVAL_NEO4J_DATABASE`` —
              copied into the standard ``NEO4J_*`` names that the
              existing agent / Neo4j helpers read at import time.

This worker deliberately does **not** import :mod:`eval_config`.  All
inputs come via argv + env vars; the parent driver
(:mod:`eval_run`) is the only place that talks to the config module.
That isolation is what makes the worker safe to run inside the smoke
tests against a config-free, locally-hosted Neo4j.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict


# ──────────────────────────────────────────────────────────────────────────────
# 1. Env-var bridge
# ──────────────────────────────────────────────────────────────────────────────

_ENV_BRIDGE = (
    # (worker-side name, in-process name expected by agent_helper / etc.)
    ("EVAL_NEO4J_URI",      "NEO4J_URI"),
    ("EVAL_NEO4J_USER",     "NEO4J_USERNAME"),
    ("EVAL_NEO4J_PASSWORD", "NEO4J_PASSWORD"),
    ("EVAL_NEO4J_DATABASE", "NEO4J_DATABASE"),
)


def _bridge_env() -> None:
    """
    Copy ``EVAL_NEO4J_*`` env vars into the standard ``NEO4J_*`` names so
    :mod:`agent.agent_helper` (and any other module that reads the
    standard names at import time) connects to the right container.
    """
    missing = []
    for src, dst in _ENV_BRIDGE:
        val = os.environ.get(src)
        if val is None:
            missing.append(src)
            continue
        # Worker-side env wins over any pre-existing value.
        os.environ[dst] = val

    if missing:
        # NEO4J_DATABASE has a sane default ("neo4j") in agent_helper, so
        # only the URI / user / password are strictly required.
        required = {"EVAL_NEO4J_URI", "EVAL_NEO4J_USER", "EVAL_NEO4J_PASSWORD"}
        missing_required = [m for m in missing if m in required]
        if missing_required:
            raise RuntimeError(
                f"eval._worker: missing required env vars {missing_required}. "
                "These are set by the parent eval_run.py from "
                "eval_config.GRAPH_CONNS — did you launch the worker by hand?"
            )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Dataset dispatch
# ──────────────────────────────────────────────────────────────────────────────

def _load_evaluate_dataset(dataset: str) -> Callable[..., Dict[str, Any]]:
    """
    Return the matching ``evaluate_dataset`` for *dataset* (lazy import).

    Augmented variants (``cypherbench_augmented`` / etc.) share the
    underlying loader + evaluator with their base variant; the
    :mod:`eval.dataset_base` mapping does the lookup.  The dataset name
    seen on the wire is forwarded to the metrics module separately so
    summary output reflects the augmented variant.
    """
    from eval.dataset_base import base_dataset

    base = base_dataset(dataset)  # raises ValueError on unknown name

    if base == "cypherbench":
        from eval.metrics_CypherBench import evaluate_dataset
    elif base == "mindthequery":
        from eval.metrics_MindTheQuery import evaluate_dataset
    elif base == "zograscope":
        from eval.metrics_ZOGRASCOPE import evaluate_dataset
    else:
        # Unreachable while _DATASET_BASE values stay in the known set,
        # but kept defensively in case the mapping grows in future.
        raise ValueError(
            f"eval._worker: dataset_base for {dataset!r} resolved to "
            f"unknown base {base!r}."
        )
    return evaluate_dataset


# ──────────────────────────────────────────────────────────────────────────────
# 3. Entry point
# ──────────────────────────────────────────────────────────────────────────────

def _summary_only(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Strip the (potentially huge) per-example records list from *summary*."""
    return {k: v for k, v in summary.items() if k != "records"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m eval._worker",
        description="Evaluate one (dataset, graph) pair in an isolated subprocess.",
    )
    ap.add_argument("dataset",     help="One of 'cypherbench' | 'mindthequery' | 'zograscope'.")
    ap.add_argument("graph",       help="Graph name (matches the 'graph' field on test examples).")
    ap.add_argument("test_path",   help="Path forwarded to evaluate_dataset(path=...).")
    ap.add_argument("out_records", help="JSONL output path for per-example records.")
    ap.add_argument("out_summary", help="JSON output path for the aggregate summary.")
    ap.add_argument("--limit",   type=int, default=None,
                    help="Optional cap on examples (None = all).")
    ap.add_argument("--verbose", action="store_true",
                    help="Per-example log lines.")
    args = ap.parse_args(argv)

    _bridge_env()

    evaluate_dataset = _load_evaluate_dataset(args.dataset)

    summary = evaluate_dataset(
        path         = args.test_path,
        limit        = args.limit,
        out          = args.out_records,
        verbose      = args.verbose,
        graph_filter = args.graph,
        dataset_name = args.dataset,
    )

    out_path = Path(args.out_summary)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(_summary_only(summary), fh, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 — surface every failure
        traceback.print_exc()
        sys.exit(1)
