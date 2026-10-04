"""eval/full_rows.py + scripts/rejudge_full_rows.py: runs of the GraphCypherQAChain methods that were
scored on at most 10 rows are scored again on the full result of their stored predictions — in place,
once, only for those methods, and never on a run that is still being written."""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import orchestrate_sweep as osw            # noqa: E402
import rejudge_full_rows as rf             # noqa: E402
from eval import full_rows as fr           # noqa: E402

GOLD12 = "MATCH (m:Movie)-[:hasGenre]->(:Genre {name: 'drama'}) RETURN m.name"
RIGHT = 'MATCH (m:Movie)-[:hasGenre]->(:Genre {name: "drama"}) RETURN m.name'
WRONG = 'MATCH (m:Movie)-[:hasGenre]->(:Genre {name: "comedy"}) RETURN m.name'
SLOW = "MATCH (a), (b) RETURN count(*)"
WRITE = "CREATE (x:Thing) RETURN x"
GOLD1 = "MATCH (c:Company {name: 'SpaceX'}) RETURN c.launch_year"
TWELVE = [{"m.name": f"film {i}"} for i in range(12)]


class FakeGraph:
    """``query`` like LangChain's Neo4jGraph; raises like the driver does for a timeout / a write."""

    def __init__(self):
        self.results = {GOLD12: TWELVE, RIGHT: list(reversed(TWELVE)), WRONG: TWELVE[:3],
                        GOLD1: [{"c.launch_year": 2002}], "MATCH (c:Company) RETURN 2002 AS y": [{"y": 2002}]}
        self.queries = []

    def query(self, cypher, params=None):
        self.queries.append(cypher)
        if cypher == SLOW:
            raise RuntimeError("Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration: terminated")
        if cypher == WRITE:
            raise RuntimeError("Neo.ClientError.Statement.AccessMode: Writing in read access mode not allowed")
        if cypher not in self.results:
            raise RuntimeError("ServiceUnavailable: Couldn't connect")
        return self.results[cypher]


def value_cmp(pred_rows, gold_rows, *, gold_cypher=None):
    norm = lambda rows: Counter(tuple(sorted(str(v) for v in r.values())) for r in rows)
    return len(pred_rows[:1] and pred_rows[0]) == len(gold_rows[:1] and gold_rows[0]) and norm(pred_rows) == norm(gold_rows)


def _records():
    base = {"question": "?", "em": False, "graph": "movie", "difficulty": "easy", "error": None, "strategy": "typo"}
    return [
        # right query, 12 rows: scored on the chain's first 10 rows -> wrong; on all 12 -> right
        {**base, "qid": "capped", "ea": False, "psjs": 1.0, "pred_cypher": RIGHT, "gold_cypher": GOLD12},
        # PSJS fell back on the old verdict: computed again
        {**base, "qid": "fallback", "ea": False, "psjs": 0.0, "pred_cypher": RIGHT, "gold_cypher": GOLD12},
        {**base, "qid": "wrong", "ea": False, "psjs": 0.25, "pred_cypher": WRONG, "gold_cypher": GOLD12},
        {**base, "qid": "small", "ea": True, "psjs": 1.0, "pred_cypher": "MATCH (c:Company) RETURN 2002 AS y", "gold_cypher": GOLD1},
        {**base, "qid": "noquery", "ea": False, "psjs": 0.0, "pred_cypher": "", "gold_cypher": GOLD1},
        {**base, "qid": "slow", "ea": False, "psjs": 0.0, "pred_cypher": SLOW, "gold_cypher": GOLD1},
        {**base, "qid": "write", "ea": False, "psjs": 0.0, "pred_cypher": WRITE, "gold_cypher": GOLD1},
        {**base, "qid": "err", "ea": None, "psjs": None, "pred_cypher": "", "gold_cypher": GOLD1, "error": "agent: boom"},
    ]


def _run_dir(tmp_path, records, *, method="no_val_link", summary=True, age=3600):
    d = tmp_path / f"cypherbench_augmented__movie__{method}@m1__20261001-000000"
    d.mkdir(parents=True)
    f = d / "records.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    if summary:
        (d / "summary.json").write_text(json.dumps({
            "dataset": "cypherbench_augmented", "n": len(records), "n_errors": 1, "ea": 1 / 8, "psjs": 0.3,
            "run_config": {"dataset": "cypherbench_augmented", "graph": "movie", "knobs": {"METHOD": method}},
            "by_difficulty": {"all": {"ea": 1 / 8}}}), encoding="utf-8")
    old = time.time() - age
    import os
    os.utime(f, (old, old))
    return d


def _psjs(pred, gold, neo4j_graph=None, ea_value=None):
    return 1.0 if ea_value else 0.0


