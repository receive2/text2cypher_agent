# -*- coding: utf-8 -*-
"""fcav.build_fcav_index — the value index is built without holding every vector as a
Python list: same embedding requests, same rows, and the scratch file never outlives it."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
faiss = pytest.importorskip("faiss")
import fcav                                          # noqa: E402
import vector_config as vc                           # noqa: E402
from embedding import embedding_helper as eh         # noqa: E402

DIM = 8


def _vector(text: str) -> list:
    """A deterministic stand-in for one embedding; "zero" embeds to the zero vector."""
    if text == "zero":
        return [0.0] * DIM
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    return np.random.default_rng(seed).standard_normal(DIM).astype("float64").tolist()


def _fake_embed(texts):
    return [_vector(t) for t in texts]


VALUES = [f"value {i}" for i in range(52)] + ["zero"] + [f"value {i}" for i in range(52, 102)]   # 103 values


@pytest.fixture
def small_slices(monkeypatch):
    """4 values per request, 3 requests per slice: 103 values are 9 slices."""
    monkeypatch.setattr(vc, "EMBEDDING_BATCH_SIZE", 4)
    monkeypatch.setattr(fcav, "_BUILD_SLICE_REQUESTS", 3)


def test_rows_are_what_one_call_over_all_values_gave(small_slices, monkeypatch, tmp_path):
    monkeypatch.setattr(fcav, "embed_texts", _fake_embed)
    before = fcav._normalize(np.asarray(_fake_embed(VALUES), dtype="float32"))   # the build before the change
    got = fcav._embed_normalized(VALUES, tmp_path / "vectors.tmp")
    assert got.dtype == np.float32 and got.shape == (103, DIM)
    assert np.array_equal(np.asarray(got), before)
    assert not np.asarray(got)[52].any()                                          # the zero vector stays zero


def test_the_embedding_requests_are_unchanged(small_slices, monkeypatch, tmp_path):
    sent = []

    def chunk(texts):
        sent.append(list(texts)); return _fake_embed(texts)

    monkeypatch.setattr(vc, "EMBEDDING_BACKEND", "openai")
    monkeypatch.setattr(eh, "_embed_openai_chunk", chunk)
    eh.embed_texts(VALUES)
    one_call, sent[:] = list(sent), []
    fcav._embed_normalized(VALUES, tmp_path / "vectors.tmp")
    assert sent == one_call and len(sent) == 26 and [len(c) for c in sent] == [4] * 25 + [3]


def test_a_short_answer_from_the_backend_is_refused(small_slices, monkeypatch, tmp_path):
    monkeypatch.setattr(fcav, "embed_texts", lambda texts: _fake_embed(texts)[:-1])
    with pytest.raises(RuntimeError, match="embedding shape mismatch"):
        fcav._embed_normalized(VALUES, tmp_path / "vectors.tmp")


TRIPLES = [(v, "Movie", "title") for v in VALUES]


def _build(monkeypatch, out, embed=_fake_embed):
    monkeypatch.setattr(fcav, "extract_value_triples", lambda driver, database, include_descriptions=False: list(TRIPLES))
    monkeypatch.setattr(fcav, "embed_texts", embed)
    return fcav.build_fcav_index(None, "neo4j", out_dir=out, dataset="cypherbench_augmented", graph="movie", uri="bolt://h:1")


def test_build_writes_the_index_and_removes_its_scratch_file(small_slices, monkeypatch, tmp_path):
    out = tmp_path / "generated" / "fcav"
    manifest = _build(monkeypatch, out)
    assert sorted(p.name for p in out.iterdir()) == ["index.faiss", "manifest.json", "meta.json"]
    assert manifest["count"] == 103 and manifest["dimensions"] == DIM and manifest["index_type"] == "flat"
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert json.loads((out / "meta.json").read_text(encoding="utf-8")) == [list(t) for t in TRIPLES]
    index = faiss.read_index(str(out / "index.faiss"))
    want = fcav._normalize(np.asarray(_fake_embed(VALUES), dtype="float32"))
    assert index.ntotal == 103 and np.array_equal(index.reconstruct_n(0, 103), want)


_APPROXIMATE = """
import json, sys
from pathlib import Path
import numpy as np, faiss
import fcav, vector_config as vc
vc.EMBEDDING_BATCH_SIZE = 4; fcav._BUILD_SLICE_REQUESTS = 3; fcav.FCAV_EXACT_MAX = 50
values = [f"value {i}" for i in range(103)]
vec = lambda t: np.random.default_rng(len(t) * 1000 + int(t.split()[1])).standard_normal(8).tolist()
fcav.embed_texts = lambda texts: [vec(t) for t in texts]
fcav.extract_value_triples = lambda driver, database, include_descriptions=False: [(v, "Movie", "title") for v in values]
out = Path(sys.argv[1])
m = fcav.build_fcav_index(None, "neo4j", out_dir=out, dataset="cypherbench_augmented", graph="movie", uri="bolt://h:1")
index = faiss.read_index(str(out / "index.faiss"))
want = fcav._normalize(np.asarray([vec(v) for v in values], dtype="float32"))
print(json.dumps({"kind": m["index_type"], "files": sorted(p.name for p in out.iterdir()), "ntotal": index.ntotal,
                  "rows_equal": bool(np.array_equal(index.reconstruct_n(0, 103), want))}))
"""


def test_the_approximate_index_past_the_exact_limit(tmp_path):
    """Its own interpreter: building an HNSW index runs FAISS's OpenMP code, which cannot share a
    process with the OpenMP runtime other test modules load (the driver process loads only FAISS's)."""
    import subprocess
    run = subprocess.run([sys.executable, "-c", _APPROXIMATE, str(tmp_path / "fcav")], cwd=REPO, text=True, capture_output=True)
    assert run.returncode == 0, run.stderr[-2000:]
    got = json.loads(run.stdout.strip().splitlines()[-1])
    assert got == {"kind": "hnsw", "files": ["index.faiss", "manifest.json", "meta.json"], "ntotal": 103, "rows_equal": True}


def test_a_failed_build_leaves_no_scratch_file(small_slices, monkeypatch, tmp_path):
    calls = []

    def flaky(texts):
        calls.append(len(texts))
        if len(calls) == 3:
            raise ConnectionError("embedding backend went away")
        return _fake_embed(texts)

    out = tmp_path / "generated" / "fcav"
    with pytest.raises(ConnectionError):
        _build(monkeypatch, out, embed=flaky)
    assert list(out.iterdir()) == []
