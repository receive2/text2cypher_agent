#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_setup.py
===============
Pre-flight check for the evaluation harness.  For every ``(dataset, graph)``
pair it confirms two things BEFORE you spend hours evaluating:

1. the **archive**'s node tools actually match the labels in that pair's
   Neo4j graph (``eval/graph_guard.py``) — otherwise the archive is
   **contaminated** (its tools belong to a different graph) and any eval on
   it silently scores at the no-val-link floor;
2. the archive's prompts / tools / schema files / routing index are
   byte-identical to the **published set** (``setup_artifacts/MANIFEST.json``,
   ``scripts/artifact_manifest.py``) — otherwise your numbers cannot be pooled
   with anyone else's, because the model comparison assumes every generator
   saw the same prompts and tools.

Run this and read the table: every line must be ✓.  ``!`` means the
coordinator has not published that graph yet — wait, do not build it
yourself.

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
from eval.artifact_swap import archive_dir_for, _read_sentinel, _setup_artifacts_root
from eval.graph_guard import check_tools_match_graph
from paths import REPO_ROOT
from scripts import artifact_manifest as am

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

    root = _setup_artifacts_root()
    manifest = am.load_manifest(am.manifest_path(root))
    if manifest is None:
        print(f"[verify_setup] ! no {am.MANIFEST_NAME} under {root} — git pull; "
              "the published artifact set ships in the repo.\n")

    results = [(ds, gr, *_check_archive(ds, gr), *am.check_pair(manifest, root, ds, gr))
               for ds, gr in pairs]

    # Aligned table: graph check | published-set check.
    wpair = max((len(f"{ds}__{gr}") for ds, gr, *_ in results), default=4)
    bad = unpublished = skipped = 0
    for ds, gr, status, detail, mstatus, mdetail in results:
        if status == "MISSING" and mstatus == am.UNPUBLISHED and "--all" in argv:
            # --all walks every registered pair; an archive that neither exists
            # nor is published is simply not part of the sweep — not a failure.
            skipped += 1
            print(f"  · {f'{ds}__{gr}':<{wpair}}  no archive, not in the published set — skipped")
            continue
        if status != "OK" or mstatus in (am.MISMATCH, am.MISSING):
            mark, bad = "✗", bad + 1
        elif mstatus == am.UNPUBLISHED:
            mark, unpublished = "!", unpublished + 1
        else:
            mark = "✓"
        print(f"  {mark} {f'{ds}__{gr}':<{wpair}}  {status:<7}  {detail}")
        print(f"    {'':<{wpair}}  {'artifacts':<9} {mstatus}: {mdetail}")
    results = [r for r in results if not (r[2] == "MISSING" and r[4] == am.UNPUBLISHED and "--all" in argv)]

    print()
    if bad:
        print(f"[verify_setup] ✗ {bad}/{len(results)} FAILED — do NOT evaluate these until fixed. "
              "Graph mismatch / MISSING: git pull the published archives (coordinator: re-run "
              "scripts/setup_and_archive.py, then scripts/artifact_manifest.py build). "
              "Artifacts MISMATCH: your copy differs from the published set — git checkout "
              "setup_artifacts/ and do not run setup yourself.")
        return 1
    if unpublished:
        print(f"[verify_setup] ! {unpublished}/{len(results)} graph(s) not published yet — "
              "ask the coordinator before running them.")
    print(f"[verify_setup] ✓ all {len(results)} archives match their graphs"
          f"{' and the published set' if not unpublished else ''}"
          f"{f' ({skipped} registered pairs have no archive and are not in the sweep)' if skipped else ''}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
