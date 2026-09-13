#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/artifact_swap.py
=====================
Per-graph setup-artifact archive / swap-in for the t2c evaluation
harness.

Re-running ``setup_project.py`` for every (dataset, graph) pair at eval
time is too expensive — the schema export, embedding backfill, vector
index build, and FAISS index build can together take many minutes per
graph.  Instead each graph is set up **once** by
:mod:`scripts.setup_and_archive`, its outputs are archived under
``setup_artifacts/<dataset>__<graph>/``, and at eval time the parent
driver (:mod:`eval_run`) calls :func:`swap_in` to copy the right
archive into the live repo locations before launching a worker
subprocess.

Swap manifest
-------------
The :data:`SWAP_FILES` / :data:`SWAP_DIRS` lists below are the
authoritative manifest.  They mirror :mod:`paths` 1:1 plus a partial
``vector_config.py`` swap of the ``EMBEDDABLE_PROPERTIES`` block (other
constants in ``vector_config.py`` are project-wide and must NOT be
swapped).  The optional lists are swapped if present in the archive
and skipped with a debug log otherwise.

Round-trip safety
-----------------
:func:`round_trip_check` archives the live state to a temp dir, swaps it
back in, and hash-compares every file in the manifest.  Run it at the
end of :mod:`scripts.setup_and_archive` to catch incomplete manifests
or buggy copy logic before the user spends time setting up the rest of
their graphs.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from loguru import logger

from eval.artifact_identity import (
    ArtifactIdentityError,
    SENTINEL_NAME,
    read_identity,
    stamp_dir,
    verify_dir,
)
from paths import REPO_ROOT


# ──────────────────────────────────────────────────────────────────────────────
# 1. Manifest
# ──────────────────────────────────────────────────────────────────────────────

# Files to swap (relative to repo root).  Keep this list authoritative —
# the round-trip test in :mod:`scripts.setup_and_archive` uses it.
SWAP_FILES: list[str] = [
    "schema_data/schema_nodes.csv",
    "schema_data/schema_relations.csv",
    "schema_data/schema_meta.json",
    "generated/generated_node_tools.py",
    "generated/generated_rel_tools.py",
    "agent/prompts.py",
]

# Optional files (swap if present, skip if absent — emit a debug log).
SWAP_FILES_OPTIONAL: list[str] = [
    "generated/tool_descriptions.csv",
]

# Directories to swap (whole-tree replace).
#
# Both FAISS index directories are REQUIRED because ``step_build_faiss``
# in ``setup_project.py`` builds both unconditionally — the archive is a
# mode-agnostic snapshot, so any downstream value-linking-mode flip just works
# without re-running setup.  See the docstring of ``step_build_faiss``
# for the rationale (cost is negligible: ~100 embedding calls + a few
# MB on disk per graph).
SWAP_DIRS: list[str] = [
    "generated/faiss/tools_auto",
    "generated/faiss/tools_auto_node_only",
]

SWAP_DIRS_OPTIONAL: list[str] = [
    # Per-graph FCAV value index (VAL_LINK_MODE=fcav). Present only once
    # ``setup_fcav.py`` has built + archived it for that graph; absent archives
    # leave the live directory untouched.
    "generated/fcav",
]

# vector_config.py is partially swapped: only the EMBEDDABLE_PROPERTIES
# block.  At archive time, we extract that block and write it to
# ``<archive>/vector_config.embeddable_properties.snippet``.  At
# swap-in time we re-inject the snippet via
# :mod:`scripts._vector_config_io.replace_embeddable_block`.
_SNIPPET_NAME      = "vector_config.embeddable_properties.snippet"
_VECTOR_CONFIG_REL = "vector_config.py"
_SENTINEL_NAME     = SENTINEL_NAME  # single source: eval.artifact_identity


# ──────────────────────────────────────────────────────────────────────────────
# 2. Path helpers
# ──────────────────────────────────────────────────────────────────────────────

def _setup_artifacts_root() -> Path:
    """
    Resolve the archive root from :mod:`eval_config`, falling back to
    ``setup_artifacts/`` next to the repo root if eval_config is absent
    (so the round-trip test can run on a clean checkout).
    """
    try:
        from eval_config import SETUP_ARTIFACTS_ROOT  # noqa: WPS433
    except (ImportError, AttributeError):  # pragma: no cover — fallback only
        SETUP_ARTIFACTS_ROOT = "setup_artifacts"
    root = Path(SETUP_ARTIFACTS_ROOT)
    if not root.is_absolute():
        root = REPO_ROOT / root
    return root


