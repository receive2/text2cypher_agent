#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/artifact_identity.py
=========================
Identity stamps for per-graph generated artifacts (FCAV / FAISS index dirs).

Why this exists (2026-07 FCAV pollution incident)
-------------------------------------------------
``generated/fcav`` is an *optional* swap dir: ``archive_current`` used to fold
whatever happened to be live into the archive, and ``swap_in`` left the live
dir untouched when the archive had none.  The combination let one graph's
FCAV index (cypherbench geography) leak into four Mind-the-Query archives,
where FCAV then silently degraded to the No-Val-Link baseline.  The root
problem: an index that does not carry its own ``(dataset, graph)`` identity
cannot be defended at any boundary.

The fix: every per-graph artifact dir carries an ``identity`` block inside its
existing JSON carrier file (``manifest.json`` for FCAV, ``fingerprint.json``
for the tool-FAISS dirs)::

    "identity": {
        "pair":       "mindthequery_augmented__healthcare",
        "dataset":    "mindthequery_augmented",
        "graph":      "healthcare",
        "bolt_uri":   "bolt://34.9.85.21:15074",
        "database":   "neo4j",
        "stamped_at": "2026-07-18T12:00:00+00:00"
    }

and the four boundaries verify it:

* **build**   — ``fcav.build_fcav_index`` stamps from the same connection it
  built against (identity cannot drift from content);
* **archive** — ``artifact_swap.archive_current`` refuses to fold a foreign or
  unstamped optional dir into an archive (kills the propagation vector);
* **swap-in** — ``artifact_swap`` validates archived dirs against the archive's
  own pair name and removes live optional dirs the archive does not carry
  (hermetic: absent in archive ⇒ absent live);
* **load**    — ``fcav._load`` / ``tools.tool_search._verify_fingerprint``
  compare the stamp against the live ``.current_setup`` sentinel and refuse to
  serve a mismatched index.

Legacy (pre-stamp) artifacts are migrated once via
``scripts/audit_artifact_identity.py --adopt``, which stamps archives whose
content is not byte-duplicated across graphs; duplicated (i.e. polluted)
archives are never adopted and must be rebuilt.

This module is dependency-free (stdlib only) and path-pure: every function
takes explicit paths so callers keep their own ``REPO_ROOT`` monkeypatching
working in offline tests.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("t2c.artifact_identity")

#: Live-tree sentinel written by ``artifact_swap.swap_in`` after a successful
#: swap; its content is ``<dataset>__<graph>``.  Single source of truth for
#: "which graph is the live tree set up for".
SENTINEL_NAME = ".current_setup"

#: Key under which the identity block lives inside the carrier JSON file.
IDENTITY_KEY = "identity"

#: Carrier files probed (in order) inside a stampable artifact dir.
CARRIER_FILES = ("manifest.json", "fingerprint.json")


class ArtifactIdentityError(RuntimeError):
    """A per-graph artifact dir failed identity verification."""


# ──────────────────────────────────────────────────────────────────────────────
# Basics
# ──────────────────────────────────────────────────────────────────────────────

def pair_id(dataset: str, graph: str) -> str:
    """Canonical ``<dataset>__<graph>`` pair id (same as the archive dir name)."""
    return f"{dataset}__{graph}"


def split_pair(pair: str) -> tuple[str, str]:
    """Inverse of :func:`pair_id`. Raises ``ValueError`` on malformed input."""
    dataset, sep, graph = pair.partition("__")
    if not sep or not dataset or not graph:
        raise ValueError(f"Not a <dataset>__<graph> pair id: {pair!r}")
    return dataset, graph


