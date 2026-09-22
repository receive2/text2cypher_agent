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


def test_discard_all_deletes_only_this_models_runs_after_confirmation(world):
    d1 = _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260916-120000", OK)
    d2 = _run(world, "cypherbench", "movie", "react", "m1", "20260916-120000", OK)            # clean graph: also gone
    d3 = _run(world, "cypherbench_augmented", "movie", "react", "m2", "20260916-120000", OK)  # another model: stays
    runs = world / "logs" / "runs"; logs = world / "logs"
    (runs / "report_20260918_195430.md").write_text("old eval_aggregate table")
    (logs / "sweep_m1.json").write_text("{}"); (logs / "sweep_m1_smoke.json").write_text("{}"); (logs / "sweep_m2.json").write_text("{}")
    seen = []
    assert ar.discard_all("m1", runs, logs, lambda paths: (seen.extend(paths), False)[1]) == []   # declined: nothing happens
    assert d1.exists() and d2.exists() and (runs / "report_20260918_195430.md").exists()
    assert {p.name for p in seen} == {d1.name, d2.name, "report_20260918_195430.md", "sweep_m1.json", "sweep_m1_smoke.json"}
    gone = ar.discard_all("m1", runs, logs, lambda paths: True)
    assert {p.name for p in gone} == {p.name for p in seen}
    assert not d1.exists() and not d2.exists() and d3.exists()
    assert not (logs / "sweep_m1.json").exists() and (logs / "sweep_m2.json").exists()
    assert ar.discard_all("m1", runs, logs, lambda paths: True) == []                         # nothing left to delete


def test_discard_all_cli_refuses_without_a_terminal_and_without_yes(world, monkeypatch, capsys):
    _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260916-120000", OK)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert ar.main(["--model", "m1", "--discard-all"]) == 0
    assert "nothing deleted" in capsys.readouterr().out
    assert (world / "logs" / "runs").iterdir().__next__().exists()
    assert ar.main(["--model", "m1", "--discard-all", "--yes"]) == 0
    assert "deleted 1 item(s)" in capsys.readouterr().out