def archive_dir_for(dataset: str, graph: str) -> Path:
    """
    Return the archive directory for one ``(dataset, graph)`` pair:
    ``<SETUP_ARTIFACTS_ROOT>/<dataset>__<graph>``.

    Flat single-level layout, double-underscore separator (dataset names
    are lowercase identifiers without ``__``, so the pair round-trips
    unambiguously through the filename).
    """
    return _setup_artifacts_root() / f"{dataset}__{graph}"


def _live_path(rel: str) -> Path:
    return REPO_ROOT / rel


# ──────────────────────────────────────────────────────────────────────────────
# 3. Validation
# ──────────────────────────────────────────────────────────────────────────────

def _validate_archive_complete(archive: Path) -> None:
    """Raise FileNotFoundError listing any required entries missing from *archive*."""
    if not archive.is_dir():
        raise FileNotFoundError(
            f"Archive directory not found: {archive}. "
            "Add the pair to eval_config.EVAL_PAIRS and run `python scripts/setup_and_archive.py` first."
        )
    missing: list[str] = []
    for rel in SWAP_FILES:
        if not (archive / rel).is_file():
            missing.append(rel)
    for rel in SWAP_DIRS:
        if not (archive / rel).is_dir():
            missing.append(rel + "/")
    if not (archive / _SNIPPET_NAME).is_file():
        missing.append(_SNIPPET_NAME)
    if missing:
        raise FileNotFoundError(
            f"Archive {archive} is incomplete; missing entries: {missing}. "
            "Re-run setup_and_archive.py for this (dataset, graph) pair."
        )
    for rel in SWAP_DIRS_OPTIONAL:
        p = archive / rel
        if p.is_dir() and not any(p.iterdir()):
            raise FileNotFoundError(
                f"Archive {archive} has empty optional directory {rel}/. "
                "Either delete the empty directory from the archive or re-run "
                "setup_and_archive.py to repopulate."
            )
    # Identity gate: any stamped per-graph index dir inside the archive must
    # be stamped for THIS archive's pair — a mismatch means the archive itself
    # is polluted (2026-07 FCAV incident) and must not be swapped in.
    # Unstamped (legacy) dirs pass with a warning here; the load boundary
    # (fcav._load / tool_search) stays fail-closed for the dirs that matter.
    expected_pair = archive.name
    for rel in [*SWAP_DIRS, *SWAP_DIRS_OPTIONAL]:
        p = archive / rel
        if p.is_dir():
            verify_dir(
                p, expected_pair,
                context=f"swap_in validation ({rel})", missing="warn",
            )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Atomic copy helpers
# ──────────────────────────────────────────────────────────────────────────────

def _atomic_copy_file(src: Path, dst: Path) -> None:
    """
    Copy *src* → *dst* via a sibling ``.tmp`` + ``rename`` so partial
    copies never overwrite the live file.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / (dst.name + ".swap.tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _replace_dir(src: Path, dst: Path) -> None:
    """
    Whole-tree replace ``dst`` with the contents of ``src``.

    Strategy: copy ``src`` to a sibling ``<dst>.swap.tmp`` first, then
    swap.  That way an aborted copy never leaves the live directory in
    a partially populated state.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".swap.tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp)

    # Move the old dir aside, swap the temp into place, then drop the old.
    backup: Optional[Path] = None
    if dst.exists():
        backup = dst.with_name(dst.name + ".swap.old")
        if backup.exists():
            shutil.rmtree(backup)
        os.rename(dst, backup)
    try:
        os.rename(tmp, dst)
    except Exception:
        # Roll back if the rename failed.
        if backup is not None and not dst.exists():
            os.rename(backup, dst)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────────
# 5. Public API — swap_in
# ──────────────────────────────────────────────────────────────────────────────

def _read_sentinel() -> Optional[str]:
    p = REPO_ROOT / _SENTINEL_NAME
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_sentinel(value: str) -> None:
    (REPO_ROOT / _SENTINEL_NAME).write_text(value + "\n", encoding="utf-8")


