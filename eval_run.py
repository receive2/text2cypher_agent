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

import json
import os
import shutil
import subprocess
import sys
import time
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


def _summarize_records(recs: list[dict], dataset: str) -> dict:
    """Recompute the headline summary from merged shard records, so the merged
    summary.json matches exactly what the report generators derive from the
    records (they read records.jsonl, not summary.json). ``err`` = #(ea is None),
    consistent with gen_ablation_report."""
    def _mean(key: str) -> float:
        vals = [r[key] for r in recs if r.get(key) is not None]
        if not vals:
            return 0.0
        nums = [1.0 if v is True else (0.0 if v is False else float(v)) for v in vals]
        return sum(nums) / len(nums)

    return {
        "dataset":   dataset,
        "n":         len(recs),
        "n_scored":  {k: sum(1 for r in recs if r.get(k) is not None)
                      for k in ("ea", "em", "psjs")},
        "n_errors":  sum(1 for r in recs if r.get("ea") is None),
        "ea":        _mean("ea"),
        "em":        _mean("em"),
        "psjs":      _mean("psjs"),
    }


def _merge_shard_outputs(dataset: str, shard_recs: list[Path], shard_sums: list[Path],
                         out_records: Path, out_summary: Path, elapsed: float) -> Tuple[bool, str]:
    """Concatenate shard record files into the standard ``out_records`` and write
    a recomputed ``out_summary`` (headline metrics from the merged records +
    run_meta carried from the first shard). Stride shards partition the example
    set exactly, so the concatenation reproduces full single-process coverage."""
    lines: list[str] = []
    for rp in shard_recs:
        if rp.exists():
            lines += [l for l in rp.read_text(encoding="utf-8").splitlines() if l.strip()]
    out_records.parent.mkdir(parents=True, exist_ok=True)
    out_records.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")

    run_meta: dict = {}
    for sp in shard_sums:
        if sp.exists():
            try:
                run_meta = json.loads(sp.read_text(encoding="utf-8")).get("run_meta", {})
                break
            except Exception:  # noqa: BLE001
                pass

    recs = []
    for l in lines:
        try:
            recs.append(json.loads(l))
        except Exception:  # noqa: BLE001
            pass
    summary = _summarize_records(recs, dataset)
    summary["elapsed_sec"] = round(elapsed, 2)
    summary["shards"]      = len(shard_recs)
    summary["run_meta"]    = run_meta
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, "ok"


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
    env = _build_env(conn.uri, conn.user, conn.password, conn.database)
    shards = int(getattr(cfg, "SHARDS", 1) or 1)

    # ── Outer subprocess timeout ────────────────────────────────────────────
    # The per-example wall-clock cap lives inside the worker (see
    # ``EVAL_PER_EXAMPLE_TIMEOUT`` / the watchdog in
    # ``metrics_CypherBench.evaluate_dataset``).  This subprocess timeout is the
    # *outer* safety net — sized to comfortably hold a process's example count
    # at the per-example cap plus startup overhead (FAISS load + Neo4j connect
    # + dataset parse ≈ 30–60 s). Under sharding each worker runs ~limit/shards
    # examples, so the cap is sized per shard. ``EVAL_WORKER_TIMEOUT_SEC``
    # overrides; ``limit is None`` falls back to a 4 h ceiling.
    per_example_sec = int(os.environ.get("EVAL_PER_EXAMPLE_TIMEOUT", "60")) + 5
    explicit_outer  = os.environ.get("EVAL_WORKER_TIMEOUT_SEC")

    def _outer_timeout(n_per_proc: int | None) -> float:
        if explicit_outer:
            return float(explicit_outer)
        if n_per_proc is not None:
            return n_per_proc * per_example_sec + 120
        return 4 * 60 * 60

    if shards <= 1:
        # ── single-process path (original behaviour, byte-identical) ─────────
        cmd: List[str] = [
            sys.executable, "-m", "eval._worker",
            dataset, graph, str(test_path), str(out_records), str(out_summary),
        ]
        if limit is not None:
            cmd += ["--limit", str(limit)]
        if verbose:
            cmd += ["--verbose"]
        outer_timeout = _outer_timeout(limit)
        print(
            f"\n[eval_run] ▶ {dataset}__{graph}  uri={conn.uri}  db={conn.database}  "
            f"outer_timeout={int(outer_timeout)}s"
        )
        try:
            proc = subprocess.run(cmd, env=env, check=False, capture_output=True,
                                  text=True, timeout=outer_timeout)
        except subprocess.TimeoutExpired as exc:
            partial_stdout = exc.stdout if isinstance(exc.stdout, str) else (
                exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            partial_stderr = exc.stderr if isinstance(exc.stderr, str) else (
                exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
            if partial_stdout:
                sys.stdout.write(partial_stdout)
            if partial_stderr:
                sys.stderr.write(partial_stderr)
            print(
                f"[eval_run] ⚠ TIMEOUT after {exc.timeout}s on "
                f"{dataset}__{graph}. Worker killed; moving on to the next EVAL_PAIR.",
                file=sys.stderr,
            )
            return False, (
                f"worker timed out after {exc.timeout}s (dataset={dataset}, graph={graph})"
            )
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            stderr_tail = "\n".join((proc.stderr or "").splitlines()[-20:])
            return False, f"worker exited {proc.returncode}; stderr tail:\n{stderr_tail}"
        return True, "ok"

    # ── sharded path (SHARDS > 1): K parallel workers over example strides ───
    # All shards target the same already-swapped live tree + container; they
    # only differ in which stride of examples they run. Merged afterwards.
    per_proc = None if limit is None else max(1, -(-limit // shards))  # ceil
    outer_timeout = _outer_timeout(per_proc)
    shard_dir = out_dir / f".shards_{dataset}__{graph}"
    if shard_dir.exists():
        shutil.rmtree(shard_dir, ignore_errors=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"\n[eval_run] ▶ {dataset}__{graph}  uri={conn.uri}  db={conn.database}  "
        f"shards={shards}  per-shard outer_timeout={int(outer_timeout)}s"
    )
    shard_recs: list[Path] = []
    shard_sums: list[Path] = []
    procs: list[subprocess.Popen] = []
    for k in range(shards):
        rec_k = shard_dir / f"shard_{k}.records.jsonl"
        sum_k = shard_dir / f"shard_{k}.summary.json"
        shard_recs.append(rec_k)
        shard_sums.append(sum_k)
        cmd = [
            sys.executable, "-m", "eval._worker",
            dataset, graph, str(test_path), str(rec_k), str(sum_k),
            "--shard", str(k), "--shards", str(shards),
        ]
        if limit is not None:
            cmd += ["--limit", str(limit)]
        if verbose:
            cmd += ["--verbose"]
        procs.append(subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True))

    start = time.monotonic()
    deadline = start + outer_timeout
    errors: list[str] = []
    for k, p in enumerate(procs):
        remaining = max(1.0, deadline - time.monotonic())
        try:
            stdout, stderr = p.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            p.kill()
            stdout, stderr = p.communicate()
            errors.append(f"shard {k}: timeout after {int(outer_timeout)}s")
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
        if p.returncode not in (0, None) and not any(f"shard {k}:" in e for e in errors):
            tail = "\n".join((stderr or "").splitlines()[-10:])
            errors.append(f"shard {k}: exit {p.returncode}; {tail}")
    elapsed = time.monotonic() - start

    if errors:
        for p in procs:                       # kill any stragglers
            if p.poll() is None:
                p.kill()
        return False, "sharded run failed: " + " | ".join(errors)

    ok, msg = _merge_shard_outputs(dataset, shard_recs, shard_sums,
                                   out_records, out_summary, elapsed)
    shutil.rmtree(shard_dir, ignore_errors=True)
    return ok, msg


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
