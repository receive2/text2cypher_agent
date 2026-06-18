#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_run.py
===========
Subprocess driver for the per-graph text-to-Cypher evaluation harness.

For each ``(dataset, graph)`` pair listed in :data:`eval_config.EVAL_PAIRS`
this script:

    1. Looks up the :class:`eval_config.GraphConn` for the pair.
    2. Calls :func:`eval.artifact_swap.swap_in` to copy that graph's
       archived setup outputs (``schema_data/``, ``generated/`` tools,
       ``agent/prompts.py``, FAISS index, ``EMBEDDABLE_PROPERTIES``
       snippet) into the live repo locations.
    3. Spawns ``python -m eval._worker <dataset> <graph> ...`` as a
       fresh subprocess with the connection's URI / user / password /
       database injected via ``EVAL_NEO4J_*`` env vars.
    4. Captures the subprocess's exit code and continues to the next
       pair on failure (one bad pair never aborts the rest).

Per-pair output files
---------------------
For each pair it writes::

    <OUT_DIR>/<dataset>__<graph>.records.jsonl   — one record per example
    <OUT_DIR>/<dataset>__<graph>.summary.json    — aggregate summary

Records and summaries from previous runs persist on disk; re-running
``eval_run.py`` for a different slice of ``EVAL_PAIRS`` adds new files
without touching old ones.  The bucketed table is **not** printed here
— run ``python eval_aggregate.py`` for that.

This script has no CLI flags.  Edit :mod:`eval_config` and re-run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import eval_config as cfg
from eval.artifact_swap import swap_in
from paths import REPO_ROOT


# Mapping of dataset name → ``eval_config`` attribute that holds its
# test-set path.  The worker subprocess reads neither; the parent passes
# the resolved path on the command line.
#
# Augmented variants (``*_augmented``) point at separate test-set paths
# so the augmentation runner's output can be evaluated independently of
# the base data.  The base attribute is kept so existing call sites
# (and partial eval_config installs) keep working.
_PATH_ATTR = {
    "cypherbench":            "CYPHERBENCH_PATH",
    "cypherbench_augmented":  "CYPHERBENCH_AUGMENTED_PATH",
    "mindthequery":           "MINDTHEQUERY_PATH",
    "mindthequery_augmented": "MINDTHEQUERY_AUGMENTED_PATH",
    "zograscope":             "ZOGRASCOPE_PATH",
    "zograscope_augmented":   "ZOGRASCOPE_AUGMENTED_PATH",
}


def _resolve_test_path(dataset: str) -> str:
    attr = _PATH_ATTR.get(dataset)
    if attr is None:
        raise ValueError(
            f"Unknown dataset {dataset!r}; expected one of {sorted(_PATH_ATTR)}."
        )
    path = getattr(cfg, attr, None)
    if not path:
        raise ValueError(f"eval_config.{attr} is not set.")
    return path


def _build_env(uri: str, user: str, password: str, database: str) -> dict[str, str]:
    """Copy the parent env and overlay the worker's connection vars."""
    env = dict(os.environ)
    env["EVAL_NEO4J_URI"]      = uri
    env["EVAL_NEO4J_USER"]     = user
    env["EVAL_NEO4J_PASSWORD"] = password
    env["EVAL_NEO4J_DATABASE"] = database
    return env


