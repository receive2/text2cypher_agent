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

The method segment carries the **generator model** when one is in play
(``cyanchor_fl@claude-sonnet-5``), because the reader resolves a triple to a
single directory: without the model in the name, a second model's run is a
newer stamp for the same triple and every report silently switches to it.
Ablation knobs stay out of the name — they are recorded *inside* ``summary.json``
under ``run_meta``, and re-running with a different knob is a deliberate
supersede.

The model segment is separated by ``@`` (never ``__``), so the component split
below is unchanged. Untagged dirs from before model tagging are still resolved,
but only for the model that actually produced them (verified against
``run_meta``) — see :func:`latest_run_dir`.

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


def model_seg(model: Optional[str]) -> str:
    """Filesystem-safe model segment. ``__`` would break the component split and
    ``/`` would create a directory level, so both collapse to ``-``."""
    if not model:
        return ""
    return re.sub(r"[^A-Za-z0-9._@-]", "-", str(model).replace("__", "_")).strip("-")


def split_method_seg(method_seg: str) -> Tuple[str, str]:
    """``"cyanchor_fl@claude-sonnet-5"`` -> ``("cyanchor_fl", "claude-sonnet-5")``.
    An untagged segment yields ``(seg, "")``."""
    head, sep, tail = method_seg.partition("@")
    return (head, tail) if sep else (method_seg, "")


def method_tag(method: str,
               fuzzy: bool = True,
               vector: bool = False,
               lev: bool = True,
               model: Optional[str] = None) -> str:
    """Canonical method segment of a run dir.

    Baselines (``no_val_link`` / ``fcav`` / ``react`` / ``graphrag``) map to the
    method name verbatim. ``cyanchor`` additionally encodes its active retrieval
    arms in the historical fuzzy→vector→lev order, so fuzzy+lev → ``cyanchor_fl``
    and fuzzy+vector+lev → ``cyanchor_fvl`` (matching the existing report dirs).

    Passing ``model`` appends ``@<model>`` so runs of different generator LLMs
    occupy different directories (and different report cells)."""
    if method != "cyanchor":
        base = method
    else:
        arms = ("f" if fuzzy else "") + ("v" if vector else "") + ("l" if lev else "")
        base = "cyanchor_" + (arms or "none")
    seg = model_seg(model)
    return f"{base}@{seg}" if seg else base


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


def method_tag_join(base: str, model: Optional[str]) -> str:
    """Attach a model segment to an already-built method segment."""
    seg = model_seg(model)
    return f"{base}@{seg}" if seg else base


_AUTO = object()   # sentinel: resolve the model from config


def default_model() -> str:
    """The generator preset this process is configured for, so a reader never
    mixes models: eval_config.GENERATOR_LLM (the control panel — what eval_run
    injects into workers) when set, else config.py's own resolution. ``""`` if
    neither is importable."""
    try:
        import eval_config as _e
        name = getattr(_e, "GENERATOR_LLM", None)
        if name:
            return str(name)
    except Exception:  # noqa: BLE001
        pass
    try:
        import config as _c
        return _c.active_generator_model()
    except Exception:  # noqa: BLE001
        return ""


def run_meta_model(d: Path) -> Optional[str]:
    """The generator model recorded in a run dir's ``summary.json`` (``run_meta``),
    or ``None`` when the file is absent/unreadable or records no model."""
    try:
        import json
        rm = json.loads((d / "summary.json").read_text(encoding="utf-8")).get("run_meta") or {}
    except Exception:  # noqa: BLE001
        return None
    for k in ("cypher_llm", "ner_llm", "qa_llm"):
        if rm.get(k):
            return str(rm[k])
    return None


def latest_run_dir(dataset: str, graph: str, method_seg: str,
                   root: str | Path = RUNS_ROOT,
                   model: Optional[str] = _AUTO) -> Optional[Path]:
    """The newest run dir for a triple, or ``None`` if the triple never ran.

    Stamped dirs win over the legacy unstamped dir (a re-run supersedes the
    pre-timestamp layout); among stamped dirs the lexically-largest stamp is
    the newest (the format is sort-safe).

    **Model scoping.** ``method_seg`` may already carry ``@<model>``; otherwise
    ``model`` is appended, and it defaults to the model *this process* is
    configured for — so a reader never picks up another model's run and a
    second generator LLM cannot take over a report cell.

    Dirs written before model tagging carry no ``@`` segment. They are accepted
    for a requested model only when their ``run_meta`` names that model, which
    keeps every pre-existing run resolvable for the model that produced it and
    for no other.

    ``model=None`` is the explicit "any model" mode for audit tooling: tagged
    and untagged dirs of the method all compete, newest stamp wins, and legacy
    provenance is not checked.
    """
    if model is _AUTO:
        model = default_model()
    root = Path(root)
    base, tagged = split_method_seg(method_seg)
    if model and not tagged:
        tagged = model_seg(model)
    want = tagged                                    # "" == any model

    def _stamped(pattern: str) -> list[tuple[str, Path]]:
        out = []
        for p in root.glob(pattern):
            parts = p.name.split("__")
            if len(parts) == 4 and _STAMP_RE.match(parts[3]) and p.is_dir():
                out.append((parts[3], p))
        return out

    if want:
        exact = _stamped(f"{dataset}__{graph}__{base}@{want}__*")
        if exact:
            return max(exact)[1]
    else:
        any_model = _stamped(f"{dataset}__{graph}__{base}@*__*")
        any_model += _stamped(f"{dataset}__{graph}__{base}__*")
        if any_model:
            return max(any_model)[1]

    # Legacy: untagged dirs predate model tagging.
    legacy = _stamped(f"{dataset}__{graph}__{base}__*")
    plain = root / f"{dataset}__{graph}__{base}"
    if plain.is_dir():
        legacy.append(("", plain))
    for _, d in sorted(legacy, reverse=True):
        if not want:
            return d
        got = run_meta_model(d)
        if got is not None and model_seg(got) == want:
            return d
    return None


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
