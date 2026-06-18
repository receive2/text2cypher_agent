#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/setup_and_archive.py
============================
Batch-set up every ``(dataset, graph)`` pair in
:data:`eval_config.EVAL_PAIRS` and archive each pair's setup outputs for
later reuse by the evaluation harness.

Workflow (per pair)
-------------------
1. **Pre-pair wipe** — delete every "live state" artifact left behind by
   any previous run, so the upcoming ``setup_project.py`` invocation
   cannot accidentally bundle stale data into the new archive.
2. Look up the :class:`eval_config.GraphConn` for the pair.
3. **Neo4j embedding reset** — drop every vector index and null every
   embedding-shaped property on the pair's live database, so setup
   re-embeds against the current ``vector_config`` identity rather than
   preserving a previous graph's stale vectors.
4. Subprocess-invoke ``setup_project.py --yes`` with the pair's
   connection injected via ``NEO4J_*`` env vars and the pair's
   ``database`` passed on ``--database``.
5. On success, archive the live setup outputs under
   ``setup_artifacts/<dataset>__<graph>/`` via
   :func:`eval.artifact_swap.archive_current` (``force=True``).
6. Round-trip-check the manifest by archiving + swapping into a temp
   directory.  If that fails, the on-disk archive is **deleted** before
   we abort, so a corrupt archive never sits on disk looking valid.
7. **Post-pair wipe** — runs in ``finally`` so the working tree is left
   clean even if setup or round-trip-check raised.

Fail-fast
---------
If any pair fails (subprocess non-zero, archive failure, round-trip
failure, Neo4j reset failure, etc.) the entire run aborts immediately.
Most pair failures are systemic (invalid API key, Neo4j unreachable,
disk full) — continuing through the remaining pairs would just produce
identical failures and waste compute.  The failed pair's own post-pair
``wipe_live_state()`` still runs (via ``finally``) so the working tree
is left clean for the operator.

After the abort the script prints:

* a per-pair summary (``✓`` done / ``✗`` failed / ``·`` skipped), and
* a copy-pasteable retry block listing the failed pair plus every pair
  that was skipped because of the early abort — so the user can paste
  the block straight back into ``eval_config.py`` and resume from where
  the run broke.

The script exits non-zero on any failure.

Usage
-----
::

    python scripts/setup_and_archive.py        # no arguments

The script reads :data:`eval_config.EVAL_PAIRS` as the single source of
truth.  To set up only a subset of graphs, edit ``eval_config.py`` and
shrink ``EVAL_PAIRS``.

The legacy ``python scripts/setup_and_archive.py <dataset> <graph>``
positional-args invocation is rejected with a non-zero exit; there is
no fallback, by design — any fallback would reintroduce the
"CLI args disagree with eval_config.py" confusion that this rewrite
exists to eliminate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

from loguru import logger

# Repo root is ``scripts/..``.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Make sibling top-level modules (eval_config, eval, paths, ...) importable
# when the user invokes this script from anywhere.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import eval_config as cfg  # noqa: E402
from eval import artifact_swap  # noqa: E402
from eval.artifact_swap import (  # noqa: E402
    archive_current,
    archive_dir_for,
    round_trip_check,
)


# ──────────────────────────────────────────────────────────────────────────────
# Live-state inventory (introspected from eval/artifact_swap.py)
# ──────────────────────────────────────────────────────────────────────────────

# Extra paths that are NOT in the swap manifest but still count as
# per-pair live state and must be wiped between pairs:
#   - ``vector_config.py.bak`` is created by
#     :func:`scripts._vector_config_io._backup` every time the
#     EMBEDDABLE_PROPERTIES block is rewritten.  It pins the previous
#     pair's snippet to disk; leaving it behind is misleading.
#   - The two ``__pycache__`` directories cache the previous pair's
#     bytecode for ``generated/*.py`` and ``agent/prompts.py``; clearing
#     them eliminates any chance of a misconfigured run importing stale
#     bytecode.
_EXTRA_LIVE_FILES: list[str] = [
    "vector_config.py.bak",
]
_EXTRA_LIVE_DIRS: list[str] = [
    "generated/__pycache__",
    "agent/__pycache__",
]