def _run_pair(
    dataset:     str,
    graph:       str,
    out_dir:     Path,
    *,
    limit:       int | None,
    verbose:     bool,
) -> Tuple[bool, str]:
    """
    Run one (dataset, graph) pair end-to-end.  Returns ``(ok, status_msg)``.

    On any failure (archive missing, subprocess non-zero, exception
    during swap_in) returns ``(False, "<reason>")`` and does not raise.
    The caller logs the reason and moves on.
    """
    out_records = out_dir / f"{dataset}__{graph}.records.jsonl"
    out_summary = out_dir / f"{dataset}__{graph}.summary.json"

    # ── Step 1: swap in archived artifacts ──────────────────────────────────
    try:
        swap_in(dataset, graph)
    except FileNotFoundError as exc:
        return False, f"swap_in: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"swap_in: {type(exc).__name__}: {exc}"

    # ── Step 2: connection lookup ───────────────────────────────────────────
    try:
        conn = cfg.conn_for(dataset, graph)
    except KeyError as exc:
        return False, f"conn_for: {exc}"

    # ── Step 2.5: graph-identity guard ──────────────────────────────────────
    # The swap copies artifacts into a single shared live tree; nothing else
    # checks that those artifacts belong to THIS graph. Ask the database
    # directly whether the live node tools search labels that exist here. A
    # mismatch means a contaminated archive — fail loud instead of silently
    # scoring at the no-val-link floor. Bypass with EVAL_SKIP_GRAPH_GUARD=1.
    if os.environ.get("EVAL_SKIP_GRAPH_GUARD") != "1":
        try:
            from eval.graph_guard import check_tools_match_graph
            ok, detail = check_tools_match_graph(
                REPO_ROOT / "generated" / "generated_node_tools.py",
                conn.uri, conn.user, conn.password, conn.database,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"graph_guard: {type(exc).__name__}: {exc}"
        if not ok:
            return False, f"graph_guard: {detail}"

    # ── Step 3: resolve test path ───────────────────────────────────────────
    try:
        test_path = _resolve_test_path(dataset)
    except ValueError as exc:
        return False, f"test path: {exc}"

    # ── Step 4: subprocess launch ───────────────────────────────────────────
    cmd: List[str] = [
        sys.executable, "-m", "eval._worker",
        dataset, graph, str(test_path),
        str(out_records), str(out_summary),
    ]
    if limit is not None:
        cmd += ["--limit", str(limit)]
    if verbose:
        cmd += ["--verbose"]

    env = _build_env(conn.uri, conn.user, conn.password, conn.database)

    # ── Outer subprocess timeout ────────────────────────────────────────────
    # The per-example wall-clock cap lives inside the worker (see
    # ``EVAL_PER_EXAMPLE_TIMEOUT`` / the watchdog in
    # ``metrics_CypherBench.evaluate_dataset``).  This subprocess timeout
    # is the *outer* safety net — sized to comfortably hold ``limit``
    # examples at the per-example cap plus startup overhead (FAISS load
    # + Neo4j connect + dataset parse ≈ 30–60 s).
    #
    # When ``limit is None`` we don't know how many examples a graph will
    # produce (e.g. cypherbench_augmented/movie has 372). The old default
    # of ``limit or 100`` undersized the cap (6620 s) for those large
    # pairs. Use the env var ``EVAL_WORKER_TIMEOUT_SEC`` for an explicit
    # override, otherwise budget 4 h — well beyond any healthy
    # 200–500-example pair at ~10 s/example and bounded enough to fire
    # before a real wedge consumes the full CI window.
    per_example_sec = int(os.environ.get("EVAL_PER_EXAMPLE_TIMEOUT", "60")) + 5
    explicit_outer  = os.environ.get("EVAL_WORKER_TIMEOUT_SEC")
    if explicit_outer:
        outer_timeout = float(explicit_outer)
    elif limit is not None:
        outer_timeout = limit * per_example_sec + 120
    else:
        # 4-hour ceiling for an entire-graph pass.
        outer_timeout = 4 * 60 * 60

    print(
        f"\n[eval_run] ▶ {dataset}__{graph}  uri={conn.uri}  db={conn.database}  "
        f"outer_timeout={int(outer_timeout)}s"
    )
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=outer_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # Surface whatever the worker managed to emit before being killed.
        partial_stdout = exc.stdout if isinstance(exc.stdout, str) else (
            exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        )
        partial_stderr = exc.stderr if isinstance(exc.stderr, str) else (
            exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        )
        if partial_stdout:
            sys.stdout.write(partial_stdout)
        if partial_stderr:
            sys.stderr.write(partial_stderr)
        limit_val = env.get("EVAL_LIMIT") or (
            cmd[cmd.index("--limit") + 1] if "--limit" in cmd else "<all>"
        )
        print(
            f"[eval_run] ⚠ TIMEOUT after {exc.timeout}s on "
            f"{dataset}__{graph} (uri={conn.uri} db={conn.database} "
            f"test_path={test_path} limit={limit_val}). "
            f"Worker subprocess killed; moving on to the next EVAL_PAIR.",
            file=sys.stderr,
        )
        # Do NOT raise — let the outer loop continue.
        return False, (
            f"worker timed out after {exc.timeout}s "
            f"(dataset={dataset}, graph={graph}, limit={limit_val})"
        )

    # Always echo stdout (the worker may have streamed verbose lines there).
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)

    if proc.returncode != 0:
        # Tail the last ~20 stderr lines for the status print.
        stderr_tail = "\n".join((proc.stderr or "").splitlines()[-20:])
        return False, (
            f"worker exited {proc.returncode}; stderr tail:\n{stderr_tail}"
        )
    return True, "ok"


def main() -> int:
    out_dir = Path(getattr(cfg, "OUT_DIR", "logs/eval"))
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs: List[Tuple[str, str]] = list(getattr(cfg, "EVAL_PAIRS", []) or [])
    if not pairs:
        print(
            "[eval_run] eval_config.EVAL_PAIRS is empty — nothing to do. "
            "Edit eval_config.py and re-run.",
            file=sys.stderr,
        )
        return 1

    statuses: list[tuple[str, str, bool, str]] = []
    for dataset, graph in pairs:
        ok, msg = _run_pair(
            dataset, graph, out_dir,
            limit   = getattr(cfg, "LIMIT", None),
            verbose = bool(getattr(cfg, "VERBOSE", False)),
        )
        statuses.append((dataset, graph, ok, msg))
        if not ok:
            print(f"[eval_run] ✗ {dataset}__{graph}: {msg}", file=sys.stderr)

    # ── Final per-pair status line ─────────────────────────────────────────
    print("\n══ eval_run summary ══")
    for dataset, graph, ok, msg in statuses:
        mark = "✓" if ok else "✗"
        suffix = "" if ok else f"  ({msg.splitlines()[0]})"
        print(f"  {mark} {dataset}__{graph}{suffix}")
    print(
        "\nRun `python eval_aggregate.py` to print the bucketed metric table "
        f"over everything currently in {out_dir}."
    )

    # Exit non-zero iff every pair failed; partial success returns 0 so
    # the user can still aggregate what landed on disk.
    if statuses and all(not ok for _, _, ok, _ in statuses):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
