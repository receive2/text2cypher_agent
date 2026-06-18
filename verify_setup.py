#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_setup.py
===============
Pre-flight check for the evaluation harness.  Confirms that every
``(dataset, graph)`` **archive**'s node tools actually match the labels
in that pair's Neo4j graph — BEFORE you spend hours evaluating.

Run this and read the table.  Green means the archive's tools belong to
the graph; red means the archive is **contaminated** (its tools belong
to a different graph) and any eval on it will silently score at the
no-val-link floor.  See ``eval/graph_guard.py`` for why this can happen.

Usage
-----
    python verify_setup.py            # check eval_config.EVAL_PAIRS (default)
    python verify_setup.py --all      # check every pair in GRAPH_CONNS
    python verify_setup.py --live     # check the LIVE tree vs .current_setup

Exit status
-----------
    0  every checked pair is OK
    1  at least one pair failed (contaminated / unreachable / missing)

Reaching the graphs requires the corporate VPN DISCONNECTED (see the
env-vpn-proxy note); a connection error is reported per-pair, not a crash.
"""

from __future__ import annotations

import sys
from pathlib import Path

import eval_config as cfg
from eval.artifact_swap import archive_dir_for, _read_sentinel
from eval.graph_guard import check_tools_match_graph
from paths import REPO_ROOT

_NODE_TOOLS_REL = "generated/generated_node_tools.py"


def _check_archive(dataset: str, graph: str) -> tuple[str, str]:
    """Return (status, detail) for one archive — non-destructive."""
    archive = archive_dir_for(dataset, graph)
    tools = archive / _NODE_TOOLS_REL
    if not tools.is_file():
        return "MISSING", f"no archive at {archive} (run setup_and_archive.py)"
    try:
        conn = cfg.conn_for(dataset, graph)
    except KeyError as exc:
        return "NO-CONN", str(exc)
    try:
        ok, detail = check_tools_match_graph(
            tools, conn.uri, conn.user, conn.password, conn.database
        )
    except Exception as exc:  # noqa: BLE001 — connection / driver errors
        return "UNREACH", f"{type(exc).__name__}: {exc}"
    return ("OK" if ok else "CONTAM"), detail


def _check_live() -> int:
    """Check the live tree against whatever .current_setup names."""
    pair = _read_sentinel()
    if not pair:
        print("✗ no .current_setup sentinel — live tree identity unknown.")
        return 1
    try:
        dataset, graph = pair.split("__", 1)
    except ValueError:
        print(f"✗ malformed sentinel {pair!r}.")
        return 1
    try:
        conn = cfg.conn_for(dataset, graph)
    except KeyError as exc:
        print(f"✗ sentinel names {pair} but no GraphConn: {exc}")
        return 1
    ok, detail = check_tools_match_graph(
        REPO_ROOT / _NODE_TOOLS_REL, conn.uri, conn.user, conn.password, conn.database
    )
    mark = "✓" if ok else "✗"
    print(f"{mark} LIVE tree (sentinel={pair}): {detail}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--live" in argv:
        return _check_live()

    pairs = (
        list(cfg.GRAPH_CONNS.keys())
        if "--all" in argv
        else list(getattr(cfg, "EVAL_PAIRS", []) or [])
    )
    if not pairs:
        print("[verify_setup] nothing to check (EVAL_PAIRS empty; use --all).")
        return 1

    scope = "GRAPH_CONNS (--all)" if "--all" in argv else "EVAL_PAIRS"
    print(f"[verify_setup] checking {len(pairs)} archive(s) from {scope}…\n")

    results = [(ds, gr, *_check_archive(ds, gr)) for ds, gr in pairs]

    # Aligned table.
    wpair = max((len(f"{ds}__{gr}") for ds, gr, *_ in results), default=4)
    bad = 0
    for ds, gr, status, detail in results:
        mark = "✓" if status == "OK" else "✗"
        if status != "OK":
            bad += 1
        print(f"  {mark} {f'{ds}__{gr}':<{wpair}}  {status:<7}  {detail}")

    print()
    if bad:
        print(f"[verify_setup] ✗ {bad}/{len(results)} FAILED — do NOT evaluate "
              "these until fixed (re-run scripts/setup_and_archive.py).")
        return 1
    print(f"[verify_setup] ✓ all {len(results)} archives match their graphs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