def swap_in(dataset: str, graph: str) -> None:
    """
    Copy the archived setup artifacts for ``(dataset, graph)`` into the
    live repo locations.

    Behaviour
    ---------
    * If ``EVAL_SKIP_SWAP=1`` is set in the environment, return
      immediately (no-op).  Used by the smoke test.
    * Idempotent: if the live ``.current_setup`` sentinel already names
      ``<dataset>__<graph>``, return immediately.
    * Validate the archive is complete (every required SWAP_FILES and
      SWAP_DIRS entry plus the snippet must exist) before any copy.
    * Atomic per-file: writes to a sibling ``.swap.tmp`` and renames in.
    * After all copies succeed, write ``<dataset>__<graph>`` to the
      sentinel.

    Raises
    ------
    FileNotFoundError
        If the archive is missing or incomplete.
    """
    if os.environ.get("EVAL_SKIP_SWAP") == "1":
        logger.debug("artifact_swap.swap_in: EVAL_SKIP_SWAP=1, no-op.")
        return

    pair_id = f"{dataset}__{graph}"
    archive = archive_dir_for(dataset, graph)
    if _read_sentinel() == pair_id:
        # The sentinel only records a NAME. The live files are tracked in git,
        # so a `git pull` / checkout can silently replace them with another
        # graph's copies while the sentinel still says this pair (seen
        # 2026-09-13: every cell refused by the graph guard). Trust the
        # sentinel only when the live required files match the archive.
        stale = [rel for rel in SWAP_FILES
                 if not (_live_path(rel).is_file() and (archive / rel).is_file()
                         and _file_sha(_live_path(rel)) == _file_sha(archive / rel))]
        if not stale:
            logger.debug(f"artifact_swap.swap_in: sentinel already at {pair_id} and live files match, no-op.")
            return
        logger.warning(f"artifact_swap.swap_in: sentinel says {pair_id} but live files differ from the "
                       f"archive ({', '.join(stale)}) — re-swapping.")

    _validate_archive_complete(archive)

    try:
        # ── Files ───────────────────────────────────────────────────────────
        for rel in SWAP_FILES:
            _atomic_copy_file(archive / rel, _live_path(rel))

        for rel in SWAP_FILES_OPTIONAL:
            src = archive / rel
            if src.is_file():
                _atomic_copy_file(src, _live_path(rel))
            else:
                logger.debug(f"artifact_swap.swap_in: optional file absent in archive: {rel}")

        # ── Dirs ────────────────────────────────────────────────────────────
        for rel in SWAP_DIRS:
            _replace_dir(archive / rel, _live_path(rel))

        for rel in SWAP_DIRS_OPTIONAL:
            src = archive / rel
            live = _live_path(rel)
            if src.is_dir():
                _replace_dir(src, live)
            elif live.is_dir():
                # Hermetic swap: absent in archive ⇒ absent live. Leaving the
                # previous graph's index behind is how the 2026-07 FCAV
                # pollution started (a later archive_current folded the stale
                # dir into a foreign archive).
                shutil.rmtree(live)
                logger.info(
                    f"artifact_swap.swap_in: removed stale live {rel}/ — "
                    f"absent from archive {pair_id} (hermetic swap)."
                )
            else:
                logger.debug(f"artifact_swap.swap_in: optional dir absent in archive: {rel}")

        # ── Partial vector_config.py rewrite ────────────────────────────────
        from scripts._vector_config_io import replace_embeddable_block
        snippet = (archive / _SNIPPET_NAME).read_text(encoding="utf-8").rstrip("\n")
        replace_embeddable_block(str(_live_path(_VECTOR_CONFIG_REL)), snippet)

        _write_sentinel(pair_id)
    except Exception as exc:
        logger.error(
            f"artifact_swap.swap_in: PARTIAL FAILURE for {pair_id}. "
            f"Live artifacts may now be in an inconsistent state — a mix of "
            f"the previous graph and {pair_id}. Before running eval, re-run "
            f"swap_in for the intended graph, or run "
            f"`scripts/setup_and_archive.py {dataset} {graph} --force` to "
            f"re-establish a known state. Original error: {exc}"
        )
        raise
    logger.info(f"artifact_swap.swap_in: live setup is now {pair_id}.")


# ──────────────────────────────────────────────────────────────────────────────
# 5b. Public API — archive_optional_dir
# ──────────────────────────────────────────────────────────────────────────────

