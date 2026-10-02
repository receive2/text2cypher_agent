"""scripts/rejudge_node_returns.py: verdicts made before the node-set rule are corrected from the
stored predictions — in place, once, and never on a run that is still being written."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import orchestrate_sweep as osw            # noqa: E402
import rejudge_node_returns as rj          # noqa: E402
from eval import node_set_match as nsm     # noqa: E402

GOLD = 'MATCH (x0:Crime)-[:OCCURRED_AT]-(x1:Location WHERE x1.address = "Pedestrian Subway") RETURN x0'
GOLD_PROP = "MATCH (x0:Crime) RETURN x0.id"
RIGHT = 'MATCH (c:Crime)-[:OCCURRED_AT]->(:Location {address: "Pedestrian Subway"}) RETURN DISTINCT c.id'
OTHER = 'MATCH (c:Crime)-[:OCCURRED_AT]->(:Location {address: "Subway"}) RETURN DISTINCT c.id'
C1, C2, C3 = {"id": "c1"}, {"id": "c2"}, {"id": "c3"}


class FakeGraph:
    def __init__(self):
        self.results = {GOLD: [{"x0": C1}, {"x0": C2}],
                        nsm.project_to_node(RIGHT): [{"c": C2}, {"c": C1}],
                        nsm.project_to_node(OTHER): [{"c": C3}]}
        self.queries = []

    def query(self, cypher, params=None):
        self.queries.append(cypher)
        return self.results[cypher]


def _records():
    base = {"question": "Which crimes ...?", "em": False, "graph": "pole", "difficulty": "easy", "error": None, "strategy": "typo"}
    return [
        {**base, "qid": "right", "ea": False, "psjs": 1.0, "pred_cypher": RIGHT, "gold_cypher": GOLD},     # selects the gold nodes
        {**base, "qid": "other", "ea": False, "psjs": 0.2, "pred_cypher": OTHER, "gold_cypher": GOLD},     # selects other nodes
        {**base, "qid": "count", "ea": False, "psjs": 0.5, "pred_cypher": "MATCH (c:Crime) RETURN count(c)", "gold_cypher": GOLD},
        {**base, "qid": "prop",  "ea": False, "psjs": 0.0, "pred_cypher": "MATCH (c:Crime) RETURN c.type", "gold_cypher": GOLD_PROP},
        {**base, "qid": "ok",    "ea": True,  "psjs": 1.0, "pred_cypher": "MATCH (c:Crime) RETURN c.id", "gold_cypher": GOLD_PROP},
        {**base, "qid": "err",   "ea": None,  "psjs": None, "pred_cypher": "", "gold_cypher": GOLD, "error": "agent: boom"},
    ]


def _run_dir(tmp_path, records, *, summary=True, age=3600):
    d = tmp_path / "zograscope_augmented__pole__cyanchor_fl@m1__20261001-000000"
    d.mkdir(parents=True)
    f = d / "records.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    if summary:
        (d / "summary.json").write_text(json.dumps({
            "dataset": "zograscope_augmented", "n": len(records), "ea": 1 / 6, "psjs": 0.45, "elapsed_sec": 12.0,
            "run_config": {"dataset": "zograscope_augmented", "graph": "pole", "knobs": {"TOOL_TYPE": "node"}},
            "by_difficulty": {"all": {"ea": 1 / 6}}}), encoding="utf-8")
    old = time.time() - age
    os.utime(f, (old, old))
    return f


def test_rejudge_corrects_the_stale_verdicts_and_nothing_else(tmp_path):
    f = _run_dir(tmp_path, _records())
    graph = FakeGraph()
    res = rj.rejudge_file(f, graph, {}, dry_run=False)
    assert res["checked"] == 3 and res["accepted"] == 1 and res["n"] == 6
    assert res["ea_before"] == pytest.approx(1 / 6) and res["ea_after"] == pytest.approx(2 / 6)
    by = {r["qid"]: r for r in rj.read_records(f)}
    assert (by["right"]["ea"], by["right"]["ea_strict"]) == (True, False)
    assert (by["other"]["ea"], by["other"]["ea_strict"]) == (False, False)          # checked, still wrong
    assert (by["count"]["ea"], by["count"]["ea_strict"]) == (False, False)          # nothing to project
    assert (by["prop"]["ea"], by["prop"]["ea_strict"]) == (False, False)            # the gold returns a property
    assert (by["ok"]["ea"], by["ok"]["ea_strict"]) == (True, True)
    assert (by["err"]["ea"], by["err"]["ea_strict"]) == (None, None) and by["err"]["error"] == "agent: boom"
    assert by["right"]["pred_cypher"] == RIGHT and by["right"]["psjs"] == 1.0      # everything else is untouched
    assert graph.queries.count(GOLD) == 1                                          # one gold execution for three records

    s = json.loads(f.with_name("summary.json").read_text(encoding="utf-8"))
    assert s["ea"] == pytest.approx(2 / 6) and s["ea_strict"] == pytest.approx(1 / 6) and s["ea_rule"] == nsm.RULE
    assert s["rejudged"]["checked"] == 3 and s["rejudged"]["accepted"] == 1
    assert s["by_difficulty"]["easy"]["ea"] == pytest.approx(2 / 6)
    assert s["run_config"]["knobs"] == {"TOOL_TYPE": "node"} and s["elapsed_sec"] == 12.0   # the run's own facts stay
    assert not list(f.parent.glob("*.tmp"))

    # a second pass finds nothing: every record now states its value verdict
    assert nsm.stale_count(rj.read_records(f)) == 0
    again = rj.rejudge_file(f, FakeGraph(), {}, dry_run=False)
    assert again["checked"] == 0 and again["accepted"] == 0


def test_dry_run_writes_nothing(tmp_path):
    f = _run_dir(tmp_path, _records())
    before = (f.read_text(encoding="utf-8"), f.with_name("summary.json").read_text(encoding="utf-8"))
    res = rj.rejudge_file(f, FakeGraph(), {}, dry_run=True)
    assert res["accepted"] == 1
    assert (f.read_text(encoding="utf-8"), f.with_name("summary.json").read_text(encoding="utf-8")) == before


def test_psjs_is_recomputed_only_where_it_was_the_ea_fallback(tmp_path):
    recs = _records()
    recs[0]["psjs"] = 0.0                               # the fallback value under the old verdict
    calls = []

    def fake_psjs(pred, gold, neo4j_graph, ea_value):
        calls.append((pred, ea_value))
        return 1.0
    rj.rejudge_records(recs, FakeGraph(), {}, compute_psjs=fake_psjs)
    assert calls == [(RIGHT, True)]
    assert recs[0]["psjs"] == 1.0 and recs[0]["psjs_strict"] == 0.0

    recs = _records()                                   # a measured PSJS (1.0) is never computed again
    rj.rejudge_records(recs, FakeGraph(), {}, compute_psjs=lambda *a, **k: pytest.fail("must not recompute"))
    assert recs[0]["psjs"] == 1.0 and "psjs_strict" not in recs[0]


def test_a_gold_query_that_no_longer_runs_aborts_without_writing(tmp_path):
    f = _run_dir(tmp_path, _records())
    before = f.read_text(encoding="utf-8")

    class Down:
        def query(self, cypher, params=None):
            raise ConnectionError("graph unreachable")
    with pytest.raises(RuntimeError, match="gold query"):
        rj.rejudge_file(f, Down(), {}, dry_run=False)
    assert f.read_text(encoding="utf-8") == before


def test_unfinished_runs_are_left_alone(tmp_path):
    no_summary = _run_dir(tmp_path / "a", _records(), summary=False)
    assert "not finished" in rj.still_written(no_summary)
    fresh = _run_dir(tmp_path / "b", _records(), age=5)
    assert "may not be finished" in rj.still_written(fresh)
    done = _run_dir(tmp_path / "c", _records())
    assert rj.still_written(done) == ""


def test_the_graph_of_a_run_comes_from_its_summary_or_its_name(tmp_path):
    f = _run_dir(tmp_path / "a", _records())
    assert rj.pair_of(f, rj.read_records(f)) == ("zograscope_augmented", "pole")
    g = _run_dir(tmp_path / "b", _records(), summary=False)                       # falls back to the directory name
    assert rj.pair_of(g, rj.read_records(g)) == ("zograscope_augmented", "pole")
    cell = tmp_path / "pole_full__reference"                                      # an ablation cell: summary only
    cell.mkdir()
    (cell / "records.jsonl").write_text("", encoding="utf-8")
    (cell / "summary.json").write_text(json.dumps({"dataset": "zograscope_augmented", "run_config": {"graph": "pole"}}))
    assert rj.pair_of(cell / "records.jsonl", [{"graph": "pole"}]) == ("zograscope_augmented", "pole")
    found = rj.find_record_files([tmp_path, tmp_path / "a", f])                   # folders, run dirs and files; no duplicates
    assert sorted(found) == sorted(tmp_path.rglob("records.jsonl")) and len(found) == 3


# ── the sweep driver marks such cells and refuses to publish them ─────────────

def _sweep_run(root: Path, method: str, rows):
    d = root / "logs" / "x" / f"zograscope_augmented__pole__{osw.method_seg(method)}@m1__20260101-000000"
    d.mkdir(parents=True)
    (d / "records.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_status_marks_cells_judged_before_the_rule_and_publish_refuses_them(tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "REPO", tmp_path)
    monkeypatch.setattr(osw, "rows_match_release", lambda ds, g, recs: (True, ""))
    logged = []
    monkeypatch.setattr(osw, "log", logged.append)
    stale = [{"qid": "a", "ea": False, "psjs": 1.0, "gold_cypher": GOLD}, {"qid": "b", "ea": True, "psjs": 1.0, "gold_cypher": GOLD}]
    judged = [{"qid": "a", "ea": True, "ea_strict": False, "psjs": 1.0, "gold_cypher": GOLD},
              {"qid": "b", "ea": True, "ea_strict": True, "psjs": 1.0, "gold_cypher": GOLD}]
    _sweep_run(tmp_path, "no_val_link", stale)
    _sweep_run(tmp_path, "react", judged)
    pair = ("zograscope_augmented", "pole")
    st = osw.build_status([pair], ["no_val_link", "react"], {pair: 2}, "logs/x", "m1")
    assert st["complete"]                                        # ↻ is not ✗: nothing is re-run for it
    assert st["stale"] == [(*pair, "no_val_link")] and st["cells"][(*pair, "react")]["stale"] == 0
    assert osw.decide_cell(st["cells"][(*pair, "no_val_link")], {}, manual=False)[0] == "skip"
    text = osw.render_status(st)
    assert "**RE-JUDGE NEEDED** — 1 cell(s)" in text and "✓ 2/0 ↻" in text and osw.REJUDGE_CMD in text
    assert "| ReAct | 0.500 | 0.500 |" in text                   # the value-only table: ReAct 1.000 with the rule, 0.500 without
    monkeypatch.setattr(osw, "_git", lambda *a: "abc1234")
    assert "1 ↻" in osw.verdict_line(st, "status")

    assert osw.publish(st, allow_incomplete=True) == 1           # --allow-incomplete does not lift it
    assert any("publish refused" in line for line in logged) and any(osw.REJUDGE_CMD in line for line in logged)
