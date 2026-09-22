#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rows that verification removed after a run was made are dropped by every
reader of evaluation records, so the run stays complete and is scored on the
released rows only (benchmarks/removed_rows.jsonl)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import eval_paths                      # noqa: E402
import orchestrate_sweep as osw        # noqa: E402

DS, G = "cypherbench_augmented", "movie"
RELEASE = {"a": "Who directed X?", "b": "Who wrote Y?"}
RETIRED = {"c": "Who produced Z?"}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(osw, "_RELEASE_ROWS", {(DS, G): dict(RELEASE)})
    monkeypatch.setattr(eval_paths, "_RETIRED", {(DS, G): dict(RETIRED)})


def test_is_retired_needs_graph_id_and_text(world):
    assert eval_paths.is_retired(DS, G, {"qid": "c", "question": "Who produced Z?"})
    assert eval_paths.is_retired(DS, G, {"qid": "c"})                       # no text: id decides
    assert not eval_paths.is_retired(DS, G, {"qid": "c", "question": "Who produced Q?"})
    assert not eval_paths.is_retired(DS, G, {"qid": "a", "question": "Who directed X?"})
    assert not eval_paths.is_retired("cypherbench", G, {"qid": "c"})         # clean-graph runs are never touched
    assert not eval_paths.is_retired(DS, "nba", {"qid": "c"})


def test_drop_retired_keeps_order(world):
    recs = [{"qid": "a"}, {"qid": "c", "question": "Who produced Z?"}, {"qid": "b"}]
    assert [r["qid"] for r in eval_paths.drop_retired(DS, G, recs)] == ["a", "b"]


def test_run_made_before_the_removal_still_matches_the_release(world):
    recs = [{"qid": "a", "question": "Who directed X?"}, {"qid": "b", "question": "Who wrote Y?"},
            {"qid": "c", "question": "Who produced Z?"}]
    ok, why = osw.rows_match_release(DS, G, recs)
    assert ok, why
    # a genuinely unknown row is still refused
    ok, why = osw.rows_match_release(DS, G, recs + [{"qid": "zzz", "question": "gone"}])
    assert not ok and "not in the released benchmark" in why


def test_cell_status_scores_the_released_rows_only(world, tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "REPO", tmp_path)                 # run dirs are labelled relative to the repo
    d = tmp_path / "runs" / f"{DS}__{G}__no_val_link@m__20260922-000000"
    d.mkdir(parents=True)
    rows = [{"qid": "a", "question": "Who directed X?", "ea": True, "psjs": 1.0},
            {"qid": "b", "question": "Who wrote Y?", "ea": False, "psjs": 0.0},
            {"qid": "c", "question": "Who produced Z?", "ea": True, "psjs": 1.0}]   # removed since
    (d / "records.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    c = osw.cell_status(DS, G, "no_val_link", expected=2, out_dir="runs", model="m")
    assert c["n"] == 2 and c["complete"] and c["rows_ok"]
    assert osw.ea(c["records"]) == 0.5


def test_real_file_matches_the_release(monkeypatch):
    """The shipped removed_rows.jsonl names rows that are NOT in the release files."""
    monkeypatch.setattr(eval_paths, "_RETIRED", None)
    if not eval_paths.RETIRED_ROWS_FILE.is_file():
        pytest.skip("no removed_rows.jsonl in this checkout")
    monkeypatch.setattr(osw, "_RELEASE_ROWS", None)
    rel = osw.release_rows()
    for (ds, g), rows in eval_paths.retired_rows().items():
        assert (ds, g) in rel
        assert not set(rows) & set(rel[(ds, g)]), f"{ds}/{g}: removed rows still in the release"