def archive_optional_dir(dataset: str, graph: str, rel: str) -> Path:
    """
    Fold ONE optional per-graph index dir (``rel`` in :data:`SWAP_DIRS_OPTIONAL`,
    e.g. ``generated/fcav``) from the live tree into the pair's archive,
    leaving every other archived file untouched.

    This is what ``setup_fcav.py`` uses: the published archive files
    (prompts, tools, schema, routing index — pinned by
    ``setup_artifacts/MANIFEST.json``) must stay byte-identical on every
    machine, so building a value index must not go through
    :func:`archive_current`, which wipes and rewrites the whole archive.

    Fail closed like :func:`archive_current`: the live dir must carry a
    build-time identity stamp for this pair (the 2026-07 pollution guard).
    A symlinked archive is resolved to its target. Returns the destination.
    """
    if rel not in SWAP_DIRS_OPTIONAL:
        raise ValueError(f"{rel!r} is not an optional swap dir ({SWAP_DIRS_OPTIONAL})")
    live = _live_path(rel)
    if not live.is_dir():
        raise FileNotFoundError(f"Live index dir missing: {live}")
    pair = f"{dataset}__{graph}"
    verify_dir(live, pair, context=f"archive_optional_dir ({rel})", missing="raise")
    archive = archive_dir_for(dataset, graph)
    if archive.is_symlink():
        archive = archive.resolve()
    if not archive.is_dir():
        raise FileNotFoundError(
            f"Archive directory not found: {archive}. The base archive must exist "
            "before an optional index can be folded into it."
        )
    dst = archive / rel
    _replace_dir(live, dst)
    logger.info(f"artifact_swap.archive_optional_dir: {rel} → {dst}")
    return dst


# ──────────────────────────────────────────────────────────────────────────────
# 6. Public API — archive_current
# ──────────────────────────────────────────────────────────────────────────────

def archive_current(dataset: str, graph: str, *, force: bool = False) -> None:
    """
    Copy the current live setup outputs into
    :func:`archive_dir_for(dataset, graph)`.

    Parameters
    ----------
    force
        If ``True`` and the archive directory already exists, it is
        wiped first.  If ``False`` (default), :class:`FileExistsError`
        is raised so the user has to opt in to overwrite.

    Also extracts the current ``EMBEDDABLE_PROPERTIES`` block from
    ``vector_config.py`` and writes it to
    ``<archive>/vector_config.embeddable_properties.snippet``.
    """
    archive = archive_dir_for(dataset, graph)
    if archive.is_symlink():
        # One graph under two names (mindthequery_augmented__bloom ->
        # mindthequery_augmented__bloom50): rebuild the link's target in place
        # so the link keeps pointing at a valid archive. rmtree() refuses a
        # symlink outright.
        archive = archive.resolve()
    if archive.exists():
        if not force:
            raise FileExistsError(
                f"Archive already exists: {archive}. Pass force=True (or "
                "--force on the CLI) to overwrite."
            )
        shutil.rmtree(archive)
    archive.mkdir(parents=True, exist_ok=True)

    # ── Required files (must exist live or this is a programming error) ─────
    for rel in SWAP_FILES:
        live = _live_path(rel)
        if not live.is_file():
            raise FileNotFoundError(
                f"Required artifact missing on disk: {live}. "
                "Did setup_project.py finish successfully?"
            )
        dst = archive / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live, dst)

    # ── Optional files ──────────────────────────────────────────────────────
    for rel in SWAP_FILES_OPTIONAL:
        live = _live_path(rel)
        if live.is_file():
            dst = archive / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, dst)
        else:
            logger.debug(f"artifact_swap.archive_current: optional file absent: {rel}")

    pair = f"{dataset}__{graph}"

    # ── Required dirs ───────────────────────────────────────────────────────
    for rel in SWAP_DIRS:
        live = _live_path(rel)
        if not live.is_dir():
            raise FileNotFoundError(
                f"Required artifact directory missing: {live}. "
                "Did setup_project.py Step 10 (FAISS build) finish?"
            )
        # A live dir stamped for another graph must never be archived under
        # this pair's name. Unstamped (legacy) dirs pass with a warning and
        # get stamped IN PLACE before the copy — archive_current's own
        # (dataset, graph) args are the authoritative identity here, and
        # stamping live-first keeps live == archive (round_trip_check).
        verify_dir(live, pair,
                   context=f"archive_current ({rel})", missing="warn")
        if read_identity(live) is None:
            try:
                stamp_dir(live, dataset, graph)
            except ArtifactIdentityError:
                logger.debug(
                    f"artifact_swap.archive_current: {rel} has no carrier "
                    "file to stamp (pre-fingerprint index?) — left unstamped."
                )
        dst = archive / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(live, dst)

    # ── Optional dirs (per-graph value indexes, e.g. generated/fcav) ───────
    # Fail closed: these are exactly the dirs that caused the 2026-07 FCAV
    # pollution. An optional dir may only enter an archive when it can PROVE
    # (build-time stamp) that it belongs to this pair.
    for rel in SWAP_DIRS_OPTIONAL:
        live = _live_path(rel)
        if live.is_dir():
            verify_dir(live, pair,
                       context=f"archive_current ({rel})", missing="raise")
            dst = archive / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(live, dst)
        else:
            logger.debug(f"artifact_swap.archive_current: optional dir absent: {rel}")

    # ── EMBEDDABLE_PROPERTIES snippet ───────────────────────────────────────
    from scripts._vector_config_io import extract_embeddable_block
    snippet = extract_embeddable_block(str(_live_path(_VECTOR_CONFIG_REL)))
    (archive / _SNIPPET_NAME).write_text(snippet + "\n", encoding="utf-8")

    logger.info(f"artifact_swap.archive_current: wrote {archive}.")


