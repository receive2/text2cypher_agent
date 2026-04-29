"""
Regression tests for setup_project.py robustness invariants.

Covers:
  - Embedding columns are never promoted to fulltext-search @tools
    (gen_tools._drop_embedding_pairs).
  - FAISS rebuild is a clean operation — no orphan files survive.
  - FAISS index is never silently reused against a mismatched env
    (fingerprint guard).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict

import pytest

# Make the repo root importable when this test is executed from the tests/ dir.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from paths import GENERATED_NODE_TOOLS  # noqa: E402
from tools.gen_tools import (  # noqa: E402
    _drop_embedding_pairs,
    _label_snake,
    _prop_snake,
)
from vector_config import EMBEDDABLE_PROPERTIES  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_generated_node_tools() -> str:
    """Return the contents of ``generated/generated_node_tools.py``.

    Skips (rather than fails) when the file has not been generated yet so
    this test stays useful in environments without a live Neo4j instance.
    """
    path = Path(GENERATED_NODE_TOOLS)
    if not path.exists():
        pytest.skip(
            f"{path} not found — run `python setup_project.py --skip-embeddings` "
            "to regenerate before running this test."
        )
    return path.read_text(encoding="utf-8")


# ── 1. No tool name ends in _embedding / _vector ────────────────────────────

def test_no_embedding_or_vector_suffix_in_generated_node_tools() -> None:
    """``generated_node_tools.py`` must not contain ``def get_*_(embedding|vector)``."""
    src = _read_generated_node_tools()
    leaked = re.findall(
        r"^def\s+(get_\w+_(?:embedding|vector))\s*\(",
        src,
        flags=re.MULTILINE,
    )
    assert not leaked, (
        f"Embedding/vector @tool functions leaked into "
        f"generated/generated_node_tools.py: {leaked}"
    )


# ── 2. Every EMBEDDABLE_PROPERTIES entry is absent from generated tools ─────

def test_no_embeddable_property_was_promoted_to_tool() -> None:
    """For every ``EMBEDDABLE_PROPERTIES`` node entry, the corresponding
    ``get_<label>_<embedding_property>`` function must NOT exist in the
    generated module."""
    src = _read_generated_node_tools()

    leaked: list[str] = []
    for entry in EMBEDDABLE_PROPERTIES:
        if entry.get("entity_type") != "node":
            continue
        label = entry["label"]
        emb_prop = entry["embedding_property"]
        func_name = f"get_{_label_snake(label)}_{_prop_snake(emb_prop)}"
        if re.search(
            rf"^def\s+{re.escape(func_name)}\s*\(",
            src,
            flags=re.MULTILINE,
        ):
            leaked.append(func_name)

    assert not leaked, (
        f"EMBEDDABLE_PROPERTIES entries leaked into generated_node_tools.py "
        f"as @tool functions: {leaked}"
    )


# ── 3. Unit test on _drop_embedding_pairs (no live Neo4j needed) ────────────

def test_drop_embedding_pairs_removes_all_three_layers() -> None:
    """Feed a synthetic pair list through ``_drop_embedding_pairs`` and
    confirm that each of the three filter layers fires."""
    triples = [
        # Plain text properties — must survive
        ("Movie", "title", ["String"]),
        ("Movie", "tagline", ["String"]),
        ("Person", "name", ["String"]),
        ("Person", "born", ["Long"]),

        # Layer 1 — type-based: floating-point list, regardless of name
        ("Foo", "weird_blob", ["LIST<FLOAT>"]),
        ("Foo", "another_blob", ["LIST<FLOAT64>"]),

        # Layer 2 — config-based: registered in EMBEDDABLE_PROPERTIES.
        # (At least one of these is guaranteed to exist in the demo config.)
        ("Movie", "title_embedding", ["String"]),  # bad type label, still caught

        # Layer 3 — naming-based: name suffix
        ("Bar", "summary_embedding", None),
        ("Bar", "summary_vector", None),
    ]

    out = _drop_embedding_pairs(triples, entity_type="node")

    # Survivors
    assert ("Movie", "title") in out
    assert ("Movie", "tagline") in out
    assert ("Person", "name") in out
    assert ("Person", "born") in out

    # Layer 1: floating-point list types are dropped
    assert ("Foo", "weird_blob") not in out
    assert ("Foo", "another_blob") not in out

    # Layer 2: EMBEDDABLE_PROPERTIES match drops the pair even when the
    # propertyTypes is incorrect / missing
    assert ("Movie", "title_embedding") not in out

    # Layer 3: name suffix
    assert ("Bar", "summary_embedding") not in out
    assert ("Bar", "summary_vector") not in out


def test_drop_embedding_pairs_preserves_input_order() -> None:
    """Filtering must preserve the relative order of surviving pairs."""
    triples = [
        ("Movie", "title", ["String"]),
        ("Movie", "title_embedding", ["LIST<FLOAT>"]),
        ("Movie", "tagline", ["String"]),
        ("Person", "name", ["String"]),
        ("Person", "name_embedding", ["LIST<FLOAT>"]),
    ]
    out = _drop_embedding_pairs(triples, entity_type="node")
    assert out == [
        ("Movie", "title"),
        ("Movie", "tagline"),
        ("Person", "name"),
    ]


def test_drop_embedding_pairs_relationship_entity_type() -> None:
    """The ``relationship`` entity_type path must apply the same three layers."""
    triples = [
        ("ACTED_IN", "roles", ["List<String>"]),
        ("ACTED_IN", "roles_embedding", None),                # naming
        ("REVIEWED", "summary_vec", ["LIST<FLOAT>"]),         # type
        ("REVIEWED", "summary", ["String"]),
    ]
    out = _drop_embedding_pairs(triples, entity_type="relationship")
    assert ("ACTED_IN", "roles") in out
    assert ("REVIEWED", "summary") in out
    assert ("ACTED_IN", "roles_embedding") not in out
    assert ("REVIEWED", "summary_vec") not in out


# ── 4. FAISS clean-rebuild lifecycle ────────────────────────────────────────
#
# These tests guard the contract of ``ner_agent_auto.rebuild_tools_faiss``:
# it must purge the on-disk FAISS directory before rebuilding, so that
# (a) corrupt/garbage files left behind by an interrupted prior run cannot
# poison the next index, and (b) a schema change that shrinks the tool list
# leaves no orphan entries from the previous schema. Embedder and tool
# objects are mocked so the test runs offline in milliseconds.

@pytest.fixture
def _fake_faiss_env(tmp_path, monkeypatch):
    """
    Build a sandboxed FAISS environment for rebuild_tools_faiss():

      • Stubs out ``agent.agent_helper`` and ``agent.prompts`` and
        ``neo4j_lib.neo4j_search`` BEFORE importing ``ner_agent_auto``,
        so the test does not trigger a real Neo4j connection or
        provider-SDK initialisation at import time.
      • Redirects ``_FAISS_DIR_BY_MODE`` for "full" and "node_only" to
        ``tmp_path``.
      • Replaces ``_get_embeddings`` with FakeEmbeddings (deterministic
        offline vectors).
      • Replaces ``build_tool_registry`` with a stub so each test can
        inject its own tool list.
      • Clears the per-mode singleton caches so the test sees a clean state.

    Yields a dict ``{"set_registry": fn, "tmp_path": Path, "module": mod}``.
    """
    import sys
    import types

    from langchain_community.embeddings.fake import FakeEmbeddings
    from langchain_core.tools import tool as _tool

    # ── Stub heavyweight upstream modules so importing ner_agent_auto
    # does NOT pull in Neo4j connectivity, OpenAI, or Anthropic SDKs.
    # These stubs are scoped to the test session via monkeypatch — they
    # are torn down automatically after the test.
    def _install_stub(name: str, **attrs) -> None:
        stub = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(stub, k, v)
        monkeypatch.setitem(sys.modules, name, stub)

    # Drop any cached real module so our stub takes precedence even if a
    # previous test (or pytest collection) already imported the heavy chain.
    for _mod in (
        "ner_agent_auto",
        "agent.agent_helper", "agent.prompts", "agent",
        "neo4j_lib.neo4j_search", "neo4j_lib",
    ):
        monkeypatch.delitem(sys.modules, _mod, raising=False)

    # Minimal `agent` package + `agent.agent_helper` + `agent.prompts` stubs.
    _install_stub("agent")
    _install_stub(
        "agent.agent_helper",
        llm        = None,
        ner_llm    = None,
        qa_llm     = None,
        cypher_llm = None,
        neo4j_graph = None,
        get_entity = lambda *a, **kw: "",
        build_llm  = lambda *a, **kw: None,
    )
    _install_stub("agent.prompts", NER_SP="")

    # Minimal `neo4j_lib` package + `neo4j_lib.neo4j_search` stub.
    _install_stub("neo4j_lib")
    _install_stub("neo4j_lib.neo4j_search", search_tool=lambda *a, **kw: [])

    import ner_agent_auto

    # Redirect both per-mode FAISS directories under tmp_path so the real
    # repo-level "generated/faiss/tools_auto" is never touched.
    full_dir      = tmp_path / "tools_auto"
    node_only_dir = tmp_path / "tools_auto_node_only"
    monkeypatch.setitem(ner_agent_auto._FAISS_DIR_BY_MODE, "full",      str(full_dir))
    monkeypatch.setitem(ner_agent_auto._FAISS_DIR_BY_MODE, "node_only", str(node_only_dir))

    # Tiny offline embedder — no OpenAI calls, no network.
    fake = FakeEmbeddings(size=8)
    monkeypatch.setattr(ner_agent_auto, "_get_embeddings", lambda: fake)

    # Tool-registry stub — controlled by each test through set_registry().
    current_registry: Dict[str, object] = {}

    def _make_tool(name: str, description: str):
        @_tool
        def _stub(user_query: str) -> list:
            """placeholder"""
            return []
        _stub.name        = name
        _stub.description = description
        return _stub

    def set_registry(specs):
        """Replace the registry that ``build_tool_registry`` will return.

        ``specs`` is a list of (func_name, description) tuples.
        """
        current_registry.clear()
        for func_name, description in specs:
            current_registry[func_name] = _make_tool(func_name, description)

    monkeypatch.setattr(
        ner_agent_auto, "build_tool_registry",
        lambda mode=None: dict(current_registry),
    )

    # Clear the per-mode singleton caches so leaks from prior tests don't
    # confuse the assertions below.
    monkeypatch.setattr(ner_agent_auto, "_registry_by_mode",    {}, raising=False)
    monkeypatch.setattr(ner_agent_auto, "_vectorstore_by_mode", {}, raising=False)

    yield {
        "set_registry": set_registry,
        "tmp_path":     tmp_path,
        "full_dir":     full_dir,
        "module":       ner_agent_auto,
    }


def test_rebuild_purges_stale_garbage_file(_fake_faiss_env) -> None:
    """A garbage file planted at the FAISS index path must be deleted, and
    the resulting index must hold exactly the new tool count."""
    full_dir = _fake_faiss_env["full_dir"]
    full_dir.mkdir(parents=True, exist_ok=True)

    # Plant garbage where index.faiss should live + an orphan sibling that
    # save_local() would normally leave behind.
    (full_dir / "index.faiss").write_bytes(b"\x00\x01\x02 GARBAGE NOT A FAISS INDEX")
    (full_dir / "index.pkl").write_bytes(b"GARBAGE PICKLE")
    (full_dir / "leftover_from_prior_schema.json").write_text("{}")

    _fake_faiss_env["set_registry"]([
        ("get_movie_title",  "Get the canonical Movie.title values."),
        ("get_movie_tagline","Get the canonical Movie.tagline values."),
        ("get_person_name",  "Get the canonical Person.name values."),
    ])

    n = _fake_faiss_env["module"].rebuild_tools_faiss(mode="full")
    assert n == 3

    # Orphan must be gone (purged), and the new index files must exist
    # and be loadable.
    assert not (full_dir / "leftover_from_prior_schema.json").exists()
    assert (full_dir / "index.faiss").exists()
    assert (full_dir / "index.pkl").exists()

    # Validate the index by loading it through the same code path setup
    # uses in production.
    from tools.tool_search import load_faiss_vectorstore
    from langchain_community.embeddings.fake import FakeEmbeddings
    vs = load_faiss_vectorstore(str(full_dir), embeddings=FakeEmbeddings(size=8))
    assert vs.index.ntotal == 3


def test_rebuild_after_schema_shrink_has_no_orphan_entries(_fake_faiss_env) -> None:
    """Build with one schema, then rebuild with a smaller schema. The
    on-disk index must reflect ONLY the second schema — no leftover
    docstore entries from the first."""
    full_dir = _fake_faiss_env["full_dir"]
    mod      = _fake_faiss_env["module"]

    # ── Schema A — 5 tools (mimics the Movies database).
    _fake_faiss_env["set_registry"]([
        ("get_movie_title",   "Movie.title"),
        ("get_movie_tagline", "Movie.tagline"),
        ("get_movie_released","Movie.released"),
        ("get_person_name",   "Person.name"),
        ("get_person_born",   "Person.born"),
    ])
    n1 = mod.rebuild_tools_faiss(mode="full")
    assert n1 == 5

    # ── Schema B — 2 tools (mimics switching to a smaller graph DB).
    _fake_faiss_env["set_registry"]([
        ("get_team_name",   "Team.name"),
        ("get_player_name", "Player.name"),
    ])
    n2 = mod.rebuild_tools_faiss(mode="full")
    assert n2 == 2

    # The reloaded index must contain exactly Schema B's tools.
    from tools.tool_search import load_faiss_vectorstore
    from langchain_community.embeddings.fake import FakeEmbeddings
    vs = load_faiss_vectorstore(str(full_dir), embeddings=FakeEmbeddings(size=8))
    assert vs.index.ntotal == 2

    surviving = {doc.metadata["func_name"] for doc in vs.docstore._dict.values()}
    assert surviving == {"get_team_name", "get_player_name"}, (
        f"Schema-A tools leaked into the rebuilt index: extra={surviving - {'get_team_name', 'get_player_name'}}"
    )


# ── 5. FAISS fingerprint guard ──────────────────────────────────────────────
#
# Each FAISS index directory carries a sibling ``fingerprint.json`` that pins
# the live env at build time (database, NEO4J_URI host, embedding model, tool
# set hash, …). ``load_faiss_vectorstore`` verifies it before loading and
# raises ``StaleFaissIndexError`` on any mismatch. The guard NEVER auto-
# rebuilds — that would mask the user's mistake.
#
# These tests exercise the contract directly (no ner_agent_auto involved):
# build a small index with FakeEmbeddings, then load it under a perturbed
# environment and assert the guard fires with a useful message.

import json as _json
import os as _os


@pytest.fixture
def _fp_env(tmp_path, monkeypatch):
    """
    Sandbox for the fingerprint guard tests.

    Pins ``NEO4J_DATABASE`` / ``NEO4J_URI`` to deterministic values so the
    fingerprint built inside the test is stable, and yields:

      * ``faiss_dir``  — empty tmp directory the test will populate.
      * ``embeddings`` — offline ``FakeEmbeddings(size=8)``.
      * ``build``      — helper that calls ``build_tools_faiss`` with a
                         dict-of-(name, description) registry stub.
      * ``load``       — helper that calls ``load_faiss_vectorstore``.
    """
    from langchain_community.embeddings.fake import FakeEmbeddings
    from langchain_core.tools import tool as _tool

    from tools.tool_search import build_tools_faiss, load_faiss_vectorstore

    # Pin env so the live fingerprint is deterministic across test boxes.
    monkeypatch.setenv("NEO4J_DATABASE", "movies_test")
    monkeypatch.setenv("NEO4J_URI",      "neo4j+s://abc123.databases.neo4j.io:7687")

    # Make sure vector_config is freshly importable and exposes the two
    # attrs the fingerprint reads. (It's a real module on disk; we patch
    # attributes inside the individual mismatch tests as needed.)
    import vector_config  # noqa: F401  (cache it)

    embeddings = FakeEmbeddings(size=8)
    faiss_dir  = tmp_path / "faiss_fp"

    def _make_tool(name: str, description: str):
        @_tool
        def _stub(user_query: str) -> list:
            """placeholder"""
            return []
        _stub.name        = name
        _stub.description = description
        return _stub

    def _build(specs, *, ner_mode: str = "full"):
        registry = {
            func_name: _make_tool(func_name, desc)
            for func_name, desc in specs
        }
        build_tools_faiss(
            registry, str(faiss_dir),
            embeddings=embeddings,
            ner_mode=ner_mode,
        )
        return registry

    def _load(*, expected_tool_names=None, expected_ner_mode=None):
        return load_faiss_vectorstore(
            str(faiss_dir), embeddings=embeddings,
            expected_tool_names=expected_tool_names,
            expected_ner_mode=expected_ner_mode,
        )

    return {
        "faiss_dir":  faiss_dir,
        "embeddings": embeddings,
        "build":      _build,
        "load":       _load,
        "monkeypatch": monkeypatch,
    }


def test_fingerprint_written_on_build(_fp_env) -> None:
    """``build_tools_faiss`` must write ``fingerprint.json`` next to
    ``index.faiss`` with all 9 documented fields populated."""
    _fp_env["build"]([
        ("get_movie_title",   "Movie.title"),
        ("get_movie_tagline", "Movie.tagline"),
        ("get_person_name",   "Person.name"),
    ])

    fp_path = _fp_env["faiss_dir"] / "fingerprint.json"
    assert fp_path.is_file(), "fingerprint.json was not written next to the index"

    fp = _json.loads(fp_path.read_text(encoding="utf-8"))
    expected_keys = {
        "database", "neo4j_uri_host", "tool_names_hash", "tool_count",
        "embedding_model", "embedding_backend", "ner_mode", "built_at",
        "schema_version",
    }
    assert set(fp.keys()) == expected_keys, (
        f"fingerprint key set mismatch: missing={expected_keys - set(fp)!r}, "
        f"extra={set(fp) - expected_keys!r}"
    )
    assert fp["database"]       == "movies_test"
    assert fp["neo4j_uri_host"] == "abc123.databases.neo4j.io"
    assert fp["tool_count"]     == 3
    assert fp["ner_mode"]       == "full"
    assert fp["schema_version"] == 1
    assert fp["tool_names_hash"], "tool_names_hash must not be empty"
    assert fp["built_at"],        "built_at timestamp must be set"


def test_load_succeeds_with_matching_fingerprint(_fp_env) -> None:
    """Load must succeed without raising when nothing in the env has
    drifted between build-time and load-time."""
    registry = _fp_env["build"]([
        ("get_movie_title", "Movie.title"),
        ("get_person_name", "Person.name"),
    ])

    vs = _fp_env["load"](
        expected_tool_names=list(registry.keys()),
        expected_ner_mode="full",
    )
    assert vs.index.ntotal == 2


def test_load_raises_on_database_mismatch(_fp_env) -> None:
    """Switching ``NEO4J_DATABASE`` between build and load is the canonical
    CypherBench mistake. The guard must catch it with a message naming the
    ``database`` field."""
    _fp_env["build"]([("get_movie_title", "Movie.title")])

    # Simulate the user switching from movies_test → soccer_test without
    # rerunning setup_project.py.
    _fp_env["monkeypatch"].setenv("NEO4J_DATABASE", "soccer_test")

    from tools.tool_search import StaleFaissIndexError
    with pytest.raises(StaleFaissIndexError) as excinfo:
        _fp_env["load"]()
    msg = str(excinfo.value)
    assert "database" in msg, f"error msg should name the 'database' field: {msg!r}"
    assert "soccer_test" in msg
    assert "movies_test" in msg


def test_load_raises_on_tool_set_change(_fp_env) -> None:
    """Loading with a registry whose ``func_name`` set differs from build
    time must raise with a ``tool_names_hash`` mismatch."""
    _fp_env["build"]([
        ("get_movie_title", "Movie.title"),
        ("get_movie_tagline", "Movie.tagline"),
    ])

    # The on-disk index was built from {get_movie_title, get_movie_tagline}.
    # The "live" registry now has a different shape — exactly what happens
    # after a schema change without rebuild.
    different_names = ["get_team_name", "get_player_name", "get_match_score"]

    from tools.tool_search import StaleFaissIndexError
    with pytest.raises(StaleFaissIndexError) as excinfo:
        _fp_env["load"](expected_tool_names=different_names)
    msg = str(excinfo.value)
    assert "tool_names_hash" in msg, (
        f"error msg should name the 'tool_names_hash' field: {msg!r}"
    )


def test_load_raises_when_fingerprint_missing(_fp_env) -> None:
    """An index built by an older code path (no fingerprint at all) must
    not load silently — the guard must demand a rebuild."""
    _fp_env["build"]([("get_movie_title", "Movie.title")])

    # Older indexes had only index.faiss + index.pkl. Simulate that.
    fp_path = _fp_env["faiss_dir"] / "fingerprint.json"
    fp_path.unlink()
    assert not fp_path.exists()

    from tools.tool_search import StaleFaissIndexError
    with pytest.raises(StaleFaissIndexError) as excinfo:
        _fp_env["load"]()
    msg = str(excinfo.value).lower()
    assert "no fingerprint file" in msg, (
        f"error msg should mention 'no fingerprint file': {msg!r}"
    )


def test_load_raises_on_embedding_model_change(_fp_env) -> None:
    """Switching ``vector_config.EMBEDDING_MODEL_NAME`` invalidates the
    vector space — the guard must reject the load even when dimensions
    happen to match."""
    _fp_env["build"]([("get_movie_title", "Movie.title")])

    # Simulate the user editing vector_config.py to point at a different
    # embedding model. _live_fingerprint() reads the attr on every call.
    import vector_config
    _fp_env["monkeypatch"].setattr(
        vector_config, "EMBEDDING_MODEL_NAME",
        "totally-different-model-v2",
        raising=False,
    )

    from tools.tool_search import StaleFaissIndexError
    with pytest.raises(StaleFaissIndexError) as excinfo:
        _fp_env["load"]()
    msg = str(excinfo.value)
    assert "embedding_model" in msg, (
        f"error msg should name the 'embedding_model' field: {msg!r}"
    )
    assert "totally-different-model-v2" in msg


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
