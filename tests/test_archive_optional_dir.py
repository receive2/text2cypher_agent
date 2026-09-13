#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""archive_optional_dir: fold one optional index into an archive without touching
the published files; symlinked archives resolve; mis-stamped live dirs are refused."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eval import artifact_swap as aswap  # noqa: E402
from eval.artifact_identity import stamp_dir, ArtifactIdentityError  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "repo"; arch_root = tmp_path / "setup_artifacts"
    (root / "generated" / "fcav").mkdir(parents=True); arch_root.mkdir()
    (root / "generated" / "fcav" / "index.faiss").write_bytes(b"live-index")
    (root / "generated" / "fcav" / "manifest.json").write_text(json.dumps({"count": 1}), encoding="utf-8")
    monkeypatch.setattr(aswap, "REPO_ROOT", root)
    monkeypatch.setattr(aswap, "_setup_artifacts_root", lambda: arch_root)
    return root, arch_root


def _archive(arch_root: Path, name: str) -> Path:
    a = arch_root / name
    (a / "agent").mkdir(parents=True)
    (a / "agent" / "prompts.py").write_text("PUBLISHED\n", encoding="utf-8")
    return a


def test_folds_only_fcav_and_keeps_published_files(world):
    root, arch_root = world
    a = _archive(arch_root, "cypherbench_augmented__movie")
    stamp_dir(root / "generated" / "fcav", "cypherbench_augmented", "movie")
    dst = aswap.archive_optional_dir("cypherbench_augmented", "movie", "generated/fcav")
    assert dst == a / "generated" / "fcav"
    assert (dst / "index.faiss").read_bytes() == b"live-index"
    assert (a / "agent" / "prompts.py").read_text(encoding="utf-8") == "PUBLISHED\n"
    assert sorted(p.name for p in a.iterdir()) == ["agent", "generated"]        # nothing else added


def test_symlinked_archive_is_resolved(world):
    root, arch_root = world
    target = _archive(arch_root, "mindthequery_augmented__bloom50")
    os.symlink(target.name, arch_root / "mindthequery_augmented__bloom")
    stamp_dir(root / "generated" / "fcav", "mindthequery_augmented", "bloom")
    dst = aswap.archive_optional_dir("mindthequery_augmented", "bloom", "generated/fcav")
    assert dst == target / "generated" / "fcav" and (dst / "index.faiss").is_file()
    assert (arch_root / "mindthequery_augmented__bloom").is_symlink()          # link survives


def test_refuses_index_stamped_for_another_graph(world):
    root, arch_root = world
    _archive(arch_root, "cypherbench_augmented__nba")
    stamp_dir(root / "generated" / "fcav", "cypherbench_augmented", "movie")
    with pytest.raises(ArtifactIdentityError):
        aswap.archive_optional_dir("cypherbench_augmented", "nba", "generated/fcav")


def test_rejects_non_optional_rel_and_missing_archive(world):
    root, arch_root = world
    with pytest.raises(ValueError):
        aswap.archive_optional_dir("cypherbench_augmented", "movie", "generated/faiss/tools_auto")
    stamp_dir(root / "generated" / "fcav", "cypherbench_augmented", "movie")
    with pytest.raises(FileNotFoundError):
        aswap.archive_optional_dir("cypherbench_augmented", "movie", "generated/fcav")   # no archive dir yet


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_swap_in_reswaps_when_live_files_differ_despite_sentinel(tmp_path, monkeypatch):
    """A git pull can overwrite the tracked live copies while .current_setup still
    names the pair; swap_in must notice and re-copy instead of no-op'ing."""
    import json as _json
    from eval.artifact_swap import SWAP_FILES, SWAP_DIRS, _SNIPPET_NAME
    root = tmp_path / "repo"; arch_root = tmp_path / "setup_artifacts"
    monkeypatch.setattr(aswap, "REPO_ROOT", root)
    monkeypatch.setattr(aswap, "_setup_artifacts_root", lambda: arch_root)
    a = arch_root / "cypherbench_augmented__movie"
    for rel in SWAP_FILES + [_SNIPPET_NAME]:
        (a / rel).parent.mkdir(parents=True, exist_ok=True); (a / rel).write_text(f"ARCHIVE {rel}\\n", encoding="utf-8")
    for d in SWAP_DIRS:
        (a / d).mkdir(parents=True, exist_ok=True); (a / d / "index.faiss").write_bytes(b"x")
        (a / d / "fingerprint.json").write_text(_json.dumps({"identity": {"pair": "cypherbench_augmented__movie"}}), encoding="utf-8")
    (root / "vector_config.py").parent.mkdir(parents=True, exist_ok=True)
    (root / "vector_config.py").write_text("EMBEDDABLE_PROPERTIES = []\\n", encoding="utf-8")
    # live tree: another graph's copies, but the sentinel claims movie
    for rel in SWAP_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_text(f"OTHER GRAPH {rel}\\n", encoding="utf-8")
    aswap._write_sentinel("cypherbench_augmented__movie")
    aswap.swap_in("cypherbench_augmented", "movie")
    for rel in SWAP_FILES:
        assert (root / rel).read_text(encoding="utf-8") == f"ARCHIVE {rel}\\n"
