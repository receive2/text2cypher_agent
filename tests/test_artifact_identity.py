# -*- coding: utf-8 -*-
"""
tests/test_artifact_identity.py
===============================
Offline regression tests for the per-graph artifact identity stamps
(:mod:`eval.artifact_identity`) and their enforcement at the archive /
swap-in / load boundaries (:mod:`eval.artifact_swap`, :mod:`fcav`).

These encode the invariants that would have prevented the 2026-07 FCAV
pollution incident (geography's value index folded into four MTQ archives):

1. ``archive_current`` refuses to fold an optional dir stamped for another
   graph — or carrying no stamp at all — into an archive.
2. ``swap_in`` removes a live optional dir the archive does not carry
   (hermetic swap: absent in archive ⇒ absent live).
3. ``swap_in`` refuses an archive whose stamped dir contradicts the
   archive's own pair name.
4. ``fcav._load`` refuses to serve an index whose stamp mismatches the
   live ``.current_setup`` sentinel.

All tests run offline against a fake repo tree under ``tmp_path``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eval import artifact_identity as ai
from eval import artifact_swap as aswap


# ──────────────────────────────────────────────────────────────────────────────
# artifact_identity unit tests
# ──────────────────────────────────────────────────────────────────────────────

def _mk_index_dir(root: Path, carrier: str = "manifest.json",
                  payload: dict | None = None) -> Path:
    d = root
    d.mkdir(parents=True, exist_ok=True)
    (d / carrier).write_text(json.dumps(payload or {"count": 3}), encoding="utf-8")
    (d / "index.faiss").write_bytes(b"\x00fake-index")
    return d


def test_pair_roundtrip():
    assert ai.pair_id("ds_augmented", "movie") == "ds_augmented__movie"
    assert ai.split_pair("ds_augmented__movie") == ("ds_augmented", "movie")
    with pytest.raises(ValueError):
        ai.split_pair("no-separator")


def test_stamp_read_verify_roundtrip(tmp_path):
    d = _mk_index_dir(tmp_path / "fcav")
    assert ai.read_identity(d) is None
    ai.stamp_dir(d, "mtq", "covid", uri="bolt://h:1", database="neo4j")
    ident = ai.read_identity(d)
    assert ident["pair"] == "mtq__covid"
    assert ident["bolt_uri"] == "bolt://h:1"
    # payload fields survive stamping
    assert json.loads((d / "manifest.json").read_text())["count"] == 3
    assert ai.verify_dir(d, "mtq__covid", context="t") is True


def test_verify_mismatch_always_raises(tmp_path):
    d = _mk_index_dir(tmp_path / "fcav")
    ai.stamp_dir(d, "cb", "geography")
    for missing in ("raise", "warn", "ignore"):
        with pytest.raises(ai.ArtifactIdentityError, match="pollution"):
            ai.verify_dir(d, "mtq__covid", context="t", missing=missing)


def test_verify_missing_policies(tmp_path):
    d = _mk_index_dir(tmp_path / "fcav")
    with pytest.raises(ai.ArtifactIdentityError, match="no identity stamp"):
        ai.verify_dir(d, "mtq__covid", context="t", missing="raise")
    assert ai.verify_dir(d, "mtq__covid", context="t", missing="warn") is False
    assert ai.verify_dir(d, "mtq__covid", context="t", missing="ignore") is False


def test_corrupt_carrier_raises(tmp_path):
    d = _mk_index_dir(tmp_path / "fcav")
    (d / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ai.ArtifactIdentityError, match="unreadable"):
        ai.read_identity(d)


def test_stamp_without_carrier_raises(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ai.ArtifactIdentityError, match="no carrier"):
        ai.stamp_dir(d, "a", "b")


def test_fingerprint_json_is_a_carrier(tmp_path):
    d = _mk_index_dir(tmp_path / "tools_auto", carrier="fingerprint.json",
                      payload={"tool_count": 5})
    ai.stamp_dir(d, "cb", "movie")
    assert ai.read_identity(d)["pair"] == "cb__movie"


def test_pairs_equivalent_clean_augmented_sibling(tmp_path):
    # same graph, clean vs augmented dataset → equivalent
    assert ai.pairs_equivalent("cypherbench__movie", "cypherbench_augmented__movie")
    assert ai.pairs_equivalent("mtq_augmented__covid", "mtq__covid")
    # different graphs → never equivalent
    assert not ai.pairs_equivalent("cypherbench_augmented__movie",
                                   "cypherbench_augmented__nba")
    assert not ai.pairs_equivalent(None, "cypherbench__movie")


def test_verify_accepts_augmented_sibling_stamp(tmp_path):
    d = _mk_index_dir(tmp_path / "fcav")
    ai.stamp_dir(d, "cypherbench", "movie")
    assert ai.verify_dir(d, "cypherbench_augmented__movie", context="t") is True


def test_current_pair(tmp_path):
    assert ai.current_pair(tmp_path) is None
    (tmp_path / ai.SENTINEL_NAME).write_text("cb__movie\n", encoding="utf-8")
    assert ai.current_pair(tmp_path) == "cb__movie"


# ──────────────────────────────────────────────────────────────────────────────
# artifact_swap boundary tests (fake repo tree)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def fake_repo(tmp_path, monkeypatch):
    """Minimal live tree satisfying artifact_swap's manifest, rooted in tmp."""
    root = tmp_path / "repo"
    for rel in aswap.SWAP_FILES + aswap.SWAP_FILES_OPTIONAL:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {rel}\n", encoding="utf-8")
    for rel in aswap.SWAP_DIRS:
        d = root / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / "fingerprint.json").write_text(json.dumps({"tool_count": 1}),
                                            encoding="utf-8")
        (d / "index.faiss").write_bytes(b"\x00tools")
    # NB: keep content after the block, like the real vector_config.py — a
    # block at EOF hits a `\s*$` regex edge in _vector_config_io where the
    # first extract/replace round-trip is not a fixed point.
    (root / "vector_config.py").write_text(
        "EMBEDDABLE_PROPERTIES = [\n]\nEMBEDDING_BACKEND = 'openai'\n",
        encoding="utf-8")
    monkeypatch.setattr(aswap, "REPO_ROOT", root)
    arch_root = tmp_path / "archives"
    arch_root.mkdir()
    monkeypatch.setattr(aswap, "_setup_artifacts_root", lambda: arch_root)
    return root