# Suffixes the atomic-copy helpers in artifact_swap.py use for in-flight
# work; clean them up if a previous run was interrupted mid-swap.
_SWAP_LEFTOVER_SUFFIXES: tuple[str, ...] = (".swap.tmp", ".swap.old")


def _live_files() -> List[str]:
    """Required + optional file entries from the swap manifest."""
    return list(artifact_swap.SWAP_FILES) + list(artifact_swap.SWAP_FILES_OPTIONAL)


def _live_dirs() -> List[str]:
    """Required + optional dir entries from the swap manifest."""
    return list(artifact_swap.SWAP_DIRS) + list(artifact_swap.SWAP_DIRS_OPTIONAL)


def _abs(rel: str) -> Path:
    return _REPO_ROOT / rel


# ──────────────────────────────────────────────────────────────────────────────
# Wipe primitives
# ──────────────────────────────────────────────────────────────────────────────

def _wipe_file(rel: str) -> None:
    """Delete file at *rel* under the repo root.  No-op if absent."""
    p = _abs(rel)
    if p.is_file() or p.is_symlink():
        try:
            p.unlink()
            logger.info(f"setup_and_archive.wipe: removed file {rel}")
        except OSError as exc:
            raise RuntimeError(f"failed to remove {p}: {exc}") from exc
    else:
        logger.debug(f"setup_and_archive.wipe: file already absent: {rel}")


def _wipe_dir(rel: str) -> None:
    """Recursively delete directory at *rel* under the repo root.  No-op if absent."""
    p = _abs(rel)
    if p.is_dir():
        try:
            shutil.rmtree(p)
            logger.info(f"setup_and_archive.wipe: removed dir  {rel}")
        except OSError as exc:
            raise RuntimeError(f"failed to remove {p}: {exc}") from exc
    else:
        logger.debug(f"setup_and_archive.wipe: dir already absent: {rel}")


def _wipe_swap_leftovers(rels: Iterable[str]) -> None:
    """
    For each *rel* in the manifest, also wipe any sibling
    ``<rel><suffix>`` left behind by an interrupted ``swap_in``.
    """
    seen: set[Path] = set()
    for rel in rels:
        for suffix in _SWAP_LEFTOVER_SUFFIXES:
            leftover_rel = rel + suffix
            p = _abs(leftover_rel)
            if p in seen:
                continue
            seen.add(p)
            if p.is_file() or p.is_symlink():
                try:
                    p.unlink()
                    logger.info(
                        f"setup_and_archive.wipe: removed swap leftover {leftover_rel}"
                    )
                except OSError as exc:
                    raise RuntimeError(f"failed to remove {p}: {exc}") from exc
            elif p.is_dir():
                try:
                    shutil.rmtree(p)
                    logger.info(
                        f"setup_and_archive.wipe: removed swap leftover {leftover_rel}/"
                    )
                except OSError as exc:
                    raise RuntimeError(f"failed to remove {p}: {exc}") from exc


def _reset_embeddable_properties_block() -> None:
    """
    Reset the ``EMBEDDABLE_PROPERTIES`` block in ``vector_config.py`` to
    an empty list, so that the next ``setup_project.py`` invocation
    auto-discovers the block fresh from a known empty state.

    No-op when ``vector_config.py`` is missing.  When the block isn't
    found (e.g. corrupted hand-edit), surface a warning rather than an
    error so the wipe stays best-effort.
    """
    vc_path = _abs(artifact_swap._VECTOR_CONFIG_REL)
    if not vc_path.is_file():
        logger.debug(
            f"setup_and_archive.wipe: vector_config absent ({vc_path}); skipping reset"
        )
        return
    try:
        from scripts._vector_config_io import replace_embeddable_block
        replace_embeddable_block(str(vc_path), "EMBEDDABLE_PROPERTIES = []")
        logger.info(
            "setup_and_archive.wipe: reset EMBEDDABLE_PROPERTIES block to []"
        )
    except RuntimeError as exc:
        logger.warning(
            f"setup_and_archive.wipe: could not reset EMBEDDABLE_PROPERTIES "
            f"block ({exc}); leaving vector_config.py untouched."
        )


