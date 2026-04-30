# -*- coding: utf-8 -*-
"""
scripts/_vector_config_io.py
============================
Shared helpers for reading and rewriting the ``EMBEDDABLE_PROPERTIES``
block in :mod:`vector_config`.

The block is the only part of ``vector_config.py`` that the setup
pipeline rewrites in place; everything else in that file is hand-edited
and project-wide.  Both ``setup_project.py`` (after auto-discovery) and
``eval/artifact_swap.py`` (per-graph archive / swap-in) need to read or
mutate just this block.  Hosting the regex-based logic here keeps the
two callers from having to import each other's orchestration modules.

Public API
----------
* :func:`rewrite_embeddable_block(path, entries)` — replace the block
  with a freshly rendered list of node/relationship spec dicts.
* :func:`extract_embeddable_block(path)` — return the current block as
  a string snippet (including the ``EMBEDDABLE_PROPERTIES = [`` header
  and trailing ``]``); raises if not found.
* :func:`replace_embeddable_block(path, snippet)` — replace the block
  with the *literal* snippet string.  Used by the artifact-swap path,
  where the snippet was extracted from the archive verbatim.

All three functions write a ``<path>.bak`` before mutating the file.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Mapping

# ── Block-finder regexes ─────────────────────────────────────────────────────
# Strict: full multi-line ``EMBEDDABLE_PROPERTIES = [ ... ]`` block, the ``]``
# alone on its own line.  This is the canonical layout produced by
# :func:`_render_block`.
_STRICT_RE = re.compile(
    r"^EMBEDDABLE_PROPERTIES\s*=\s*\[.*?^\]\s*$",
    flags=re.MULTILINE | re.DOTALL,
)

# Permissive: tolerate single-line lists, trailing comments, etc.  Used as a
# fallback when the strict regex misses (e.g. someone hand-edited the file
# and left the closing bracket on the same line as the last entry).
_PERMISSIVE_RE = re.compile(
    r"^EMBEDDABLE_PROPERTIES\s*=\s*\[.*?\][ \t]*(?:#[^\n]*)?$",
    flags=re.MULTILINE | re.DOTALL,
)


def _find_block(text: str, *, path_for_error: str) -> re.Match[str]:
    """Return the regex match spanning the EMBEDDABLE_PROPERTIES block."""
    m = _STRICT_RE.search(text) or _PERMISSIVE_RE.search(text)
    if not m:
        raise RuntimeError(
            f"Could not find EMBEDDABLE_PROPERTIES block in {path_for_error!r}. "
            "Neither the strict nor permissive regex matched. The block must "
            "start with 'EMBEDDABLE_PROPERTIES = [' at column 0."
        )
    return m


def _render_block(entries: List[Mapping[str, str]]) -> str:
    """Render *entries* as the canonical multi-line literal."""
    lines: List[str] = ["EMBEDDABLE_PROPERTIES = ["]
    for e in entries:
        lines.append("    {")
        lines.append(f'        "entity_type":        "{e["entity_type"]}",')
        lines.append(f'        "label":              "{e["label"]}",')
        lines.append(f'        "property":           "{e["property"]}",')
        lines.append(f'        "embedding_property": "{e["embedding_property"]}",')
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


def _backup(path: str) -> None:
    backup = path + ".bak"
    try:
        shutil.copy(path, backup)
    except OSError as e:
        raise RuntimeError(
            f"Could not write backup {backup!r}: {e}. Aborting rewrite."
        ) from e


def rewrite_embeddable_block(path: str, entries: List[Mapping[str, str]]) -> None:
    """
    Rewrite the ``EMBEDDABLE_PROPERTIES = [...]`` block in *path* in place
    with the canonical rendering of *entries*.

    A ``<path>.bak`` is written before mutation.  Behaviour matches the
    original ``setup_project._rewrite_embeddable_block`` exactly — this is
    the lifted shared implementation.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    m = _find_block(text, path_for_error=path)
    _backup(path)
    new_block = _render_block(entries)
    p.write_text(text[: m.start()] + new_block + text[m.end():], encoding="utf-8")


def extract_embeddable_block(path: str) -> str:
    """
    Return the current ``EMBEDDABLE_PROPERTIES`` block as a string snippet.

    The returned snippet includes the leading ``EMBEDDABLE_PROPERTIES = [``
    and the trailing ``]``.  No surrounding context is included.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = _find_block(text, path_for_error=path)
    return text[m.start():m.end()]


def replace_embeddable_block(path: str, snippet: str) -> None:
    """
    Replace the ``EMBEDDABLE_PROPERTIES`` block in *path* with the literal
    *snippet* string (which itself must start with
    ``EMBEDDABLE_PROPERTIES = [`` and end with ``]``).

    Used by the per-graph artifact-swap path: the snippet was captured
    verbatim from the archive at archive time and is re-injected at swap-in
    time without re-rendering.  A ``<path>.bak`` is written before mutation.
    """
    snippet = snippet.rstrip("\n")
    if not snippet.lstrip().startswith("EMBEDDABLE_PROPERTIES"):
        raise ValueError(
            "replace_embeddable_block: snippet must start with "
            "'EMBEDDABLE_PROPERTIES = [' (got first 64 chars: "
            f"{snippet[:64]!r})"
        )
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    m = _find_block(text, path_for_error=path)
    _backup(path)
    p.write_text(text[: m.start()] + snippet + text[m.end():], encoding="utf-8")
