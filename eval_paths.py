#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_paths.py
=============
The single source of truth for where a run's artifacts live on disk.

Every run of one ``(dataset, graph, method)`` triple writes to a canonical
per-run directory::

    logs/runs/<dataset>__<graph>__<method>/records.jsonl
    logs/runs/<dataset>__<graph>__<method>/summary.json

``eval_run`` writes there; ``eval_aggregate`` and the report generators
(``gen_graph_report`` / ``gen_pooled_report``) read from there. This replaces
the old per-prefix convention (``logs/cb_<graph>_<method>/`` etc.) and the
hand-maintained prefix→graph map that the orchestrator and report scripts each
carried a copy of.

The separator is a *double* underscore ``__``; dataset / graph / method names
themselves use single underscores (``cypherbench_augmented``,
``fictional_character``, ``cyanchor_fl``), so ``name.split("__")`` always yields
exactly the three components back.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

# Canonical root for all per-run artifact directories.
RUNS_ROOT = "logs/runs"

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


def run_dir(dataset: str, graph: str, method_seg: str,
            root: str | Path = RUNS_ROOT) -> Path:
    """``<root>/<dataset>__<graph>__<method_seg>`` — the canonical per-run dir.

    ``method_seg`` is the value from :func:`method_tag` (or a literal such as
    ``"graphrag"`` / ``"cyanchor_fl"`` from a report generator)."""
    return Path(root) / f"{dataset}__{graph}__{method_seg}"


def parse_run_dir(path: str | Path) -> Optional[Tuple[str, str, str]]:
    """Inverse of :func:`run_dir`: return ``(dataset, graph, method_seg)`` parsed
    from a run-dir name, or ``None`` if it doesn't carry the three ``__``-joined
    components."""
    name = Path(path).name
    parts = name.split("__")
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]
