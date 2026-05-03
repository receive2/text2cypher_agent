# -*- coding: utf-8 -*-
"""
tests/test_setup_and_archive.py
================================
Offline regression tests for ``scripts/setup_and_archive.py``.

Covers
------
1. Legacy CLI rejection — positional args fail loudly.
2. ``wipe_live_state`` —
   - wipes every manifest file/dir from ``eval.artifact_swap``
   - wipes the ``.current_setup`` sentinel
   - wipes ``__pycache__`` dirs and ``*.swap.tmp`` / ``*.swap.old`` siblings
   - resets ``EMBEDDABLE_PROPERTIES`` to ``[]``
   - wipes ``vector_config.py.bak`` AFTER the reset, not before
3. Fail-fast main loop — pair 2 fails → pair 1 ✓, pair 2 ✗, pair 3 · skipped.
4. Retry block — lists failed + every skipped pair (fail-fast).
5. Retry block — prints the no-retry-needed comment on full success.
6. ``_reset_neo4j_embeddings`` — discovery + drop + null + identity logging.
7. ``_run_one_pair`` — calls ``_reset_neo4j_embeddings`` before
   ``setup_project.py`` subprocess.
8. Round-trip failure — deletes the just-written archive directory.
9. Subprocess failure — does NOT call ``archive_current``.

All tests are offline:
  * ``setup_project.py`` subprocess is monkeypatched on
    ``subprocess.run``.
  * Neo4j driver is monkeypatched with ``_FakeDriver`` /
    ``_FakeSession`` / ``_FakeResult`` doubles.
  * ``_REPO_ROOT`` is redirected under ``tmp_path`` so the real on-disk
    repo files are never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pytest

# ── Repo-root import bootstrap ───────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# Neo4j driver/session fakes
# ──────────────────────────────────────────────────────────────────────────────

class _FakeResult:
    """Minimal stand-in for a Neo4j Result object."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def consume(self) -> None:
        return None


