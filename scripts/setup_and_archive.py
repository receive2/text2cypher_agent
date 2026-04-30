#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/setup_and_archive.py
============================
One-shot helper to set up a single ``(dataset, graph)`` pair and archive
its setup outputs for later reuse by the evaluation harness.

Workflow
--------
1. Look up the :class:`eval_config.GraphConn` for the pair.
2. (Sanity) refuse to overwrite an existing archive unless ``--force``.
3. Subprocess-invoke ``setup_project.py`` with the pair's connection
   injected via ``NEO4J_*`` env vars and the pair's ``database`` passed
   on ``--database``.  All optional flags
   (``--skip-faiss`` / ``--skip-embeddings`` / ``--rediscover`` /
   ``--reset-embeddings`` / ``--yes``) are forwarded as-is so the user
   sees the existing setup_project.py UI.
4. On success, archive the live setup outputs under
   ``setup_artifacts/<dataset>__<graph>/`` via
   :func:`eval.artifact_swap.archive_current`.
5. Round-trip-check the manifest by archiving + swapping into a temp
   directory.  If that fails, the swap manifest is incomplete or buggy
   and we bail out loudly so the user notices BEFORE setting up the
   rest of their graphs.

Usage
-----
::

    python scripts/setup_and_archive.py <dataset> <graph> \\
        [--force] [--skip-faiss] [--skip-embeddings] \\
        [--rediscover] [--reset-embeddings] [--yes]

Re-running for an already-archived pair without ``--force`` is an
error — the user must opt in to overwriting.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List

# Repo root is ``scripts/..``.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Make sibling top-level modules (eval_config, eval, paths, ...) importable
# when the user invokes this script from anywhere.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import eval_config as cfg  # noqa: E402
from eval.artifact_swap import (  # noqa: E402
    archive_current,
    archive_dir_for,
    round_trip_check,
)


def _build_env(uri: str, user: str, password: str, database: str) -> dict[str, str]:
    """Copy the parent env and overlay the standard ``NEO4J_*`` names."""
    env = dict(os.environ)
    env["NEO4J_URI"]      = uri
    env["NEO4J_USERNAME"] = user
    env["NEO4J_PASSWORD"] = password
    env["NEO4J_DATABASE"] = database
    return env


def _build_setup_argv(args: argparse.Namespace) -> List[str]:
    """Translate this script's parsed args into setup_project.py CLI flags."""
    cmd: List[str] = [
        sys.executable, str(_REPO_ROOT / "setup_project.py"),
        "--database", args.database,
    ]
    if args.skip_faiss:
        cmd.append("--skip-faiss")
    if args.skip_embeddings:
        cmd.append("--skip-embeddings")
    if args.rediscover:
        cmd.append("--rediscover")
    if args.reset_embeddings:
        cmd.append("--reset-embeddings")
    if args.yes:
        cmd.append("--yes")
    return cmd


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Set up one (dataset, graph) pair and archive its setup outputs "
            "for later reuse by eval_run.py."
        ),
    )
    p.add_argument("dataset", help="Dataset name (e.g. 'cypherbench').")
    p.add_argument("graph",   help="Graph name (e.g. 'movie').")
    p.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing archive at "
             "setup_artifacts/<dataset>__<graph>/.",
    )

    # Forwarded flags — match setup_project.py exactly.
    p.add_argument("--skip-faiss",       action="store_true")
    p.add_argument("--skip-embeddings",  action="store_true")
    p.add_argument("--rediscover",       action="store_true")
    p.add_argument("--reset-embeddings", action="store_true")
    p.add_argument("--yes",              action="store_true",
                   help="Skip all interactive confirmation prompts.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    # ── Step 1: connection lookup ──────────────────────────────────────────
    try:
        conn = cfg.conn_for(args.dataset, args.graph)
    except KeyError as exc:
        print(f"[setup_and_archive] {exc}", file=sys.stderr)
        return 1

    # Stash the database name on args so _build_setup_argv can read it.
    args.database = conn.database

    # ── Step 2: archive-existence guard ────────────────────────────────────
    archive = archive_dir_for(args.dataset, args.graph)
    if archive.exists() and not args.force:
        print(
            f"[setup_and_archive] Archive already exists: {archive}\n"
            "Pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    # ── Step 3: subprocess-invoke setup_project.py ─────────────────────────
    cmd = _build_setup_argv(args)
    env = _build_env(conn.uri, conn.user, conn.password, conn.database)

    print(
        f"[setup_and_archive] ▶ {args.dataset}__{args.graph}\n"
        f"    uri      : {conn.uri}\n"
        f"    database : {conn.database}\n"
        f"    cmd      : {' '.join(cmd)}\n",
        flush=True,
    )

    # Stream stdout/stderr to the parent so the existing setup_project.py
    # UI is visible; do NOT capture.
    proc = subprocess.run(cmd, env=env, check=False, cwd=str(_REPO_ROOT))
    if proc.returncode != 0:
        print(
            f"[setup_and_archive] setup_project.py exited "
            f"{proc.returncode}; not archiving.",
            file=sys.stderr,
        )
        return proc.returncode

    # ── Step 4: archive the live setup outputs ────────────────────────────
    print(f"[setup_and_archive] archiving to {archive} ...", flush=True)
    archive_current(args.dataset, args.graph, force=True)

    # ── Step 5: round-trip-check the manifest ─────────────────────────────
    print("[setup_and_archive] running round-trip check ...", flush=True)
    try:
        round_trip_check(args.dataset, args.graph)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[setup_and_archive] round-trip check FAILED: {exc}\n"
            "The swap manifest in eval/artifact_swap.py is incomplete or "
            "buggy; review SWAP_FILES / SWAP_DIRS before setting up more "
            "graphs.",
            file=sys.stderr,
        )
        return 2

    print(
        f"[setup_and_archive] ✓ {args.dataset}__{args.graph} archived.\n"
        f"    {archive}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