def wipe_live_state() -> None:
    """
    Delete every artifact that counts as per-pair live state.

    The manifest of files + dirs is read live from
    :mod:`eval.artifact_swap` so this stays in sync with whatever the
    swap layer considers per-graph.  Plus ``.current_setup``,
    ``vector_config.py.bak``, the two ``__pycache__`` dirs, any
    ``*.swap.tmp`` / ``*.swap.old`` leftovers, and the
    ``EMBEDDABLE_PROPERTIES`` block (reset to ``[]``).
    """
    logger.info("setup_and_archive.wipe: wiping live state for clean run")

    files = _live_files()
    dirs = _live_dirs()

    # Manifest files
    for rel in files:
        _wipe_file(rel)

    # Manifest dirs
    for rel in dirs:
        _wipe_dir(rel)

    # Sentinel
    _wipe_file(artifact_swap._SENTINEL_NAME)

    # __pycache__ dirs (cached bytecode for swap-targeted modules)
    for rel in _EXTRA_LIVE_DIRS:
        _wipe_dir(rel)

    # Stale .swap.tmp / .swap.old siblings under any manifest entry
    _wipe_swap_leftovers(files + dirs)

    # Reset the partial-swap target (EMBEDDABLE_PROPERTIES block).
    # This re-creates ``vector_config.py.bak`` as a side effect of
    # _vector_config_io._backup, so we MUST wipe the .bak AFTER the
    # reset, not before.
    _reset_embeddable_properties_block()

    # Stale ``vector_config.py.bak`` (plus any other extra files) — wipe
    # last so we also catch the .bak the reset just created.
    for rel in _EXTRA_LIVE_FILES:
        _wipe_file(rel)

    logger.info("setup_and_archive.wipe: live state wiped")


# ──────────────────────────────────────────────────────────────────────────────
# Per-pair runner
# ──────────────────────────────────────────────────────────────────────────────

def _build_env(uri: str, user: str, password: str, database: str) -> dict[str, str]:
    """Copy the parent env and overlay the standard ``NEO4J_*`` names."""
    env = dict(os.environ)
    env["NEO4J_URI"]      = uri
    env["NEO4J_USERNAME"] = user
    env["NEO4J_PASSWORD"] = password
    env["NEO4J_DATABASE"] = database
    return env


def _build_setup_argv(database: str) -> List[str]:
    """Translate a pair's database name into a ``setup_project.py`` argv."""
    return [
        sys.executable,
        str(_REPO_ROOT / "setup_project.py"),
        "--database", database,
        "--yes",  # always non-interactive in batch mode
        "--skip-embeddings",  # fuzzy retrieval is the paper baseline (TOOL_RETRIEVAL_MODE="fuzzy")
                              # so Steps 6-7 (embedding backfill, vector indexes) are unnecessary.
                              # Remove this line for a hybrid-mode run.
    ]


class PairFailure(RuntimeError):
    """Raised by :func:`_run_one_pair` to signal a single-pair failure."""


# ──────────────────────────────────────────────────────────────────────────────
# Neo4j-side embedding reset
# ──────────────────────────────────────────────────────────────────────────────

# Floating-point list type names emitted by ``db.schema.nodeTypeProperties`` /
# ``db.schema.relTypeProperties``.  Matched case-insensitively below.
_EMBEDDING_TYPE_NAMES: tuple[str, ...] = (
    "LIST<FLOAT>",
    "LIST<FLOAT64>",
    "LIST<DOUBLE>",
)