class _FakeSession:
    """
    Records every cypher executed plus returns canned rows for the schema
    introspection / SHOW VECTOR INDEXES queries.
    """

    def __init__(
        self,
        *,
        node_rows: List[Dict[str, Any]] | None = None,
        rel_rows:  List[Dict[str, Any]] | None = None,
        index_names: List[str] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.node_rows   = node_rows   or []
        self.rel_rows    = rel_rows    or []
        self.index_names = index_names or []
        self.fail_on     = fail_on
        self.queries: List[str] = []

    # Context-manager protocol — driver.session(...) is a CM in real neo4j
    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run(self, query: str, *args, **kwargs) -> _FakeResult:
        self.queries.append(query)
        if self.fail_on and self.fail_on in query:
            raise RuntimeError(f"fake driver: forced failure on {self.fail_on!r}")
        if "db.schema.nodeTypeProperties" in query:
            return _FakeResult(self.node_rows)
        if "db.schema.relTypeProperties" in query:
            return _FakeResult(self.rel_rows)
        if "SHOW VECTOR INDEXES" in query:
            return _FakeResult([{"name": n} for n in self.index_names])
        # All MATCH/CALL { ... }/DROP INDEX statements just succeed quietly.
        return _FakeResult([])


class _FakeDriver:
    """
    Stand-in for a ``neo4j.GraphDatabase.driver(...)`` return value.

    The session(...) call is recorded so tests can assert on the database
    arg.  Sessions are pre-built per test by the fixture; close() is a
    no-op record.
    """

    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.session_calls: List[Dict[str, Any]] = []
        self.closed = False

    def session(self, *, database: str | None = None, **kwargs) -> _FakeSession:
        self.session_calls.append({"database": database, **kwargs})
        return self._session

    def close(self) -> None:
        self.closed = True


# ──────────────────────────────────────────────────────────────────────────────
# Sandbox fixture
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def _sandbox(tmp_path, monkeypatch):
    """
    Build a sandboxed copy of every path ``setup_and_archive`` interacts
    with under ``tmp_path``, then redirect ``_REPO_ROOT`` to point at it.

    Yields a dict with ``module``, ``root``, plus helper functions for
    asserting on the on-disk state.
    """
    import scripts.setup_and_archive as sa

    root = tmp_path / "repo"
    root.mkdir()

    # Recreate the manifest layout under the sandbox so the wipe primitives
    # have something to delete.
    (root / "schema_data").mkdir()
    (root / "generated").mkdir()
    (root / "agent").mkdir()
    (root / "generated" / "faiss").mkdir()

    # Manifest files (must match eval/artifact_swap.SWAP_FILES).
    for rel in [
        "schema_data/schema_nodes.csv",
        "schema_data/schema_relations.csv",
        "schema_data/schema_meta.json",
        "generated/generated_node_tools.py",
        "generated/generated_rel_tools.py",
        "agent/prompts.py",
        "generated/tool_descriptions.csv",  # OPTIONAL
    ]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")

    # Manifest dirs.
    (root / "generated" / "faiss" / "tools_auto").mkdir(parents=True)
    (root / "generated" / "faiss" / "tools_auto" / "index.faiss").write_bytes(b"x")
    (root / "generated" / "faiss" / "tools_auto_node_only").mkdir(parents=True)
    (root / "generated" / "faiss" / "tools_auto_node_only" / "index.faiss").write_bytes(b"x")

    # Sentinel.
    (root / ".current_setup").write_text("dataset__graph", encoding="utf-8")

    # __pycache__ dirs.
    (root / "generated" / "__pycache__").mkdir()
    (root / "generated" / "__pycache__" / "x.pyc").write_bytes(b"x")
    (root / "agent" / "__pycache__").mkdir()
    (root / "agent" / "__pycache__" / "y.pyc").write_bytes(b"y")

    # Swap leftovers.
    (root / "schema_data" / "schema_nodes.csv.swap.tmp").write_text("tmp\n")
    (root / "agent" / "prompts.py.swap.old").write_text("old\n")

    # Stale .bak left behind from a prior run.
    (root / "vector_config.py.bak").write_text("# stale bak\n", encoding="utf-8")

    # vector_config.py with a real EMBEDDABLE_PROPERTIES block so
    # _reset_embeddable_properties_block has something to rewrite.
    vc_text = (
        "# fake vector_config\n"
        "EMBEDDABLE_PROPERTIES = [\n"
        "    {\n"
        '        "entity_type":        "node",\n'
        '        "label":              "Movie",\n'
        '        "property":           "title",\n'
        '        "embedding_property": "title_embedding",\n'
        "    },\n"
        "]\n"
        "EMBEDDING_BACKEND = 'openai'\n"
        "EMBEDDING_MODEL_NAME = 'text-embedding-3-small'\n"
        "EMBEDDING_DIMENSIONS = 1536\n"
        "RESET_TX_BATCH_SIZE = 5000\n"
    )
    (root / "vector_config.py").write_text(vc_text, encoding="utf-8")

    # Redirect the module's repo-root anchor.
    monkeypatch.setattr(sa, "_REPO_ROOT", root, raising=False)

    return {
        "module": sa,
        "root":   root,
        "vc":     root / "vector_config.py",
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. Legacy CLI rejection
# ──────────────────────────────────────────────────────────────────────────────

def test_legacy_cli_rejects_positional_args(_sandbox, capsys) -> None:
    """``setup_and_archive.py movies actor`` must hard-fail."""
    sa = _sandbox["module"]

    with pytest.raises(SystemExit) as excinfo:
        sa.main(["setup_and_archive.py", "movies", "actor"])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "positional CLI args have been removed" in err
    assert "no arguments" in err


def test_legacy_cli_rejects_single_positional(_sandbox, capsys) -> None:
    """A single trailing arg also trips the rejection."""
    sa = _sandbox["module"]

    with pytest.raises(SystemExit) as excinfo:
        sa.main(["setup_and_archive.py", "movies"])

    assert excinfo.value.code == 2


# ──────────────────────────────────────────────────────────────────────────────
# 2. wipe_live_state behaviour
# ──────────────────────────────────────────────────────────────────────────────

def _all_manifest_paths(root: Path) -> Tuple[List[Path], List[Path]]:
    """Return (files, dirs) the wipe is supposed to delete."""
    from eval import artifact_swap
    files = [root / r for r in (list(artifact_swap.SWAP_FILES)
                                + list(artifact_swap.SWAP_FILES_OPTIONAL))]
    dirs  = [root / r for r in (list(artifact_swap.SWAP_DIRS)
                                + list(artifact_swap.SWAP_DIRS_OPTIONAL))]
    return files, dirs


def test_wipe_removes_all_manifest_files_and_dirs(_sandbox) -> None:
    """Every SWAP_FILES / SWAP_FILES_OPTIONAL / SWAP_DIRS entry vanishes."""
    sa   = _sandbox["module"]
    root = _sandbox["root"]

    files, dirs = _all_manifest_paths(root)
    for p in files:
        assert p.is_file(), f"precondition: {p} should exist"
    for p in dirs:
        assert p.is_dir(), f"precondition: {p} should exist"

    sa.wipe_live_state()

    for p in files:
        assert not p.exists(), f"manifest file not wiped: {p}"
    for p in dirs:
        assert not p.exists(), f"manifest dir not wiped: {p}"


def test_wipe_removes_sentinel_and_pycache(_sandbox) -> None:
    sa   = _sandbox["module"]
    root = _sandbox["root"]

    sa.wipe_live_state()

    assert not (root / ".current_setup").exists()
    assert not (root / "generated" / "__pycache__").exists()
    assert not (root / "agent"     / "__pycache__").exists()


def test_wipe_removes_swap_leftovers(_sandbox) -> None:
    sa   = _sandbox["module"]
    root = _sandbox["root"]

    sa.wipe_live_state()

    assert not (root / "schema_data" / "schema_nodes.csv.swap.tmp").exists()
    assert not (root / "agent"       / "prompts.py.swap.old").exists()


def test_wipe_resets_embeddable_properties_block(_sandbox) -> None:
    sa = _sandbox["module"]
    vc = _sandbox["vc"]

    sa.wipe_live_state()

    body = vc.read_text(encoding="utf-8")
    assert "EMBEDDABLE_PROPERTIES = []" in body
    # Make sure no stale entries survived.
    assert '"label": "Movie"' not in body
    assert '"property": "title"' not in body


def test_wipe_removes_bak_AFTER_reset(_sandbox) -> None:
    """
    The reset re-creates ``vector_config.py.bak`` (via
    ``_vector_config_io._backup``).  The wipe MUST run the .bak deletion
    AFTER the reset, otherwise the .bak the reset wrote sits around.

    This test plants a sentinel string into the existing .bak and
    asserts the .bak does not exist after the wipe — neither the stale
    one nor the reset's freshly-written one.
    """
    sa   = _sandbox["module"]
    root = _sandbox["root"]
    bak  = root / "vector_config.py.bak"
    bak.write_text("STALE_BAK_SENTINEL\n", encoding="utf-8")

    sa.wipe_live_state()

    assert not bak.exists(), (
        "vector_config.py.bak must be wiped AFTER the EMBEDDABLE_PROPERTIES "
        "reset; otherwise the .bak the reset just wrote leaks into the "
        "next pair."
    )


def test_wipe_handles_already_clean_tree(_sandbox) -> None:
    """Calling wipe twice in a row is idempotent — the second call no-ops."""
    sa = _sandbox["module"]

    sa.wipe_live_state()
    # Should not raise even though everything is already gone.
    sa.wipe_live_state()


# ──────────────────────────────────────────────────────────────────────────────
# 3. Fail-fast main loop
# ──────────────────────────────────────────────────────────────────────────────

def test_main_fail_fast_aborts_after_first_failure(_sandbox, monkeypatch, capsys) -> None:
    """
    Three pairs.  Pair 2 raises PairFailure.  Expect:
      * pair 1 ✓
      * pair 2 ✗
      * pair 3 ·skipped (never executed)
      * exit code 2
    """
    sa = _sandbox["module"]

    pairs = [("ds", "g1"), ("ds", "g2"), ("ds", "g3")]
    monkeypatch.setattr(sa.cfg, "EVAL_PAIRS", pairs, raising=False)

    executed: List[Tuple[str, str]] = []

    def fake_run_one_pair(dataset: str, graph: str) -> None:
        executed.append((dataset, graph))
        if graph == "g2":
            raise sa.PairFailure("simulated pair-2 failure")

    monkeypatch.setattr(sa, "_run_one_pair", fake_run_one_pair)

    rc = sa.main(["setup_and_archive.py"])
    assert rc == 2

    # _run_one_pair invoked for g1 + g2 only — g3 was skipped.
    assert executed == [("ds", "g1"), ("ds", "g2")]

    out = capsys.readouterr().out
    assert "✓ ds__g1" in out
    assert "✗ ds__g2" in out
    assert "· ds__g3" in out and "skipped" in out


def test_main_full_success_returns_zero(_sandbox, monkeypatch, capsys) -> None:
    sa = _sandbox["module"]

    pairs = [("ds", "g1"), ("ds", "g2")]
    monkeypatch.setattr(sa.cfg, "EVAL_PAIRS", pairs, raising=False)
    monkeypatch.setattr(sa, "_run_one_pair", lambda *a, **kw: None)

    rc = sa.main(["setup_and_archive.py"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "✓ ds__g1" in out
    assert "✓ ds__g2" in out
    assert "all 2 pair(s) archived successfully" in out


def test_main_empty_eval_pairs_returns_one(_sandbox, monkeypatch, capsys) -> None:
    sa = _sandbox["module"]
    monkeypatch.setattr(sa.cfg, "EVAL_PAIRS", [], raising=False)

    rc = sa.main(["setup_and_archive.py"])
    assert rc == 1

    err = capsys.readouterr().err
    assert "EVAL_PAIRS is empty" in err


def test_main_post_pair_wipe_runs_even_on_failure(_sandbox, monkeypatch) -> None:
    """The post-pair wipe must run inside ``finally``, not be skipped."""
    sa = _sandbox["module"]

    pairs = [("ds", "g1")]
    monkeypatch.setattr(sa.cfg, "EVAL_PAIRS", pairs, raising=False)

    wipes: List[None] = []
    real_wipe = sa.wipe_live_state

    def counting_wipe() -> None:
        wipes.append(None)
        real_wipe()

    monkeypatch.setattr(sa, "wipe_live_state", counting_wipe)

    def boom(*a, **kw):
        raise sa.PairFailure("kaboom")

    monkeypatch.setattr(sa, "_run_one_pair", boom)

    rc = sa.main(["setup_and_archive.py"])
    assert rc == 2
    # Pre-pair wipe + post-pair wipe == 2.
    assert len(wipes) == 2


# ──────────────────────────────────────────────────────────────────────────────
# 4. Retry block
# ──────────────────────────────────────────────────────────────────────────────

def test_retry_block_lists_failed_and_skipped(_sandbox, monkeypatch, capsys) -> None:
    sa = _sandbox["module"]

    pairs = [("ds", "g1"), ("ds", "g2"), ("ds", "g3"), ("ds", "g4")]
    monkeypatch.setattr(sa.cfg, "EVAL_PAIRS", pairs, raising=False)

    def fake(dataset: str, graph: str) -> None:
        if graph == "g2":
            raise sa.PairFailure("nope")

    monkeypatch.setattr(sa, "_run_one_pair", fake)

    sa.main(["setup_and_archive.py"])

    out = capsys.readouterr().out
    assert "retry block (paste into eval_config.py)" in out
    assert "EVAL_PAIRS: list[tuple[str, str]] = [" in out
    # Failed pair (g2) AND every skipped pair (g3, g4) — but NOT g1.
    assert '"g2"' in out
    assert '"g3"' in out
    assert '"g4"' in out
    # g1 was completed; must not appear in the retry block proper.
    # Find the substring after "retry block" header to scope the assert.
    retry_section = out.split("retry block (paste into eval_config.py)", 1)[1]
    assert '"g1"' not in retry_section


def test_retry_block_says_no_retry_needed_on_full_success(_sandbox, monkeypatch, capsys) -> None:
    sa = _sandbox["module"]

    pairs = [("ds", "g1"), ("ds", "g2")]
    monkeypatch.setattr(sa.cfg, "EVAL_PAIRS", pairs, raising=False)
    monkeypatch.setattr(sa, "_run_one_pair", lambda *a, **kw: None)

    sa.main(["setup_and_archive.py"])

    out = capsys.readouterr().out
    assert "all pairs succeeded — no retry block needed" in out
    # Make sure we did NOT print an empty retry block list either.
    assert "EVAL_PAIRS: list[tuple[str, str]] = [" not in out


# ──────────────────────────────────────────────────────────────────────────────
# 5. _reset_neo4j_embeddings — discovery + drop + null
# ──────────────────────────────────────────────────────────────────────────────

def _make_conn(uri: str = "bolt://test:7687", database: str = "neo4j"):
    """Build a stand-in ``GraphConn`` (any object with attrs works)."""
    class _C:
        pass
    c = _C()
    c.uri      = uri
    c.user     = "neo4j"
    c.password = "x"
    c.database = database
    return c


def _patch_neo4j_driver(monkeypatch, fake_session: _FakeSession) -> _FakeDriver:
    """Replace ``neo4j.GraphDatabase.driver`` with a constructor that returns
    a ``_FakeDriver`` wrapping *fake_session*."""
    fake_driver = _FakeDriver(fake_session)

    class _FakeGraphDatabase:
        @staticmethod
        def driver(uri, auth=None, **kwargs):
            fake_driver.last_uri  = uri
            fake_driver.last_auth = auth
            return fake_driver

    # Inject a fake `neo4j` module exposing GraphDatabase.
    import types
    fake_neo4j = types.ModuleType("neo4j")
    fake_neo4j.GraphDatabase = _FakeGraphDatabase
    monkeypatch.setitem(sys.modules, "neo4j", fake_neo4j)
    return fake_driver


def test_reset_neo4j_embeddings_discovers_and_nulls(_sandbox, monkeypatch) -> None:
    sa = _sandbox["module"]

    session = _FakeSession(
        node_rows=[
            # By name (layer 3)
            {"nodeLabels": ["Movie"],  "propertyName": "title_embedding",
             "propertyTypes": ["LIST<FLOAT>"]},
            # By type (layer 1) — name doesn't match
            {"nodeLabels": ["Person"], "propertyName": "weird_blob",
             "propertyTypes": ["LIST<FLOAT64>"]},
            # Plain text — must NOT be touched
            {"nodeLabels": ["Movie"],  "propertyName": "title",
             "propertyTypes": ["String"]},
            # propertyName None — defensive skip
            {"nodeLabels": ["Movie"],  "propertyName": None,
             "propertyTypes": ["LIST<FLOAT>"]},
        ],
        rel_rows=[
            {"relType": ":`ACTED_IN`", "propertyName": "roles_vector",
             "propertyTypes": ["LIST<DOUBLE>"]},
            {"relType": ":`REVIEWED`", "propertyName": "summary",
             "propertyTypes": ["String"]},
        ],
        index_names=["movie_title_emb_idx", "actedin_roles_vec_idx"],
    )
    fake_driver = _patch_neo4j_driver(monkeypatch, session)

    conn = _make_conn(uri="bolt://X:7687", database="movies_test")

    sa._reset_neo4j_embeddings(conn)

    # Driver was opened with the right URI/auth and closed.
    assert fake_driver.last_uri == "bolt://X:7687"
    assert fake_driver.last_auth == ("neo4j", "x")
    assert fake_driver.closed is True
    assert fake_driver.session_calls[0]["database"] == "movies_test"

    qs = session.queries

    # Discovery queries fired.
    assert any("db.schema.nodeTypeProperties" in q for q in qs)
    assert any("db.schema.relTypeProperties"  in q for q in qs)
    assert any("SHOW VECTOR INDEXES"          in q for q in qs)

    # Both vector indexes were dropped.
    assert any("DROP INDEX `movie_title_emb_idx`" in q for q in qs)
    assert any("DROP INDEX `actedin_roles_vec_idx`" in q for q in qs)

    # Embedding properties are nulled — by-name AND by-type.
    assert any(
        "MATCH (n:`Movie`)" in q and "REMOVE n.`title_embedding`" in q
        for q in qs
    )
    assert any(
        "MATCH (n:`Person`)" in q and "REMOVE n.`weird_blob`" in q
        for q in qs
    )
    # Rel embedding nulled — backticks stripped from relType.
    assert any(
        "MATCH ()-[r:`ACTED_IN`]->()" in q and "REMOVE r.`roles_vector`" in q
        for q in qs
    )

    # Plain text props are NOT nulled.
    assert not any("REMOVE n.`title`"  in q and "title_embedding" not in q for q in qs)
    assert not any("REMOVE r.`summary`" in q for q in qs)


def test_reset_neo4j_embeddings_uses_RESET_TX_BATCH_SIZE(_sandbox, monkeypatch) -> None:
    sa = _sandbox["module"]

    session = _FakeSession(
        node_rows=[
            {"nodeLabels": ["Movie"], "propertyName": "title_embedding",
             "propertyTypes": ["LIST<FLOAT>"]},
        ],
        rel_rows=[],
        index_names=[],
    )
    _patch_neo4j_driver(monkeypatch, session)

    # Bump the chunk size in the live config so the test sees the override.
    import vector_config
    monkeypatch.setattr(vector_config, "RESET_TX_BATCH_SIZE", 4242, raising=False)

    sa._reset_neo4j_embeddings(_make_conn())

    null_q = next(q for q in session.queries if "REMOVE n." in q)
    assert "IN TRANSACTIONS OF 4242 ROWS" in null_q


def test_reset_neo4j_embeddings_wraps_drop_failure_as_PairFailure(_sandbox, monkeypatch) -> None:
    sa = _sandbox["module"]

    session = _FakeSession(
        node_rows=[],
        rel_rows=[],
        index_names=["bad_index"],
        fail_on="DROP INDEX",
    )
    _patch_neo4j_driver(monkeypatch, session)

    with pytest.raises(sa.PairFailure) as excinfo:
        sa._reset_neo4j_embeddings(_make_conn())
    assert "bad_index" in str(excinfo.value)


def test_reset_neo4j_embeddings_logs_identity(_sandbox, monkeypatch, caplog) -> None:
    """The reset logs backend / model / dim before doing any work."""
    sa = _sandbox["module"]

    session = _FakeSession(node_rows=[], rel_rows=[], index_names=[])
    _patch_neo4j_driver(monkeypatch, session)

    # loguru → standard logging bridge
    from loguru import logger as _lg
    handler_id = _lg.add(lambda msg: caplog.records.append(
        type("R", (), {"getMessage": lambda self, m=str(msg): m, "msg": str(msg)})()
    ), level="INFO")
    try:
        sa._reset_neo4j_embeddings(_make_conn())
    finally:
        _lg.remove(handler_id)

    msgs = " ".join(r.msg for r in caplog.records)
    # We expect backend / model / dim / target to appear in the identity log.
    assert "backend=" in msgs
    assert "model="   in msgs
    assert "dim="     in msgs
    assert "target="  in msgs


# ──────────────────────────────────────────────────────────────────────────────
# 6. _run_one_pair orchestration
# ──────────────────────────────────────────────────────────────────────────────

def test_run_one_pair_calls_reset_BEFORE_subprocess(_sandbox, monkeypatch) -> None:
    sa = _sandbox["module"]

    order: List[str] = []
    monkeypatch.setattr(
        sa.cfg, "conn_for",
        lambda ds, gr: _make_conn(uri="bolt://x:7687", database="d"),
        raising=False,
    )
    monkeypatch.setattr(
        sa, "_reset_neo4j_embeddings",
        lambda conn: order.append("reset"),
    )

    class _Proc:
        returncode = 0

    def fake_subproc(*a, **kw):
        order.append("setup_project")
        return _Proc()

    monkeypatch.setattr(sa.subprocess, "run", fake_subproc)
    monkeypatch.setattr(sa, "archive_current",   lambda *a, **kw: order.append("archive"))
    monkeypatch.setattr(sa, "round_trip_check",  lambda *a, **kw: order.append("rtc"))
    monkeypatch.setattr(sa, "archive_dir_for",   lambda ds, gr: _sandbox["root"] / f"{ds}__{gr}")

    sa._run_one_pair("ds", "g1")
    assert order == ["reset", "setup_project", "archive", "rtc"]


def test_run_one_pair_subprocess_failure_skips_archive(_sandbox, monkeypatch) -> None:
    sa = _sandbox["module"]

    monkeypatch.setattr(
        sa.cfg, "conn_for",
        lambda ds, gr: _make_conn(),
        raising=False,
    )
    monkeypatch.setattr(sa, "_reset_neo4j_embeddings", lambda conn: None)

    class _Proc:
        returncode = 17

    monkeypatch.setattr(sa.subprocess, "run", lambda *a, **kw: _Proc())

    archive_called: List[bool] = []
    monkeypatch.setattr(
        sa, "archive_current",
        lambda *a, **kw: archive_called.append(True),
    )
    monkeypatch.setattr(sa, "round_trip_check", lambda *a, **kw: None)
    monkeypatch.setattr(sa, "archive_dir_for", lambda ds, gr: _sandbox["root"] / "x")

    with pytest.raises(sa.PairFailure) as excinfo:
        sa._run_one_pair("ds", "g1")

    assert "exited with code 17" in str(excinfo.value)
    assert not archive_called, "archive_current must not be called after subprocess failure"


def test_run_one_pair_round_trip_failure_deletes_archive(_sandbox, monkeypatch) -> None:
    sa = _sandbox["module"]

    archive_dir = _sandbox["root"] / "ds__g1_archive"
    archive_dir.mkdir()
    (archive_dir / "marker.txt").write_text("contents")

    monkeypatch.setattr(sa.cfg, "conn_for",
                        lambda ds, gr: _make_conn(), raising=False)
    monkeypatch.setattr(sa, "_reset_neo4j_embeddings", lambda conn: None)

    class _Proc:
        returncode = 0

    monkeypatch.setattr(sa.subprocess, "run", lambda *a, **kw: _Proc())
    monkeypatch.setattr(sa, "archive_current", lambda *a, **kw: None)
    monkeypatch.setattr(sa, "archive_dir_for", lambda ds, gr: archive_dir)

    def boom(*a, **kw):
        raise RuntimeError("manifest mismatch")

    monkeypatch.setattr(sa, "round_trip_check", boom)

    with pytest.raises(sa.PairFailure) as excinfo:
        sa._run_one_pair("ds", "g1")
    assert "round-trip check FAILED" in str(excinfo.value)

    # The archive must have been deleted to prevent a corrupt artifact
    # sitting on disk looking valid.
    assert not archive_dir.exists(), (
        "round-trip failure must delete the just-written archive directory"
    )


def test_run_one_pair_missing_GraphConn_raises_PairFailure(_sandbox, monkeypatch) -> None:
    sa = _sandbox["module"]

    def fake_conn_for(ds, gr):
        raise KeyError(f"no conn for ({ds!r}, {gr!r})")

    monkeypatch.setattr(sa.cfg, "conn_for", fake_conn_for, raising=False)

    with pytest.raises(sa.PairFailure) as excinfo:
        sa._run_one_pair("ds", "ghost")
    assert "no GraphConn registered" in str(excinfo.value)


# ──────────────────────────────────────────────────────────────────────────────
# 7. End-to-end fail-fast invariant: reset is called once per attempted pair
# ──────────────────────────────────────────────────────────────────────────────

def test_main_invokes_reset_for_each_attempted_pair(_sandbox, monkeypatch) -> None:
    """
    Three pairs, the second blows up.  ``_reset_neo4j_embeddings`` should
    have been called exactly twice (g1 succeeds, g2 fails) and the third
    pair must NOT trigger a reset because of fail-fast.
    """
    sa = _sandbox["module"]

    pairs = [("ds", "g1"), ("ds", "g2"), ("ds", "g3")]
    monkeypatch.setattr(sa.cfg, "EVAL_PAIRS", pairs, raising=False)

    monkeypatch.setattr(sa.cfg, "conn_for",
                        lambda ds, gr: _make_conn(database=gr), raising=False)

    reset_calls: List[str] = []

    def fake_reset(conn) -> None:
        reset_calls.append(conn.database)
        if conn.database == "g2":
            raise sa.PairFailure("reset blew up on g2")

    monkeypatch.setattr(sa, "_reset_neo4j_embeddings", fake_reset)

    # Stub everything past the reset so a successful pair completes.
    class _Proc:
        returncode = 0

    monkeypatch.setattr(sa.subprocess, "run", lambda *a, **kw: _Proc())
    monkeypatch.setattr(sa, "archive_current",  lambda *a, **kw: None)
    monkeypatch.setattr(sa, "round_trip_check", lambda *a, **kw: None)
    monkeypatch.setattr(sa, "archive_dir_for",  lambda ds, gr: _sandbox["root"] / f"{ds}__{gr}")

    rc = sa.main(["setup_and_archive.py"])
    assert rc == 2
    assert reset_calls == ["g1", "g2"], (
        f"reset should run for g1+g2 only (fail-fast); got {reset_calls!r}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