def _live_fcav(root: Path, payload: dict | None = None) -> Path:
    return _mk_index_dir(root / "generated" / "fcav", payload=payload)


def test_archive_refuses_foreign_optional_dir(fake_repo):
    d = _live_fcav(fake_repo)
    ai.stamp_dir(d, "cypherbench_augmented", "geography")
    with pytest.raises(ai.ArtifactIdentityError, match="pollution"):
        aswap.archive_current("mindthequery_augmented", "healthcare", force=True)


def test_archive_refuses_unstamped_optional_dir(fake_repo):
    _live_fcav(fake_repo)
    with pytest.raises(ai.ArtifactIdentityError, match="no identity stamp"):
        aswap.archive_current("mindthequery_augmented", "healthcare", force=True)


def test_archive_accepts_matching_optional_dir_and_stamps_required(fake_repo):
    d = _live_fcav(fake_repo)
    ai.stamp_dir(d, "mtq", "covid")
    aswap.archive_current("mtq", "covid", force=True)
    arch = aswap.archive_dir_for("mtq", "covid")
    assert ai.read_identity(arch / "generated" / "fcav")["pair"] == "mtq__covid"
    # required tools dirs were legacy-unstamped live; the ARCHIVED copies get
    # stamped from archive_current's own authoritative args
    for rel in aswap.SWAP_DIRS:
        assert ai.read_identity(arch / rel)["pair"] == "mtq__covid"


