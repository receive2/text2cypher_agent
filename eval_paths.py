#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_paths.py
=============
The single source of truth for where a run's artifacts live on disk.

Every invocation of ``eval_run`` for one ``(dataset, graph, method)`` triple
writes to a fresh, timestamped per-run directory::

    logs/runs/<dataset>__<graph>__<method>__<YYYYMMDD-HHMMSS>/records.jsonl
    logs/runs/<dataset>__<graph>__<method>__<YYYYMMDD-HHMMSS>/summary.json

The directory name deliberately carries **no model or config information** —
only the triple plus a timestamp. What actually ran (LLM per stage, embedding
backend, every ablation knob) is recorded *inside* ``summary.json`` under the
``run_config`` key, so each run dir is self-describing and re-running with a
different model or knob setting can never silently overwrite earlier records.

Readers (``eval_aggregate``, the report generators, the orchestrator) resolve
a triple through :func:`latest_run_dir`, which returns the newest stamped run
and falls back to the legacy unstamped layout
(``logs/runs/<dataset>__<graph>__<method>/``) so pre-existing runs keep
working unchanged.

The separator is a *double* underscore ``__``; dataset / graph / method names
themselves use single underscores (``cypherbench_augmented``,
``fictional_character``, ``cyanchor_fl``) and the stamp contains none, so
``name.split("__")`` always yields the components back (3 legacy / 4 stamped).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# Canonical root for all per-run artifact directories.
RUNS_ROOT = "logs/runs"

# Timestamp segment appended to run dirs. No underscores (see module doc).
STAMP_FMT = "%Y%m%d-%H%M%S"
_STAMP_RE = re.compile(r"^\d{8}-\d{6}$")

# Data dataset key → the report/ subdirectory label the per-graph reports live
# under. Used by the report generators so callers pass the data key (which
# eval_run already has) rather than re-deriving the label.
REPORT_DIR_LABEL = {
    "cypherbench_augmented":  "CypherBench",
    "mindthequery_augmented": "MindTheQuery",
    "zograscope_augmented":   "ZOGRASCOPE",
}


def method_tag(method: str,
               fuzzy: bool = True,
               vector: bool = False,
               lev: bool = True) -> str:
    """Canonical method segment of a run dir.

    Baselines (``no_val_link`` / ``fcav`` / ``react`` / ``graphrag``) map to the
    method name verbatim. ``cyanchor`` additionally encodes its active retrieval
    arms in the historical fuzzy→vector→lev order, so fuzzy+lev → ``cyanchor_fl``
    and fuzzy+vector+lev → ``cyanchor_fvl`` (matching the existing report dirs)."""
    if method != "cyanchor":
        return method
    arms = ("f" if fuzzy else "") + ("v" if vector else "") + ("l" if lev else "")
    return "cyanchor_" + (arms or "none")


def new_stamp() -> str:
    """A fresh run-dir timestamp segment (second resolution)."""
    return datetime.now().strftime(STAMP_FMT)


def run_dir(dataset: str, graph: str, method_seg: str,
            root: str | Path = RUNS_ROOT,
            stamp: Optional[str] = None) -> Path:
    """``<root>/<dataset>__<graph>__<method_seg>[__<stamp>]`` — pure path join.

    Writers should use :func:`new_run_dir`; readers should use
    :func:`latest_run_dir`. Without ``stamp`` this returns the legacy
    unstamped location (kept for logging labels and backward compatibility)."""
    base = f"{dataset}__{graph}__{method_seg}"
    if stamp:
        base += f"__{stamp}"
    return Path(root) / base


def new_run_dir(dataset: str, graph: str, method_seg: str,
                root: str | Path = RUNS_ROOT) -> Path:
    """A fresh timestamped run dir for a writer (not created on disk)."""
    return run_dir(dataset, graph, method_seg, root=root, stamp=new_stamp())


def latest_run_dir(dataset: str, graph: str, method_seg: str,
                   root: str | Path = RUNS_ROOT) -> Optional[Path]:
    """The newest run dir for a triple, or ``None`` if the triple never ran.

    Stamped dirs win over the legacy unstamped dir (a re-run supersedes the
    pre-timestamp layout); among stamped dirs the lexically-largest stamp is
    the newest (the format is sort-safe)."""
    root = Path(root)
    stamped: list[tuple[str, Path]] = []
    for p in root.glob(f"{dataset}__{graph}__{method_seg}__*"):
        parts = p.name.split("__")
        if len(parts) == 4 and _STAMP_RE.match(parts[3]) and p.is_dir():
            stamped.append((parts[3], p))
    if stamped:
        return max(stamped)[1]
    legacy = root / f"{dataset}__{graph}__{method_seg}"
    return legacy if legacy.is_dir() else None


def parse_run_dir_stamped(path: str | Path) -> Optional[Tuple[str, str, str, str]]:
    """Parse a run-dir name into ``(dataset, graph, method_seg, stamp)``.

    Legacy unstamped dirs parse with ``stamp == ""`` (which sorts before any
    real stamp, so "stamped supersedes legacy" falls out of a plain max()).
    Returns ``None`` for names that are neither layout."""
    parts = Path(path).name.split("__")
    if len(parts) == 3 and all(parts):
        return parts[0], parts[1], parts[2], ""
    if len(parts) == 4 and all(parts) and _STAMP_RE.match(parts[3]):
        return parts[0], parts[1], parts[2], parts[3]
    return None


def parse_run_dir(path: str | Path) -> Optional[Tuple[str, str, str]]:
    """Inverse of :func:`run_dir` modulo the stamp: ``(dataset, graph,
    method_seg)`` from either layout, or ``None``."""
    parsed = parse_run_dir_stamped(path)
    return None if parsed is None else parsed[:3]