def current_pair(repo_root: Union[str, Path]) -> Optional[str]:
    """Read the live ``.current_setup`` sentinel; ``None`` if absent/empty."""
    p = Path(repo_root) / SENTINEL_NAME
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def make_identity(
    dataset: str,
    graph: str,
    *,
    uri: Optional[str] = None,
    database: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a fresh identity block for ``(dataset, graph)``."""
    return {
        "pair":       pair_id(dataset, graph),
        "dataset":    dataset,
        "graph":      graph,
        "bolt_uri":   uri,
        "database":   database,
        "stamped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Read / stamp
# ──────────────────────────────────────────────────────────────────────────────

def carrier_path(artifact_dir: Union[str, Path]) -> Optional[Path]:
    """First existing carrier file inside *artifact_dir*, or ``None``."""
    d = Path(artifact_dir)
    for name in CARRIER_FILES:
        p = d / name
        if p.is_file():
            return p
    return None


def read_identity(artifact_dir: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """
    Return the identity block of *artifact_dir*, or ``None`` when the dir is
    legacy (no carrier file, or carrier without an ``identity`` key).

    Raises
    ------
    ArtifactIdentityError
        If a carrier file exists but is unreadable/corrupt — a corrupt
        manifest on a per-graph index is itself suspicious, never ignorable.
    """
    p = carrier_path(artifact_dir)
    if p is None:
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactIdentityError(
            f"Carrier file {p} is unreadable ({exc!r}) — the artifact dir is "
            "corrupt; rebuild it."
        ) from exc
    ident = obj.get(IDENTITY_KEY)
    return ident if isinstance(ident, dict) else None


def stamp_dir(
    artifact_dir: Union[str, Path],
    dataset: str,
    graph: str,
    *,
    uri: Optional[str] = None,
    database: Optional[str] = None,
) -> Path:
    """
    Write/overwrite the identity block into *artifact_dir*'s carrier file
    (atomic tmp+rename). Returns the carrier path.

    Raises
    ------
    ArtifactIdentityError
        If the dir has no carrier file to stamp.
    """
    p = carrier_path(artifact_dir)
    if p is None:
        raise ArtifactIdentityError(
            f"Cannot stamp {artifact_dir}: no carrier file "
            f"({' / '.join(CARRIER_FILES)}) found."
        )
    obj = json.loads(p.read_text(encoding="utf-8"))
    obj[IDENTITY_KEY] = make_identity(dataset, graph, uri=uri, database=database)
    tmp = p.with_name(p.name + ".stamp.tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    logger.info("Stamped %s as %s", artifact_dir, pair_id(dataset, graph))
    return p


# ──────────────────────────────────────────────────────────────────────────────
# Pair equivalence
# ──────────────────────────────────────────────────────────────────────────────
# Augmenting a dataset only rewrites the NL questions — ``<ds>_augmented``
# reuses the exact same graph (eval_config registers it with the same
# connection), so identical index content across the clean/augmented sibling
# archives is legitimate and their stamps must inter-verify.  The ground truth
# for "same graph" is the connection registry; the ``_augmented`` suffix strip
# is the dependency-free fallback (it covers everything except registry-level
# aliases like mindthequery's bloom ↔ bloom50).

def normalize_pair(pair: str) -> str:
    """Collapse the ``_augmented`` dataset suffix: ``ds_augmented__g`` → ``ds__g``."""
    try:
        dataset, graph = split_pair(pair)
    except ValueError:
        return pair
    if dataset.endswith("_augmented"):
        dataset = dataset[: -len("_augmented")]
    return pair_id(dataset, graph)


_URI_BY_PAIR: Optional[Dict[str, str]] = None


def _uri_map() -> Dict[str, str]:
    """pair id → bolt uri from eval_config.GRAPH_CONNS (empty if unavailable)."""
    global _URI_BY_PAIR
    if _URI_BY_PAIR is None:
        try:
            from eval_config import GRAPH_CONNS  # noqa: WPS433 — lazy, optional
            _URI_BY_PAIR = {
                pair_id(ds, g): conn.uri for (ds, g), conn in GRAPH_CONNS.items()
            }
        except Exception:  # pragma: no cover — clean checkout / offline tests
            _URI_BY_PAIR = {}
    return _URI_BY_PAIR


def pairs_equivalent(a: Optional[str], b: Optional[str]) -> bool:
    """
    True when *a* and *b* name the same underlying graph: equal, equal after
    ``_augmented`` normalization, or registered on the same connection in
    ``eval_config.GRAPH_CONNS``.
    """
    if not a or not b:
        return False
    if a == b or normalize_pair(a) == normalize_pair(b):
        return True
    uris = _uri_map()
    ua, ub = uris.get(a) or uris.get(normalize_pair(a)), uris.get(b) or uris.get(normalize_pair(b))
    return ua is not None and ua == ub


# ──────────────────────────────────────────────────────────────────────────────
# Verify
# ──────────────────────────────────────────────────────────────────────────────

def verify_dir(
    artifact_dir: Union[str, Path],
    expected_pair: str,
    *,
    context: str,
    missing: str = "raise",
) -> bool:
    """
    Verify that *artifact_dir* is stamped for *expected_pair*.

    Parameters
    ----------
    context
        Short human label for error messages, e.g. ``"FCAV load"`` or
        ``"archive_current(generated/fcav)"``.
    missing
        Policy when the dir carries no stamp (legacy artifact):
        ``"raise"`` (fail closed), ``"warn"`` (log + continue), or
        ``"ignore"``.

    Returns
    -------
    bool
        ``True`` only when the stamp exists AND matches (positive
        verification). ``False`` for an unstamped dir under
        ``missing="warn"``/``"ignore"``.

    Raises
    ------
    ArtifactIdentityError
        On a stamp mismatch (always), or on a missing stamp when
        ``missing="raise"``.
    """
    if missing not in ("raise", "warn", "ignore"):
        raise ValueError(f"missing= must be raise|warn|ignore, got {missing!r}")
    ident = read_identity(artifact_dir)
    if ident is None:
        msg = (
            f"{context}: {artifact_dir} carries no identity stamp — cannot "
            f"prove it belongs to {expected_pair!r}. Either adopt legacy "
            "artifacts once (`python scripts/audit_artifact_identity.py "
            "--adopt`) or rebuild this artifact (setup_fcav.py / "
            "setup_project.py)."
        )
        if missing == "raise":
            raise ArtifactIdentityError(msg)
        if missing == "warn":
            logger.warning(msg)
        return False
    found = ident.get("pair")
    if not pairs_equivalent(found, expected_pair):
        raise ArtifactIdentityError(
            f"{context}: {artifact_dir} is stamped for {found!r} but "
            f"{expected_pair!r} was expected — cross-graph artifact pollution "
            "(see the 2026-07 FCAV incident in this module's docstring). "
            "Refusing to continue. If the stamp is right, you are pointing at "
            "the wrong (dataset, graph); if the content is wrong, delete the "
            "dir and rebuild it for its graph."
        )
    return True
