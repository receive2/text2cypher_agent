# -*- coding: utf-8 -*-
"""scripts/audit_runs.py — which run directories the sweep can use, and the
verdict for every other kind (older benchmark copy, made before the checkout
had the published artifact set, superseded, truncated, outside the suite)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import orchestrate_sweep as osw       # noqa: E402
import scripts.audit_runs as ar       # noqa: E402

REL = {("cypherbench_augmented", "movie"): {"a": "qa", "b": "qb"},
       ("cypherbench_augmented", "nba"):   {"n1": "q1"}}
OK = [{"qid": "a", "question": "qa", "ea": True}, {"qid": "b", "question": "qb", "ea": True}]


def _run(root: Path, dataset, graph, method, model, stamp, rows):
    d = root / "logs" / "runs" / f"{dataset}__{graph}__{osw.method_seg(method)}@{model}__{stamp}"
    d.mkdir(parents=True)
    (d / "records.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return d


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "_RELEASE_ROWS", REL)
    monkeypatch.setattr(osw, "suite_pairs", lambda: [("cypherbench_augmented", "movie"), ("cypherbench_augmented", "nba")])
    monkeypatch.setattr(ar, "REPO", tmp_path)
    return tmp_path


def test_every_verdict(world):
    guard = datetime(2026, 9, 10, 18, 29)
    _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260909-120000", OK)        # before the guard
    _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260915-120000", OK)        # complete, later superseded
    _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260916-120000", OK[:1])    # newest but truncated
    _run(world, "cypherbench_augmented", "nba", "react", "m1", "20260916-120000",
         [{"qid": "n1", "question": "q1", "ea": True}, {"qid": "zzz", "question": "removed", "ea": True}])  # older benchmark copy
    _run(world, "cypherbench", "movie", "react", "m1", "20260916-120000", OK)                  # clean graph: outside the suite
    _run(world, "cypherbench_augmented", "movie", "react", "m2", "20260916-120000", OK)        # another model: not listed
    rows = ar.audit(world / "logs" / "runs", "m1", False, guard)
    v = {r["dir"].name: r["verdict"] for r in rows}
    assert v["cypherbench_augmented__movie__react@m1__20260909-120000"] == "DELETE"
    assert v["cypherbench_augmented__movie__react@m1__20260915-120000"] == "older"
    assert v["cypherbench_augmented__movie__react@m1__20260916-120000"] == "partial"
    assert v["cypherbench_augmented__nba__react@m1__20260916-120000"] == "DELETE"
    assert v["cypherbench__movie__react@m1__20260916-120000"] == "outside"
    assert not any(r["model"] == "m2" for r in rows)
    partial = next(r for r in rows if r["verdict"] == "partial")
    assert partial["fallback"].endswith("cypherbench_augmented__movie__react@m1__20260915-120000")
    before = next(r for r in rows if r["dir"].name.endswith("20260909-120000"))
    assert "before this checkout had the published artifact set (2026-09-10 18:29)" in before["reason"]


def test_all_models_lists_every_model(world):
    _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260916-120000", OK)
    _run(world, "cypherbench_augmented", "movie", "react", "m2", "20260916-120000", OK)
    rows = ar.audit(world / "logs" / "runs", None, True, datetime(2026, 9, 10, 18, 29))
    assert sorted(r["model"] for r in rows) == ["m1", "m2"] and all(r["verdict"] == "keep" for r in rows)


def test_no_git_evidence_means_check_not_keep(world):
    _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260916-120000", OK)
    rows = ar.audit(world / "logs" / "runs", "m1", False, None)
    assert rows[0]["verdict"] == "CHECK"


def test_guard_since_on_this_repo():
    when, note = ar.guard_since()
    assert when is not None and "published artifact set since" in note
