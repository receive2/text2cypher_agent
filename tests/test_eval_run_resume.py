"""eval_run supervises the evaluation worker: a worker that dies or stalls is relaunched on the
questions not yet recorded, and the segments are merged into one records.jsonl + summary.json."""
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

import eval_run

FAKE_WORKER = textwrap.dedent('''
    import json, sys, time
    from pathlib import Path
    test_path, out_rec, out_sum, mode, state = sys.argv[1:6]
    rows = json.load(open(test_path))
    attempt = int(Path(state).read_text()) if Path(state).exists() else 0
    Path(state).write_text(str(attempt + 1))
    def rec(r, ok=True):
        return json.dumps({"qid": r["id"], "question": r["nl"], "ea": ok, "em": False, "psjs": 1.0 if ok else 0.0,
                           "pred_cypher": "MATCH (n) RETURN n", "gold_cypher": r["gold_cypher"], "graph": r["graph"],
                           "difficulty": "easy", "error": None, "strategy": "typo"})
    with open(out_rec, "w") as fh:
        for i, r in enumerate(rows):
            if attempt == 0 and mode in ("die_after_2", "hang_after_2", "stall_on_q3") and i == 2:
                fh.flush()
                if mode == "hang_after_2":
                    time.sleep(120)          # alive, no progress: the parent must kill it
                sys.exit(3)                  # the in-process watchdog's last resort
            if mode == "stall_on_q3" and attempt == 1 and i == 0:
                sys.exit(3)                  # dies again on the same (first remaining) question
            if mode == "always_die":
                sys.exit(3)
            fh.write(rec(r) + "\\n"); fh.flush()
    json.dump({"n": len(rows), "ea": 1.0, "run_meta": {"fake": True, "attempt": attempt}}, open(out_sum, "w"))
    sys.exit(0)
''')


@pytest.fixture
def world(tmp_path):
    rows = [{"id": f"q{i}", "graph": "g", "nl": f"question {i}", "gold_cypher": "MATCH (n) RETURN n"} for i in range(5)]
    test_path = tmp_path / "test.json"; test_path.write_text(json.dumps(rows))
    (tmp_path / "fake_worker.py").write_text(FAKE_WORKER)
    pair = tmp_path / "pair"; pair.mkdir()
    return tmp_path, test_path, pair


def run(world, mode, **kw):
    tmp, test_path, pair = world
    state = tmp / f"state_{mode}"
    def argv(tp, rec, summ, lim):
        return [sys.executable, str(tmp / "fake_worker.py"), str(tp), str(rec), str(summ), mode, str(state)]
    ok, msg = eval_run._supervise_worker(argv, dataset="cypherbench_augmented", graph="g", test_path=test_path,
                                         out_records=pair / "records.jsonl", out_summary=pair / "summary.json",
                                         limit=None, env=os.environ.copy(), outer_timeout=60, stall_sec=2,
                                         startup_grace=0, poll_sec=0.1, **kw)
    recs = eval_run._read_records(pair / "records.jsonl")
    summ = json.loads((pair / "summary.json").read_text()) if (pair / "summary.json").exists() else None
    return ok, msg, recs, summ, int(state.read_text())


def test_clean_run_leaves_the_usual_files_only(world):
    ok, msg, recs, summ, attempts = run(world, "ok")
    assert ok and attempts == 1 and [r["qid"] for r in recs] == [f"q{i}" for i in range(5)]
    assert summ["run_meta"] == {"fake": True, "attempt": 0} and "resumed" not in summ
    assert sorted(p.name for p in world[2].iterdir()) == ["records.jsonl", "summary.json"]


def test_worker_death_is_resumed_on_the_remaining_questions(world):
    ok, msg, recs, summ, attempts = run(world, "die_after_2")
    assert ok and attempts == 2
    assert [r["qid"] for r in recs] == [f"q{i}" for i in range(5)]      # order kept, nothing twice
    assert summ["n"] == 5 and summ["n_errors"] == 0 and summ["ea"] == 1.0 and summ["resumed"] == 1
    assert summ["run_meta"]["attempt"] == 1                                # from the attempt that finished
    assert sorted(p.name for p in world[2].iterdir()) == ["records.jsonl", "summary.json"]


def test_stalled_worker_is_killed_and_resumed(world):
    ok, msg, recs, summ, attempts = run(world, "hang_after_2")
    assert ok and attempts == 2 and len(recs) == 5 and summ["resumed"] == 1


def test_question_that_kills_the_worker_twice_is_recorded_as_stalled(world):
    ok, msg, recs, summ, attempts = run(world, "stall_on_q3")
    assert ok and attempts == 3
    assert [r["qid"] for r in recs] == [f"q{i}" for i in range(5)]
    bad = [r for r in recs if r.get("error")]
    assert len(bad) == 1 and bad[0]["qid"] == "q2" and bad[0]["ea"] is None and "stalled" in bad[0]["error"]
    assert bad[0]["strategy"] is None and bad[0]["difficulty"] is not None
    assert summ["n"] == 5 and summ["n_errors"] == 1 and abs(summ["ea"] - 0.8) < 1e-9 and summ["resumed"] == 2


def test_a_worker_that_never_records_anything_fails_without_looping(world):
    ok, msg, recs, summ, attempts = run(world, "always_die")
    assert not ok and "worker exited 3" in msg
    assert attempts == 2 and recs == []          # one plain relaunch, no question blamed, then the pair fails


def test_non_json_test_set_is_not_resumed(world, tmp_path):
    tmp, test_path, pair = world
    csv = tmp / "test.csv"; csv.write_text("id,nl\nq0,x\n")
    state = tmp / "state_csv"
    def argv(tp, rec, summ, lim):
        return [sys.executable, str(tmp / "fake_worker.py"), str(test_path), str(rec), str(summ), "die_after_2", str(state)]
    ok, msg = eval_run._supervise_worker(argv, dataset="cypherbench_augmented", graph="g", test_path=csv,
                                         out_records=pair / "records.jsonl", out_summary=pair / "summary.json",
                                         limit=None, env=os.environ.copy(), outer_timeout=60, stall_sec=2, startup_grace=0, poll_sec=0.1)
    assert not ok and "not resumable" in msg and int(state.read_text()) == 1


def test_limit_is_reduced_by_what_is_done(world):
    tmp, test_path, pair = world
    state = tmp / "state_limit"
    seen = []
    def argv(tp, rec, summ, lim):
        seen.append((Path(tp).name, lim, len(json.load(open(tp)))))
        return [sys.executable, str(tmp / "fake_worker.py"), str(tp), str(rec), str(summ), "die_after_2", str(state)]
    ok, msg = eval_run._supervise_worker(argv, dataset="cypherbench_augmented", graph="g", test_path=test_path,
                                         out_records=pair / "records.jsonl", out_summary=pair / "summary.json",
                                         limit=4, env=os.environ.copy(), outer_timeout=60, stall_sec=2, startup_grace=0, poll_sec=0.1)
    assert ok and seen[0] == ("test.json", 4, 5) and seen[1][1] is None and seen[1][2] == 2   # 2 done of 4 wanted -> 2 rows remain
    assert len(eval_run._read_records(pair / "records.jsonl")) == 4
