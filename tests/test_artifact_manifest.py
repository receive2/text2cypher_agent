#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Published-artifact manifest: build gate, check statuses, set id."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import artifact_manifest as am  # noqa: E402
from eval.artifact_swap import SWAP_DIRS, SWAP_FILES, _SNIPPET_NAME  # noqa: E402

PAIRS = [("cypherbench_augmented", "movie"), ("mindthequery_augmented", "covid")]


def _make_archive(root: Path, dataset: str, graph: str, stamp: str | None = None, with_optional=False):
    pair = f"{dataset}__{graph}"
    a = root / pair
    for rel in SWAP_FILES + [_SNIPPET_NAME]:
        p = a / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{pair}:{rel}\n", encoding="utf-8")
    for d in SWAP_DIRS:
        (a / d).mkdir(parents=True, exist_ok=True)
        (a / d / "index.faiss").write_bytes(b"\x00" + pair.encode())
        (a / d / "fingerprint.json").write_text(json.dumps({"identity": {"pair": stamp or pair}}), encoding="utf-8")
    (a / "generated" / "fcav").mkdir(parents=True, exist_ok=True)          # large, never published
    (a / "generated" / "fcav" / "index.faiss").write_bytes(b"big")
    (a / "generated" / "__pycache__").mkdir(exist_ok=True)
    (a / "generated" / "__pycache__" / "x.pyc").write_bytes(b"pyc")
    if with_optional:
        (a / "generated" / "tool_descriptions.csv").write_text("t\n", encoding="utf-8")
    return a


@pytest.fixture
def root(tmp_path):
    for ds, g in PAIRS:
        _make_archive(tmp_path, ds, g)
    return tmp_path


def test_published_paths_cover_contract_only(root):
    rels = am.published_rel_paths(root / "cypherbench_augmented__movie")
    assert set(SWAP_FILES) <= set(rels) and _SNIPPET_NAME in rels
    assert any(r.startswith("generated/faiss/") for r in rels)
    assert not any("fcav" in r or "__pycache__" in r for r in rels)


def test_build_and_check_ok(root):
    manifest, excluded = am.build(root, PAIRS, commit="abc")
    assert not excluded and set(manifest["pairs"]) == {"cypherbench_augmented__movie", "mindthequery_augmented__covid"}
    assert manifest["commit"] == "abc" and len(manifest["set_id"]) == 12
    am.write_manifest(manifest, am.manifest_path(root))
    loaded = am.load_manifest(am.manifest_path(root))
    for ds, g in PAIRS:
        status, detail = am.check_pair(loaded, root, ds, g)
        assert status == am.OK, detail
        assert manifest["set_id"] in detail


def test_gate_excludes_misstamped_archive(tmp_path):
    _make_archive(tmp_path, "cypherbench_augmented", "movie")
    _make_archive(tmp_path, "cypherbench_augmented", "nba", stamp="cypherbench_augmented__movie")
    manifest, excluded = am.build(tmp_path, PAIRS[:1] + [("cypherbench_augmented", "nba")], commit="x")
    assert "cypherbench_augmented__nba" in excluded
    assert any("stamped for 'cypherbench_augmented__movie'" in p for p in excluded["cypherbench_augmented__nba"])
    assert set(manifest["pairs"]) == {"cypherbench_augmented__movie"}


def test_gate_accepts_equivalent_pair_stamp(tmp_path):
    # the same graph under its clean-set name (``_augmented`` stripped) is not pollution
    _make_archive(tmp_path, "cypherbench_augmented", "movie", stamp="cypherbench__movie")
    manifest, excluded = am.build(tmp_path, PAIRS[:1], commit="x")
    assert not excluded and "cypherbench_augmented__movie" in manifest["pairs"]


def test_gate_reports_missing_files(tmp_path):
    a = _make_archive(tmp_path, "cypherbench_augmented", "movie")
    (a / "agent" / "prompts.py").unlink()
    _, excluded = am.build(tmp_path, PAIRS[:1], commit="x")
    assert excluded["cypherbench_augmented__movie"] == ["missing agent/prompts.py"]


def test_check_statuses(root):
    manifest, _ = am.build(root, PAIRS, commit="x")
    # a changed prompt -> MISMATCH naming the file
    (root / "cypherbench_augmented__movie" / "agent" / "prompts.py").write_text("edited\n", encoding="utf-8")
    status, detail = am.check_pair(manifest, root, "cypherbench_augmented", "movie")
    assert status == am.MISMATCH and "differs: agent/prompts.py" in detail
    # an extra file inside the published tree is reported too
    (root / "mindthequery_augmented__covid" / "generated" / "faiss" / SWAP_DIRS[0].split("/")[-1] / "stray.bin").write_bytes(b"?")
    status, detail = am.check_pair(manifest, root, "mindthequery_augmented", "covid")
    assert status == am.MISMATCH and "not in set" in detail
    # archive absent -> MISSING; pair unknown -> UNPUBLISHED; no manifest -> UNPUBLISHED
    import shutil
    shutil.rmtree(root / "mindthequery_augmented__covid")
    assert am.check_pair(manifest, root, "mindthequery_augmented", "covid")[0] == am.MISSING
    assert am.check_pair(manifest, root, "zograscope_augmented", "pole")[0] == am.UNPUBLISHED
    assert am.check_pair(None, root, "cypherbench_augmented", "movie")[0] == am.UNPUBLISHED


def test_set_id_is_order_independent_and_content_sensitive(root):
    m1, _ = am.build(root, PAIRS, commit="x")
    m2, _ = am.build(root, list(reversed(PAIRS)), commit="y")
    assert m1["set_id"] == m2["set_id"]
    (root / "cypherbench_augmented__movie" / "schema_data" / "schema_meta.json").write_text("{}", encoding="utf-8")
    m3, _ = am.build(root, PAIRS, commit="x")
    assert m3["set_id"] != m1["set_id"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