def test_swap_in_hermetic_removes_stale_optional_dir(fake_repo):
    # archive WITHOUT fcav; live WITH a stale (foreign) fcav dir
    aswap.archive_current("cb", "movie", force=True)
    stale = _live_fcav(fake_repo)
    ai.stamp_dir(stale, "cypherbench_augmented", "geography")
    aswap.swap_in("cb", "movie")
    assert not stale.exists(), "hermetic swap must remove dirs absent from archive"
    assert ai.current_pair(fake_repo) == "cb__movie"


def test_swap_in_refuses_polluted_archive(fake_repo):
    d = _live_fcav(fake_repo)
    ai.stamp_dir(d, "mtq", "covid")
    aswap.archive_current("mtq", "covid", force=True)
    # corrupt the archive: restamp its fcav dir as another graph's
    arch = aswap.archive_dir_for("mtq", "covid")
    ai.stamp_dir(arch / "generated" / "fcav", "cypherbench_augmented", "geography")
    (fake_repo / ai.SENTINEL_NAME).unlink(missing_ok=True)
    with pytest.raises(ai.ArtifactIdentityError, match="pollution"):
        aswap.swap_in("mtq", "covid")


def test_round_trip_still_passes_with_stamped_dirs(fake_repo):
    d = _live_fcav(fake_repo)
    ai.stamp_dir(d, "mtq", "covid")
    aswap.round_trip_check("mtq", "covid")


# ──────────────────────────────────────────────────────────────────────────────
# fcav load boundary
# ──────────────────────────────────────────────────────────────────────────────

def test_fcav_load_refuses_mismatched_index(tmp_path, monkeypatch):
    faiss = pytest.importorskip("faiss")
    np = pytest.importorskip("numpy")
    import fcav

    d = tmp_path / "generated" / "fcav"
    d.mkdir(parents=True)
    index = faiss.IndexFlatIP(4)
    index.add(np.zeros((2, 4), dtype="float32"))
    faiss.write_index(index, str(d / "index.faiss"))
    (d / "meta.json").write_text(json.dumps([["v", "L", "k"]] * 2), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({
        "count": 2, "embedding_model": "",
        "identity": ai.make_identity("cypherbench_augmented", "geography"),
    }), encoding="utf-8")

    monkeypatch.setattr(fcav, "REPO_ROOT", tmp_path)
    fcav._CACHE.clear()
    (tmp_path / ai.SENTINEL_NAME).write_text("mindthequery_augmented__healthcare\n",
                                             encoding="utf-8")
    with pytest.raises(ai.ArtifactIdentityError, match="pollution"):
        fcav._load(out_dir=d)

    # matching sentinel loads fine
    (tmp_path / ai.SENTINEL_NAME).write_text("cypherbench_augmented__geography\n",
                                             encoding="utf-8")
    fcav._CACHE.clear()
    index_, meta, manifest = fcav._load(out_dir=d)
    assert manifest["count"] == 2


def test_fcav_load_refuses_unstamped_index_under_sentinel(tmp_path, monkeypatch):
    faiss = pytest.importorskip("faiss")
    np = pytest.importorskip("numpy")
    import fcav

    d = tmp_path / "generated" / "fcav"
    d.mkdir(parents=True)
    index = faiss.IndexFlatIP(4)
    index.add(np.zeros((1, 4), dtype="float32"))
    faiss.write_index(index, str(d / "index.faiss"))
    (d / "meta.json").write_text(json.dumps([["v", "L", "k"]]), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"count": 1}), encoding="utf-8")

    monkeypatch.setattr(fcav, "REPO_ROOT", tmp_path)
    fcav._CACHE.clear()
    (tmp_path / ai.SENTINEL_NAME).write_text("mtq__covid\n", encoding="utf-8")
    with pytest.raises(ai.ArtifactIdentityError, match="no identity stamp"):
        fcav._load(out_dir=d)