# Property-name suffixes that mark a column as an embedding, regardless of
# its declared type.  Matches the gen_tools layer-3 filter.
_EMBEDDING_NAME_SUFFIXES: tuple[str, ...] = ("_embedding", "_vector")


def _is_embedding_property(prop_name: str, prop_types: list[str] | None) -> bool:
    """True if *prop_name* / *prop_types* look like an embedding column."""
    if any(prop_name.endswith(suf) for suf in _EMBEDDING_NAME_SUFFIXES):
        return True
    if prop_types:
        upper = {t.upper().replace(" ", "") for t in prop_types}
        if any(t in upper for t in _EMBEDDING_TYPE_NAMES):
            return True
    return False


def _dedupe(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for p in pairs:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _discover_embedding_props(
    session,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Return ``(node_pairs, rel_pairs)`` where each pair is
    ``(label_or_reltype, property_name)`` for every property in the live
    schema that looks like an embedding column.

    Uses ``db.schema.nodeTypeProperties`` / ``db.schema.relTypeProperties``
    — both are read-only and available on Neo4j 5.x.
    """
    node_pairs: list[tuple[str, str]] = []
    rel_pairs:  list[tuple[str, str]] = []

    for row in session.run(
        "CALL db.schema.nodeTypeProperties() "
        "YIELD nodeLabels, propertyName, propertyTypes "
        "RETURN nodeLabels, propertyName, propertyTypes"
    ):
        labels = row["nodeLabels"] or []
        pname  = row["propertyName"]
        ptypes = row["propertyTypes"]
        if pname is None:
            continue
        if not _is_embedding_property(pname, ptypes):
            continue
        for lbl in labels:
            node_pairs.append((lbl, pname))

    for row in session.run(
        "CALL db.schema.relTypeProperties() "
        "YIELD relType, propertyName, propertyTypes "
        "RETURN relType, propertyName, propertyTypes"
    ):
        rtype = row["relType"]
        pname = row["propertyName"]
        ptypes = row["propertyTypes"]
        if pname is None or rtype is None:
            continue
        if not _is_embedding_property(pname, ptypes):
            continue
        # ``db.schema.relTypeProperties`` returns ``:`TYPE`` strings —
        # strip the leading ":" + backticks so the rel-type is usable
        # as a Cypher identifier.
        rtype = rtype.lstrip(":").strip("`")
        rel_pairs.append((rtype, pname))

    return _dedupe(node_pairs), _dedupe(rel_pairs)


def _reset_neo4j_embeddings(conn) -> None:
    """
    Drop every vector index and null every embedding-shaped property on
    the live database for *conn*.

    "Embedding-shaped" is defined two ways (either is sufficient):
      * Property type is ``LIST<FLOAT>`` / ``LIST<FLOAT64>`` /
        ``LIST<DOUBLE>``  (matches the gen_tools layer-1 filter).
      * Property name ends in ``_embedding`` or ``_vector``  (layer-3).

    Logs the embedding backend / model / dimensions read from
    :mod:`vector_config` so the operator can verify the run is being
    reset against the *intended* embedding identity.

    Called from :func:`_run_one_pair` BEFORE the ``setup_project.py``
    subprocess and AFTER :func:`wipe_live_state`, so that
    ``setup_project.py`` always starts against a Neo4j whose embeddings
    match the live ``vector_config`` rather than the previous graph's
    leftovers.

    Implementation notes
    --------------------
    * ``CALL { ... } IN TRANSACTIONS OF N ROWS`` requires implicit-tx
      context (``session.run`` directly), matching the pattern in
      :func:`embedding.embedding_helper.null_embedding_properties`.
    * Vector indexes are discovered via ``SHOW VECTOR INDEXES`` so this
      works even when ``EMBEDDABLE_PROPERTIES`` was just reset to ``[]``
      — we don't need a spec to know which indexes exist on the live DB.
    """
    from neo4j import GraphDatabase
    import vector_config as vc

    # Log the live embedding identity so the operator can verify what
    # they're resetting against.
    logger.info(
        f"setup_and_archive.reset_neo4j: backend={vc.EMBEDDING_BACKEND!r} "
        f"model={vc.EMBEDDING_MODEL_NAME!r} dim={vc.EMBEDDING_DIMENSIONS} "
        f"target={conn.uri} db={conn.database!r}"
    )

    chunk = int(getattr(vc, "RESET_TX_BATCH_SIZE", 10000))

    driver = GraphDatabase.driver(conn.uri, auth=(conn.user, conn.password))
    try:
        with driver.session(database=conn.database) as session:
            # ── Discover the live embedding columns ───────────────────
            node_pairs, rel_pairs = _discover_embedding_props(session)
            logger.info(
                f"setup_and_archive.reset_neo4j: discovered "
                f"{len(node_pairs)} node embedding prop(s), "
                f"{len(rel_pairs)} rel embedding prop(s) on {conn.uri}"
            )

            # ── Drop every vector index ───────────────────────────────
            existing = [
                r["name"] for r in session.run(
                    "SHOW VECTOR INDEXES YIELD name RETURN name"
                )
            ]
            for iname in existing:
                try:
                    session.run(f"DROP INDEX `{iname}` IF EXISTS").consume()
                    logger.info(
                        f"setup_and_archive.reset_neo4j: dropped vector index {iname}"
                    )
                except Exception as exc:  # noqa: BLE001
                    raise PairFailure(
                        f"failed to drop vector index {iname!r} on "
                        f"{conn.uri}/{conn.database}: {exc}"
                    ) from exc

            # ── Null node embedding properties ────────────────────────
            for lbl, pname in node_pairs:
                safe_lbl = lbl.replace("`", "``")
                safe_p   = pname.replace("`", "``")
                try:
                    session.run(
                        f"MATCH (n:`{safe_lbl}`) "
                        f"WHERE n.`{safe_p}` IS NOT NULL "
                        f"CALL {{ WITH n REMOVE n.`{safe_p}` }} "
                        f"IN TRANSACTIONS OF {chunk} ROWS"
                    ).consume()
                    logger.info(
                        f"setup_and_archive.reset_neo4j: nulled {lbl}.{pname}"
                    )
                except Exception as exc:  # noqa: BLE001
                    raise PairFailure(
                        f"failed to null node embedding {lbl}.{pname} on "
                        f"{conn.uri}/{conn.database}: {exc}"
                    ) from exc

            # ── Null relationship embedding properties ────────────────
            for rtype, pname in rel_pairs:
                safe_r = rtype.replace("`", "``")
                safe_p = pname.replace("`", "``")
                try:
                    session.run(
                        f"MATCH ()-[r:`{safe_r}`]->() "
                        f"WHERE r.`{safe_p}` IS NOT NULL "
                        f"CALL {{ WITH r REMOVE r.`{safe_p}` }} "
                        f"IN TRANSACTIONS OF {chunk} ROWS"
                    ).consume()
                    logger.info(
                        f"setup_and_archive.reset_neo4j: nulled {rtype}.{pname} (rel)"
                    )
                except Exception as exc:  # noqa: BLE001
                    raise PairFailure(
                        f"failed to null rel embedding {rtype}.{pname} on "
                        f"{conn.uri}/{conn.database}: {exc}"
                    ) from exc
    finally:
        driver.close()


_AUG_SUFFIX = "_augmented"


def _maybe_reuse_base_archive(dataset: str, graph: str) -> bool:
    """
    Short-circuit setup for ``*_augmented`` pairs whose base archive
    already exists on disk.

    Why
    ---
    Augmenting a dataset only rewrites the natural-language question;
    the gold Cypher, the schema, and the Neo4j graph state are all
    untouched.  That means ``setup_artifacts/<dataset>_augmented__<graph>/``
    can be a verbatim copy of ``setup_artifacts/<dataset>__<graph>/`` —
    no Cypher-tool regeneration, no FAISS rebuild, no embedding
    backfill, no LLM tool-description fees.

    Behaviour
    ---------
    * Returns ``True`` when the base archive existed and the augmented
      archive was successfully populated by ``shutil.copytree`` (the
      caller treats this as a completed pair and skips wipe / setup /
      round-trip-check entirely).
    * Returns ``False`` (and logs a warning) when the base archive is
      missing — caller falls through to the full setup path.  The
      warning recommends listing base pairs before augmented pairs in
      ``EVAL_PAIRS`` so the augmented variant inherits a verified state
      instead of paying the full setup cost.
    * Returns ``False`` for non-augmented datasets.
    """
    if not dataset.endswith(_AUG_SUFFIX):
        return False

    base = dataset[: -len(_AUG_SUFFIX)]
    base_archive = archive_dir_for(base, graph)
    aug_archive  = archive_dir_for(dataset, graph)

    if not base_archive.is_dir():
        logger.warning(
            f"setup_and_archive: no base archive at {base_archive} for "
            f"{dataset}__{graph}; falling through to full setup. "
            "Tip: list base pairs (e.g. ('cypherbench', 'movie')) before "
            "augmented pairs (e.g. ('cypherbench_augmented', 'movie')) "
            "in EVAL_PAIRS so the augmented variant inherits the base "
            "archive verbatim and skips a redundant setup_project.py run."
        )
        return False

    # Wipe any pre-existing augmented archive so the copy is atomic.
    if aug_archive.exists():
        shutil.rmtree(aug_archive)
    shutil.copytree(base_archive, aug_archive)
    logger.info(
        f"setup_and_archive: ✓ {dataset}__{graph} reused base archive "
        f"({base_archive.name}); skipped setup_project.py + round-trip check."
    )
    return True


def _run_one_pair(dataset: str, graph: str) -> None:
    """
    Set up + archive + round-trip-check a single ``(dataset, graph)`` pair.

    Raises :class:`PairFailure` on any failure path.  On round-trip
    failure specifically, the just-written archive directory is deleted
    before the exception propagates so a corrupt archive never sits on
    disk looking valid.

    Augmented-dataset short-circuit
    -------------------------------
    If *dataset* ends with ``_augmented`` and the base archive already
    exists, we copy the base archive verbatim into the augmented slot
    and return immediately — no wipe, no setup_project.py, no round-
    trip check.  The augmented variant inherits the base's verified
    state.  See :func:`_maybe_reuse_base_archive` for the rationale.
    """
    # ── Augmented-pair archive reuse (must run BEFORE any setup work) ──────
    if _maybe_reuse_base_archive(dataset, graph):
        return

    # ── Connection lookup ──────────────────────────────────────────────────
    try:
        conn = cfg.conn_for(dataset, graph)
    except KeyError as exc:
        raise PairFailure(
            f"no GraphConn registered for ({dataset!r}, {graph!r}): {exc}"
        ) from exc

    # ── Neo4j-side embedding reset ────────────────────────────────────────
    # Runs AFTER wipe_live_state (which cleared the local artifacts) and
    # BEFORE setup_project.py runs.  Drops every vector index and nulls
    # every embedding-shaped property on the live database, so the
    # upcoming setup re-embeds against the current vector_config identity
    # instead of preserving a previous graph's stale vectors.
    try:
        _reset_neo4j_embeddings(conn)
    except PairFailure:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PairFailure(
            f"_reset_neo4j_embeddings failed for {dataset}__{graph}: {exc}"
        ) from exc

    # ── Subprocess: setup_project.py ───────────────────────────────────────
    argv = _build_setup_argv(conn.database)
    env  = _build_env(conn.uri, conn.user, conn.password, conn.database)

    logger.info(
        f"setup_and_archive: ▶ {dataset}__{graph}\n"
        f"    uri      : {conn.uri}\n"
        f"    database : {conn.database}\n"
        f"    cmd      : {' '.join(argv)}"
    )

    proc = subprocess.run(argv, env=env, check=False, cwd=str(_REPO_ROOT))
    if proc.returncode != 0:
        raise PairFailure(
            f"setup_project.py exited with code {proc.returncode}; "
            "see stdout/stderr above for details."
        )

    # ── Guard: never freeze a contaminated live tree into an archive ───────
    # setup_project.py just regenerated the live tools from THIS graph's
    # schema, but a partial/stale run could leave the previous graph's tools
    # behind. Cross-check against the database before archiving so a poisoned
    # archive can never sit on disk looking valid.
    from eval.graph_guard import check_tools_match_graph
    ok, detail = check_tools_match_graph(
        _REPO_ROOT / "generated" / "generated_node_tools.py",
        conn.uri, conn.user, conn.password, conn.database,
    )
    if not ok:
        raise PairFailure(
            f"refusing to archive {dataset}__{graph}: live tools do not "
            f"match the graph — {detail}"
        )

    # ── Archive ────────────────────────────────────────────────────────────
    archive = archive_dir_for(dataset, graph)
    logger.info(f"setup_and_archive: archiving to {archive} ...")
    try:
        archive_current(dataset, graph, force=True)
    except Exception as exc:  # noqa: BLE001
        raise PairFailure(f"archive_current failed: {exc}") from exc

    # ── Round-trip check (manifest sanity) ─────────────────────────────────
    logger.info("setup_and_archive: running round-trip check ...")
    try:
        round_trip_check(dataset, graph)
    except Exception as exc:  # noqa: BLE001
        # Delete the just-written archive so a corrupt one never sits on
        # disk looking valid.  The next operator who comes to investigate
        # won't find a misleading green-looking artifact.
        if archive.exists():
            shutil.rmtree(archive, ignore_errors=True)
            logger.error(
                f"setup_and_archive: deleted corrupt archive at {archive} "
                f"after round-trip failure."
            )
        raise PairFailure(
            f"round-trip check FAILED: {exc}\n"
            "The swap manifest in eval/artifact_swap.py is incomplete or "
            "buggy; review SWAP_FILES / SWAP_DIRS before setting up more "
            "graphs."
        ) from exc

    logger.info(f"setup_and_archive: ✓ {dataset}__{graph} archived at {archive}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry
# ──────────────────────────────────────────────────────────────────────────────

_LEGACY_CLI_ERROR = (
    "[setup_and_archive] ERROR: positional CLI args have been removed.\n"
    "\n"
    "  Old:  python scripts/setup_and_archive.py <dataset> <graph> [flags]\n"
    "  New:  python scripts/setup_and_archive.py        # no arguments\n"
    "\n"
    "The script now reads eval_config.EVAL_PAIRS as the single source of\n"
    "truth and processes every listed pair in order. To set up a single\n"
    "pair, edit eval_config.py and shrink EVAL_PAIRS to that one pair,\n"
    "then re-run with no arguments.\n"
    "\n"
    "This change exists so eval_config.py and the CLI can never disagree.\n"
)


def _reject_legacy_cli(argv: List[str]) -> None:
    """Hard-fail if any positional / flag args are passed."""
    # argv[0] is the script name; anything beyond is the legacy interface.
    if len(argv) > 1:
        print(_LEGACY_CLI_ERROR, file=sys.stderr)
        sys.exit(2)


def _print_summary(
    pairs: List[Tuple[str, str]],
    completed: List[Tuple[str, str]],
    failed: Tuple[str, str, str] | None,
) -> None:
    """
    Print a per-pair summary in the ``eval_run.py`` style.

    Fail-fast: every pair is one of three states — ``✓`` done,
    ``✗`` failed, or ``·`` skipped (because the run aborted at the
    failing pair before reaching this one).
    """
    print("\n══ setup_and_archive summary ══")
    completed_set = set(completed)
    failed_pair = (failed[0], failed[1]) if failed else None

    aborted = False
    for ds, gr in pairs:
        if (ds, gr) in completed_set:
            print(f"  ✓ {ds}__{gr}")
        elif failed_pair == (ds, gr):
            reason = failed[2].splitlines()[0] if failed else ""
            print(f"  ✗ {ds}__{gr}  ({reason})")
            aborted = True
        elif aborted:
            print(f"  · {ds}__{gr}  (skipped — early abort)")


def _print_retry_block(
    pairs: List[Tuple[str, str]],
    completed: List[Tuple[str, str]],
) -> None:
    """
    Print a copy-pasteable ``EVAL_PAIRS`` retry block listing every
    pair that did NOT successfully complete this run — i.e. the failed
    pair plus everything skipped after it.

    If everything succeeded, print the no-retry-needed comment instead.
    Format matches the canonical ``eval_config.py`` declaration so the
    operator can paste the block directly into that file and resume.
    """
    completed_set = set(completed)
    retry: List[Tuple[str, str]] = [p for p in pairs if p not in completed_set]

    print("\n══ retry block (paste into eval_config.py) ══\n")
    if not retry:
        print("# all pairs succeeded — no retry block needed")
        return
    print("EVAL_PAIRS: list[tuple[str, str]] = [")
    # Right-pad the dataset string so all graph strings line up — same
    # visual style as the existing eval_config.py block.
    width = max(len(ds) for ds, _ in retry) + 3  # 2 quotes + comma
    for ds, gr in retry:
        ds_part = f'"{ds}",'
        print(f'    ({ds_part:<{width + 1}} "{gr}"),')
    print("]")


def main(argv: List[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    _reject_legacy_cli(argv)

    pairs: List[Tuple[str, str]] = list(getattr(cfg, "EVAL_PAIRS", []) or [])
    if not pairs:
        print(
            "[setup_and_archive] ERROR: eval_config.EVAL_PAIRS is empty — "
            "nothing to do.\n"
            "Edit eval_config.py and add the pairs you want to set up, "
            "then re-run.",
            file=sys.stderr,
        )
        return 1

    completed: List[Tuple[str, str]] = []
    failed: Tuple[str, str, str] | None = None  # (dataset, graph, message)

    for dataset, graph in pairs:
        # ── Pre-pair wipe ──────────────────────────────────────────────
        wipe_live_state()
        # ── Run the pair, with guaranteed post-pair wipe ───────────────
        try:
            try:
                _run_one_pair(dataset, graph)
            except PairFailure as exc:
                failed = (dataset, graph, str(exc))
                logger.error(f"setup_and_archive: ✗ {dataset}__{graph}: {exc}")
            except Exception as exc:  # noqa: BLE001 — defensive
                failed = (dataset, graph, f"unexpected error: {exc}")
                logger.error(
                    f"setup_and_archive: ✗ {dataset}__{graph}: unexpected "
                    f"error: {exc}"
                )
            else:
                completed.append((dataset, graph))
        finally:
            # ALWAYS run the post-pair wipe, even on failure, so the
            # working tree is left clean for the next operator.
            wipe_live_state()

        # ── Fail-fast: abort the whole run on the first failure ────────
        if failed is not None:
            break

    _print_summary(pairs, completed, failed)
    _print_retry_block(pairs, completed)

    if failed is not None:
        ds, gr, _msg = failed
        print(
            f"\n[setup_and_archive] aborted after failure in {ds}__{gr}; "
            f"see retry block above to resume.",
            file=sys.stderr,
        )
        return 2

    print(
        f"\n[setup_and_archive] ✓ all {len(completed)} pair(s) archived "
        f"successfully."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
