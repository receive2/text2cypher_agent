#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrate_sweep: pooled metrics, completeness cells, rendered status."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import orchestrate_sweep as osw  # noqa: E402


def test_pooled_metrics_score_errors_as_zero():
    recs = [{"ea": True, "psjs": 1.0}, {"ea": False, "psjs": 0.5}, {"ea": None, "psjs": None, "error": "boom"}, {"ea": True, "psjs": 0.25}]
    assert osw.ea(recs) == pytest.approx(0.5)            # 2 of 4, the errored row counts in the denominator
    assert osw.psjs(recs) == pytest.approx(1.75 / 4)     # None -> 0
    assert osw.n_err(recs) == 1
    assert osw.ea([]) is None and osw.psjs([]) is None


def _write_run(root: Path, dataset: str, graph: str, method: str, model: str, stamp: str, rows):
    seg = osw.method_seg(method)
    d = root / "logs" / "x" / f"{dataset}__{graph}__{seg}@{model}__{stamp}"
    d.mkdir(parents=True)
    (d / "records.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return d


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "REPO", tmp_path)
    pairs = [("cypherbench_augmented", "movie"), ("zograscope_augmented", "pole")]
    expected = {("cypherbench_augmented", "movie"): 3, ("zograscope_augmented", "pole"): 2}
    # movie: no_val_link complete (3 rows, one error), react truncated (2 rows); pole: nothing
    _write_run(tmp_path, "cypherbench_augmented", "movie", "no_val_link", "m1", "20260101-000000",
               [{"ea": True, "psjs": 1.0}, {"ea": False, "psjs": 0.0}, {"ea": None, "psjs": None, "error": "x"}])
    _write_run(tmp_path, "cypherbench_augmented", "movie", "react", "m1", "20260101-000000",
               [{"ea": True, "psjs": 1.0}, {"ea": True, "psjs": 1.0}])
    # a newer no_val_link run must win over the older one
    _write_run(tmp_path, "cypherbench_augmented", "movie", "no_val_link", "m1", "20260102-000000",
               [{"ea": True, "psjs": 1.0}, {"ea": True, "psjs": 1.0}, {"ea": True, "psjs": 1.0}])
    return pairs, expected


def test_cell_status_and_matrix(world):
    pairs, expected = world
    st = osw.build_status(pairs, ["no_val_link", "react"], expected, "logs/x", "m1")
    movie_nvl = st["cells"][("cypherbench_augmented", "movie", "no_val_link")]
    assert movie_nvl["complete"] and movie_nvl["n"] == 3 and movie_nvl["err"] == 0     # newest run, 3/3, no errors
    movie_react = st["cells"][("cypherbench_augmented", "movie", "react")]
    assert not movie_react["complete"] and movie_react["n"] == 2                       # truncated
    pole = st["cells"][("zograscope_augmented", "pole", "react")]
    assert not pole["complete"] and pole["n"] == 0 and pole["dir"] is None
    assert not st["complete"]
    text = osw.render_status(st)
    assert "**NOT CLEAN**" in text and "✓ 3/0" in text and "✗ 2/0" in text and "✗ missing" in text
    assert "| No Val Link | 1.000 | 1.000 |" in text            # CypherBench pooled over the complete cell


def test_status_complete_when_every_cell_is_full(tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "REPO", tmp_path)
    rows = [{"ea": True, "psjs": 1.0}, {"ea": None, "psjs": None, "error": "gold broken"}]
    for m in ("no_val_link", "react"):
        _write_run(tmp_path, "mindthequery_augmented", "er", m, "m1", "20260101-000000", rows)
    st = osw.build_status([("mindthequery_augmented", "er")], ["no_val_link", "react"],
                          {("mindthequery_augmented", "er"): 2}, "logs/x", "m1")
    assert st["complete"]                                    # errors do not block completeness
    text = osw.render_status(st)
    assert "**COMPLETE**" in text and "✓ 2/1" in text and "| No Val Link | 0.500 | 0.500 |" in text


def test_write_status_keeps_one_file_per_invocation(tmp_path, monkeypatch):
    import eval_config as cfg
    monkeypatch.setattr(osw, "REPO", tmp_path)
    monkeypatch.setattr(cfg, "REPORT_DIR", "report")
    rows = [{"ea": True, "psjs": 1.0, "strategy": "typo", "difficulty": "easy"},
            {"ea": False, "psjs": 0.0, "strategy": "alias", "difficulty": "hard"}]
    _write_run(tmp_path, "mindthequery_augmented", "er", "no_val_link", "m1", "20260101-000000", rows)
    st = osw.build_status([("mindthequery_augmented", "er")], ["no_val_link"], {("mindthequery_augmented", "er"): 2}, "logs/x", "m1")
    p1 = osw.write_status(st)
    import time; time.sleep(1.1)
    p2 = osw.write_status(st)
    assert p1 != p2 and p1.parent == tmp_path / "report" / "m1" and p1.name.startswith("SWEEP_")
    assert (tmp_path / "report" / "m1" / "SWEEP.md").read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")
    text = p2.read_text(encoding="utf-8")
    assert "by perturbation strategy" in text and "| typo |" in text.replace("| typo | alias", "| typo |") or "typo" in text
    assert "by query difficulty" in text and "hard" in text


def test_model_name_rejects_unknown_preset(monkeypatch):
    import eval_config as cfg
    monkeypatch.setattr(cfg, "GENERATOR_LLM", "gpt-9-nope")
    with pytest.raises(KeyError):
        osw.model_name()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