def _rejudge(d, *, dry_run=False):
    g = FakeGraph()
    return g, rf.rejudge_file(d / "records.jsonl", rf.Scorer(value_cmp), (g, g), {}, dry_run=dry_run, compute_psjs=_psjs)


def test_which_runs_used_the_chain():
    knobs = lambda m, r=2: {"run_config": {"knobs": {"METHOD": m, "CYPHER_RETRY_MAX_ROUNDS": str(r)}}}
    assert fr.uses_chain(knobs("no_val_link")) and fr.uses_chain(knobs("fcav"))
    assert not fr.uses_chain(knobs("react")) and not fr.uses_chain(knobs("cyanchor")) and not fr.uses_chain(knobs("graphrag"))
    assert fr.uses_chain(knobs("cyanchor", 0)) and fr.uses_chain(knobs("react", 0))   # no retry loop -> the chain
    assert fr.uses_chain({}, "cypherbench_augmented__movie__fcav@m1__20261001-000000")
    assert not fr.uses_chain({}, "cypherbench_augmented__movie__cyanchor_fl@m1__20261001-000000")
    assert fr.is_stale({"ea": False}) and not fr.is_stale({"ea": None}) and not fr.is_stale({"ea": True, "rows_rule": fr.RULE})
    assert fr.stale_count([{"ea": True}], chain=False) == 0


def test_rejudge_scores_the_full_result_and_nothing_else(tmp_path):
    d = _run_dir(tmp_path, _records())
    _, res = _rejudge(d)
    assert res["checked"] == 7 and res["changed"] == 2 and res["to_error"] == 1 and res["kept_writes"] == 1
    recs = {r["qid"]: r for r in map(json.loads, (d / "records.jsonl").read_text().splitlines())}
    assert recs["capped"]["ea"] is True and recs["capped"]["ea_capped"] is False and recs["capped"]["psjs"] == 1.0
    assert recs["fallback"]["ea"] is True and recs["fallback"]["psjs"] == 1.0 and recs["fallback"]["psjs_capped"] == 0.0
    assert recs["wrong"]["ea"] is False and recs["wrong"]["psjs"] == 0.25 and "psjs_capped" not in recs["wrong"]
    assert recs["small"]["ea"] is True and recs["small"]["ea_capped"] is True
    assert recs["noquery"]["ea"] is False                                  # no query: the chain's empty result
    assert recs["slow"]["ea"] is None and recs["slow"]["error"].startswith("agent: ") and recs["slow"]["ea_capped"] is False
    assert recs["write"]["ea"] is False and recs["write"]["rows_note"].startswith("not executed")
    assert recs["err"] == {**_records()[-1]}                              # an error record is not touched
    assert all(r.get("rows_rule") == fr.RULE for q, r in recs.items() if q != "err")
    s = json.loads((d / "summary.json").read_text())
    assert s["ea"] == pytest.approx(3 / 8) and s["n_errors"] == 2 and s["rows_rejudged"]["changed"] == 2
    assert s["run_config"]["knobs"]["METHOD"] == "no_val_link"             # everything else kept
    _, again = _rejudge(d)
    assert again["checked"] == 0                                           # a second run finds nothing to do


def test_dry_run_writes_nothing(tmp_path):
    d = _run_dir(tmp_path, _records())
    before = (d / "records.jsonl").read_text(), (d / "summary.json").read_text()
    _, res = _rejudge(d, dry_run=True)
    assert res["changed"] == 2 and ((d / "records.jsonl").read_text(), (d / "summary.json").read_text()) == before


def test_an_unreachable_graph_aborts_without_writing(tmp_path):
    recs = _records()
    recs[0]["pred_cypher"] = "MATCH (n) RETURN n.unknown"                  # FakeGraph: "ServiceUnavailable"
    d = _run_dir(tmp_path, recs)
    before = (d / "records.jsonl").read_text()
    with pytest.raises(RuntimeError, match="ServiceUnavailable"):
        _rejudge(d)
    assert (d / "records.jsonl").read_text() == before


def test_main_leaves_other_methods_and_unfinished_runs_alone(tmp_path, capsys):
    _run_dir(tmp_path / "a", _records(), method="cyanchor")                # executes its own query: never stale
    _run_dir(tmp_path / "b", _records(), age=5)                           # still being written
    assert rf.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "skipped — records.jsonl was written" in out and "0 run(s) re-judged, 1 skipped" in out