# ──────────────────────────────────────────────────────────────────────────────
# 7. Public API — round_trip_check
# ──────────────────────────────────────────────────────────────────────────────

def _file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_signature(root: Path) -> List[tuple[str, str]]:
    """Sorted list of (relpath, sha256) for every file under *root*."""
    out: List[tuple[str, str]] = []
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append((str(p.relative_to(root)), _file_sha(p)))
    return out


def round_trip_check(dataset: str, graph: str) -> None:
    """
    Sanity-check the swap manifest by archiving the live state to a temp
    directory, swapping it back in (with the sentinel forced to a
    different value so the no-op short-circuit doesn't fire), and
    hash-comparing every file in :data:`SWAP_FILES` and the recursive
    contents of :data:`SWAP_DIRS`.

    Raises ``RuntimeError`` on any mismatch.
    """
    # Archive into a temp dir and run swap_in via a temporarily relocated
    # SETUP_ARTIFACTS_ROOT.  The simplest way is to call the real
    # archive_current/swap_in into a temp directory by monkey-patching
    # _setup_artifacts_root for the duration of the check.
    #
    # The live snapshot is taken AFTER archive_current: archiving may stamp a
    # previously unstamped live index dir in place (a one-time identity
    # migration — see eval.artifact_identity), and the invariant under test is
    # "swap_in restores exactly what archive_current wrote", not "archiving is
    # a pure read".
    with tempfile.TemporaryDirectory(prefix="t2c_round_trip_") as td:
        td_root = Path(td)
        global _setup_artifacts_root  # noqa: PLW0603 — intentional shim
        original = _setup_artifacts_root

        def _shim() -> Path:
            return td_root
        _setup_artifacts_root = _shim  # type: ignore[assignment]

        try:
            archive_current(dataset, graph, force=True)

            pre_files = {rel: _file_sha(_live_path(rel)) for rel in SWAP_FILES if _live_path(rel).is_file()}
            pre_dirs  = {rel: _dir_signature(_live_path(rel)) for rel in SWAP_DIRS}
            pre_snip  = None
            vc_path = _live_path(_VECTOR_CONFIG_REL)
            if vc_path.is_file():
                from scripts._vector_config_io import extract_embeddable_block
                pre_snip = extract_embeddable_block(str(vc_path))

            # Force swap_in to do real work even if the sentinel already
            # matches.
            sentinel = REPO_ROOT / _SENTINEL_NAME
            if sentinel.exists():
                sentinel.unlink()

            swap_in(dataset, graph)
        finally:
            _setup_artifacts_root = original  # type: ignore[assignment]

    # Re-hash and diff.
    post_files = {rel: _file_sha(_live_path(rel)) for rel in SWAP_FILES if _live_path(rel).is_file()}
    post_dirs  = {rel: _dir_signature(_live_path(rel)) for rel in SWAP_DIRS}
    post_snip  = None
    if vc_path.is_file():
        from scripts._vector_config_io import extract_embeddable_block
        post_snip = extract_embeddable_block(str(vc_path))

    diffs: list[str] = []
    for rel, pre in pre_files.items():
        post = post_files.get(rel)
        if post != pre:
            diffs.append(f"file changed after round-trip: {rel}")
    for rel, pre in pre_dirs.items():
        post = post_dirs.get(rel, [])
        if post != pre:
            diffs.append(f"dir changed after round-trip: {rel}")
    if pre_snip != post_snip:
        diffs.append("EMBEDDABLE_PROPERTIES snippet changed after round-trip")

    if diffs:
        raise RuntimeError(
            "artifact_swap.round_trip_check failed:\n  - "
            + "\n  - ".join(diffs)
            + "\nSwap manifest is incomplete or buggy — review eval/artifact_swap.py."
        )
    logger.info(f"artifact_swap.round_trip_check OK for ({dataset}, {graph}).")