def test_status_marks_capped_cells_and_publish_refuses_them(tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "REPO", tmp_path)
    monkeypatch.setattr(osw, "rows_match_release", lambda ds, g, recs: (True, ""))
    logged = []
    monkeypatch.setattr(osw, "log", logged.append)
    root = tmp_path / "logs" / "x"
    capped = [{"qid": "a", "ea": False, "psjs": 1.0}, {"qid": "b", "ea": True, "psjs": 1.0}]
    for method, recs in (("no_val_link", capped), ("react", capped),
                         ("fcav", [{**r, "rows_rule": fr.RULE} for r in capped])):
        d = root / f"cypherbench_augmented__movie__{osw.method_seg(method)}@m1__20261001-000000"
        d.mkdir(parents=True)
        (d / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    pair = ("cypherbench_augmented", "movie")
    st = osw.build_status([pair], ["no_val_link", "react", "fcav"], {pair: 2}, "logs/x", "m1")
    assert st["complete"] and st["stale_rows"] == [(*pair, "no_val_link")]   # ↻ is not ✗; react and the stamped fcav are fine
    text = osw.render_status(st)
    assert "scored on at most 10 rows" in text and "--publish" in text and "✓ 2/0 ↻" in text
    monkeypatch.setattr(osw, "_git", lambda *a: "abc1234")
    assert "1 ↻ (--publish re-scores them)" in osw.verdict_line(st, "status")
    assert osw.publish(st, allow_incomplete=True) == 1                   # the fallback: still capped -> refused
    assert any("publish refused" in line for line in logged) and any(osw.REJUDGE_ROWS_CMD in line for line in logged)


def test_publish_path_rescores_capped_cells_graph_by_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "REPO", tmp_path)
    monkeypatch.setattr(osw, "rows_match_release", lambda ds, g, recs: (True, ""))
    logged = []
    monkeypatch.setattr(osw, "log", logged.append)
    root = tmp_path / "logs" / "x"
    capped = [{"qid": "a", "ea": False, "psjs": 1.0, "gold_cypher": GOLD1}, {"qid": "b", "ea": True, "psjs": 1.0, "gold_cypher": GOLD1}]
    for g in ("movie", "nba"):
        for method in ("no_val_link", "fcav", "react"):
            d = root / f"cypherbench_augmented__{g}__{osw.method_seg(method)}@m1__20261001-000000"
            d.mkdir(parents=True)
            (d / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in capped), encoding="utf-8")
    pairs = [("cypherbench_augmented", "movie"), ("cypherbench_augmented", "nba")]
    expected = {p: 2 for p in pairs}
    st = osw.build_status(pairs, ["no_val_link", "fcav", "react"], expected, "logs/x", "m1")
    assert len(st["stale_rows"]) == 4                                     # two chain methods on two graphs; react never

    calls = []
    def fake_runner(dirs):                                                # stands in for scripts/rejudge_full_rows.py
        calls.append(sorted(Path(d).name for d in dirs))
        for d in dirs:                                                    # the script stamps every scored record
            f = Path(d) / "records.jsonl"
            recs = [json.loads(l) for l in f.read_text().splitlines()]
            for r in recs:
                if r.get("ea") is not None:
                    r["ea_capped"], r["rows_rule"] = r["ea"], fr.RULE
            f.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        return 0, [f"  rejudged {Path(d).name}: 0 of 2 verdicts changed" for d in dirs]
    monkeypatch.setattr(osw, "_rejudge_rows_runner", fake_runner)
    assert osw.rejudge_capped_cells(st) is True
    assert len(calls) == 2 and all(len(c) == 2 and all("react" not in n for n in c) for c in calls)   # one call per graph, chain cells only
    after = osw.build_status(pairs, ["no_val_link", "fcav", "react"], expected, "logs/x", "m1")
    assert after["stale_rows"] == [] and after["complete"]
    assert any("re-scoring 4 No Val Link / FCAV cell(s)" in line for line in logged)

    # a graph whose database does not answer: reported, nothing else changes, the gate stays shut
    monkeypatch.setattr(osw, "_rejudge_rows_runner", lambda dirs: (1, ["  ! x: not changed — ServiceUnavailable"]))
    broken = osw.build_status(pairs, ["no_val_link"], expected, "logs/x", "m1")
    broken["stale_rows"] = [(*pairs[0], "no_val_link")]                 # pretend one cell is still capped
    assert osw.rejudge_capped_cells(broken) is False
    assert any("not re-scored" in line for line in logged)


def test_report_scripts_refuse_a_capped_chain_run(tmp_path):
    capped = [{"qid": "a", "ea": False, "psjs": 1.0, "gold_cypher": GOLD1}, {"qid": "b", "ea": None, "psjs": None, "error": "x"}]
    d = _run_dir(tmp_path / "x", capped)                                    # no_val_link, scored before the fix
    msg = fr.refusal(d, capped)
    assert "1 verdict(s)" in msg and fr.REJUDGE_CMD in msg
    assert fr.refusal(d, [{**r, "rows_rule": fr.RULE} for r in capped]) == ""   # stamped: nothing to refuse
    other = _run_dir(tmp_path / "y", capped, method="cyanchor")             # never used the chain
    assert fr.refusal(other, capped) == ""
