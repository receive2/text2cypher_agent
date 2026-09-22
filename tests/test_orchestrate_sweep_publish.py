# -*- coding: utf-8 -*-
"""Tests for the parts of orchestrate_sweep.py that a runner depends on but that
never run the model: error classification, ⚠ flagging, and the worktree-based
publish. The flagging cases are the real numbers from the first returned sweep
(gpt-5.6-luna, 2026-09-18) and the committed gpt-4.1 reference tables."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import orchestrate_sweep as osw  # noqa: E402


# ── error classification ─────────────────────────────────────────────────────

@pytest.mark.parametrize("error, kind", [
    ("gold: CypherSyntaxError: {code: Neo.ClientError.Statement.SyntaxError} {message: 'distance", "gold"),
    ("agent: CypherSyntaxError: {code: Neo.ClientError.Statement.SyntaxError} {message: Variable", "agent"),
    ("agent: CypherTypeError: {code: Neo.ClientError.Statement.TypeError} {message: Ex", "agent"),
    ("example timeout: exceeded 900s", "infra"),
    ("agent: APITimeoutError: Request timed out.", "infra"),        # infra wins over the agent prefix
    ("transaction timeout: query exceeded 60s", "infra"),
    ("RateLimitError: Error code: 429", "infra"),
    ("APIConnectionError: Connection error.", "infra"),
    ("ea: ValueError: cannot convert float NaN to integer", "other"),
    ("", "other"),
    (None, "other"),
    # the false positive caught on real data: a column number that looks like an HTTP 5xx
    ("agent: CypherSyntaxError: {code: Neo.ClientError.Statement.SyntaxError} {message: Type mismatch: "
     "expected Float, Integer or String but was List<T> (line 1, column 536 (offset: 535))", "agent"),
    ("agent: CypherSyntaxError: ... (line 1, column 429 (offset: 428))", "agent"),   # 429 inside a Cypher message
    ("agent: ClientError: {code: Neo.ClientError.Procedure.ProcedureCallFailed} {message: x}", "agent"),
    ("gold: ClientError: {code: Neo.ClientError.Statement.ArithmeticError} {message: / by zero}", "gold"),
    ("Error code: 503 - {'error': {'message': 'overloaded'}}", "infra"),
    ("HTTP 502 Bad Gateway", "infra"),
    ("httpx.ReadTimeout: timed out", "infra"),
    # Neo4j-side infrastructure: transient / session errors are not statement errors
    ("agent: TransientError: {code: Neo.TransientError.General.DatabaseUnavailable} {message: x}", "infra"),
    ("neo4j.exceptions.SessionExpired: Failed to read from defunct connection", "infra"),
    ("neo4j.exceptions.ServiceUnavailable: Unable to retrieve routing information", "infra"),
])
def test_classify_error(error, kind):
    assert osw.classify_error(error) == kind


# ── ⚠ flagging on real-shaped cells ───────────────────────────────────────────

def _cell(n, errors, complete=True):
    """A cell whose records carry the given error strings (rest succeed)."""
    recs = [{"qid": f"q{i}", "ea": None, "error": e} for i, e in enumerate(errors)]
    recs += [{"qid": f"ok{i}", "ea": True, "psjs": 1.0} for i in range(n - len(errors))]
    return {"dir": "x", "n": n, "err": len(errors), "expected": n, "complete": complete,
            "records": recs, "breakdown": osw.error_breakdown(recs), "suspect": False, "why": ""}


GOLD = "gold: CypherSyntaxError: {code: Neo.ClientError.Statement.SyntaxError} {message: 'distance"
AGENT = "agent: CypherSyntaxError: {code: Neo.ClientError.Statement.SyntaxError} {message: Function"
TIMEOUT = "example timeout: exceeded 900s"


def test_zog_cyanchor_861_timeouts_is_flagged_and_peers_are_not():
    """The incident: ZOGRASCOPE × cyanchor errored on 861/1290 while the other
    methods on the same graph errored on <10."""
    cells = {
        ("zograscope_augmented", "pole", "cyanchor"):    _cell(1290, [TIMEOUT] * 861),
        ("zograscope_augmented", "pole", "react"):       _cell(1290, [TIMEOUT] * 383),
        ("zograscope_augmented", "pole", "fcav"):        _cell(1290, [AGENT] * 9),
        ("zograscope_augmented", "pole", "graphrag"):    _cell(1290, [AGENT] * 10),
        ("zograscope_augmented", "pole", "no_val_link"): _cell(1290, [AGENT] * 3),
    }
    osw.flag_suspects(cells)
    assert cells[("zograscope_augmented", "pole", "cyanchor")]["suspect"]
    assert cells[("zograscope_augmented", "pole", "react")]["suspect"]
    for m in ("fcav", "graphrag", "no_val_link"):
        assert not cells[("zograscope_augmented", "pole", m)]["suspect"], m


def test_mtq_data_and_model_errors_never_flag():
    """MindTheQuery in the gpt-4.1 reference: 79 gold-side failures shared by
    every method plus model-side syntax errors — no infrastructure. Nothing
    may be flagged, even at 19% for no_val_link."""
    cells = {
        ("mindthequery_augmented", "covid", "no_val_link"): _cell(342, [GOLD] * 59 + [AGENT] * 133),  # 192
        ("mindthequery_augmented", "covid", "fcav"):        _cell(342, [GOLD] * 59 + [AGENT] * 140),  # 199
        ("mindthequery_augmented", "covid", "react"):       _cell(342, [GOLD] * 59),
        ("mindthequery_augmented", "covid", "graphrag"):    _cell(342, [GOLD] * 59),
        ("mindthequery_augmented", "covid", "cyanchor"):    _cell(342, [GOLD] * 59),
    }
    osw.flag_suspects(cells)
    assert not any(c["suspect"] for c in cells.values())


def test_small_infra_spillover_on_one_method_is_caught():
    """luna on MindTheQuery: cyanchor 116 errors where react/graphrag had 71 —
    the extra 45 are timeouts. 9.5% overall would pass any rate threshold;
    the type rule catches it."""
    cells = {
        ("mindthequery_augmented", "covid", "cyanchor"): _cell(1222, [GOLD] * 59 + [AGENT] * 12 + [TIMEOUT] * 45),
        ("mindthequery_augmented", "covid", "react"):    _cell(1222, [GOLD] * 59 + [AGENT] * 12),
        ("mindthequery_augmented", "covid", "graphrag"): _cell(1222, [GOLD] * 59 + [AGENT] * 12),
    }
    osw.flag_suspects(cells)
    assert cells[("mindthequery_augmented", "covid", "cyanchor")]["suspect"]
    assert not cells[("mindthequery_augmented", "covid", "react")]["suspect"]


def test_a_couple_of_timeouts_on_a_small_graph_do_not_flag():
    cells = {("mindthequery_augmented", "bloom", "cyanchor"): _cell(40, [TIMEOUT] * 2),
             ("mindthequery_augmented", "bloom", "react"):    _cell(40, [])}
    osw.flag_suspects(cells)
    assert not cells[("mindthequery_augmented", "bloom", "cyanchor")]["suspect"]


def test_unclassified_errors_flag_only_when_lopsided():
    weird = "SomethingNew: boom"
    lopsided = {("cypherbench_augmented", "movie", "cyanchor"): _cell(360, [weird] * 120),   # 33%
                ("cypherbench_augmented", "movie", "react"):    _cell(360, [AGENT] * 4)}        # 1.1%
    osw.flag_suspects(lopsided)
    assert lopsided[("cypherbench_augmented", "movie", "cyanchor")]["suspect"]
    uniform = {("cypherbench_augmented", "movie", "cyanchor"): _cell(360, [weird] * 120),
               ("cypherbench_augmented", "movie", "react"):    _cell(360, [weird] * 110)}
    osw.flag_suspects(uniform)
    assert not uniform[("cypherbench_augmented", "movie", "cyanchor")]["suspect"]


def test_clean_reference_pole_is_not_flagged():
    cells = {("zograscope_augmented", "pole", "cyanchor"): _cell(1441, [])}
    osw.flag_suspects(cells)
    assert not cells[("zograscope_augmented", "pole", "cyanchor")]["suspect"]


# ── worktree publish: the two traps ───────────────────────────────────────────

def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def scratch_repo(tmp_path):
    """A repo on `main` with a bare origin, mimicking a runner's clone."""
    origin = tmp_path / "origin.git"
    _git("init", "-q", "--bare", str(origin), cwd=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / ".gitignore").write_text("logs/\n")
    (repo / "eval_config.py").write_text("GENERATOR_LLM = 'm'\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "base", cwd=repo)
    _git("remote", "add", "origin", str(origin), cwd=repo)
    _git("push", "-q", "-u", "origin", "main", cwd=repo)
    return repo, origin


def _write_run(repo, name, content):
    d = repo / "logs" / "runs" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "records.jsonl").write_text(content)
    return f"logs/runs/{name}"


def test_publish_twice_after_main_moves_fast_forwards_and_leaves_tree_alone(scratch_repo):
    repo, origin = scratch_repo
    branch = "sweep/m"
    r1 = _write_run(repo, "ds__g__m@m__20260101-000000", '{"r":1}\n')
    (repo / "report" / "m").mkdir(parents=True)
    (repo / "report" / "m" / "SWEEP.md").write_text("v1")

    outcome, sha1 = osw._publish_tree(repo, branch, [r1], ["report/m", "eval_config.py"],
                                      mirror_roots=["logs/runs", "report/m"], message="publish 1")
    assert outcome == "pushed"
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"          # trap 6: never switched
    assert (repo / r1 / "records.jsonl").exists()                                   # run dir untouched
    assert _git("ls-remote", "--heads", "origin", branch, cwd=repo)                 # branch is on origin

    # the runner pulls a newer main (docs/driver update), then publishes again with one more cell
    (repo / "README.md").write_text("new doc\n")
    _git("add", "README.md", cwd=repo); _git("commit", "-q", "-m", "main moved", cwd=repo)
    r2 = _write_run(repo, "ds__g2__m@m__20260102-000000", '{"r":2}\n')
    (repo / "report" / "m" / "SWEEP.md").write_text("v2")

    outcome, sha2 = osw._publish_tree(repo, branch, [r1, r2], ["report/m", "eval_config.py"],
                                      mirror_roots=["logs/runs", "report/m"], message="publish 2")
    assert outcome == "pushed" and sha2 != sha1                                     # trap 7: not rejected
    remote_tip = _git("rev-parse", f"origin/{branch}", cwd=repo)
    assert _git("merge-base", "--is-ancestor", sha1, remote_tip, cwd=repo) == ""    # history kept (fast-forward)
    files = _git("ls-tree", "-r", "--name-only", remote_tip, cwd=repo).splitlines()
    assert f"{r1}/records.jsonl" in files and f"{r2}/records.jsonl" in files
    assert _git("show", f"{remote_tip}:report/m/SWEEP.md", cwd=repo) == "v2"        # tree mirrors disk
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo) == "main"
    assert not _git("worktree", "list", "--porcelain", cwd=repo).count("worktree") > 1  # tmp worktree cleaned


def test_publish_with_nothing_new_reports_unchanged(scratch_repo):
    repo, _ = scratch_repo
    r1 = _write_run(repo, "ds__g__m@m__20260101-000000", '{"r":1}\n')
    osw._publish_tree(repo, "sweep/m", [r1], ["eval_config.py"], mirror_roots=["logs/runs"], message="p1")
    outcome, _ = osw._publish_tree(repo, "sweep/m", [r1], ["eval_config.py"], mirror_roots=["logs/runs"], message="p2")
    assert outcome == "unchanged"


def test_mirror_drops_run_dirs_that_no_longer_exist_locally(scratch_repo):
    """A re-run supersedes an old stamped dir; if the runner deleted the old one,
    the published tree must not keep resurrecting it."""
    repo, _ = scratch_repo
    old = _write_run(repo, "ds__g__m@m__20260101-000000", '{"r":1}\n')
    osw._publish_tree(repo, "sweep/m", [old], ["eval_config.py"], mirror_roots=["logs/runs"], message="p1")
    import shutil
    shutil.rmtree(repo / old)
    new = _write_run(repo, "ds__g__m@m__20260102-000000", '{"r":2}\n')
    osw._publish_tree(repo, "sweep/m", [new], ["eval_config.py"], mirror_roots=["logs/runs"], message="p2")
    files = _git("ls-tree", "-r", "--name-only", "origin/sweep/m", cwd=repo).splitlines()
    assert f"{new}/records.jsonl" in files and f"{old}/records.jsonl" not in files


@pytest.mark.parametrize("stderr, kind", [
    ("remote: Permission to o/r.git denied to x.\nfatal: unable to access ... 403", "access"),
    ("! [rejected] sweep/m -> sweep/m (non-fast-forward)", "moved"),
    ("fatal: unable to access 'https://github.com/': Could not resolve host", "network"),
    ("something else entirely", "unknown"),
])
def test_classify_push_failure(stderr, kind):
    assert osw._classify_push_failure(stderr) == kind


@pytest.mark.parametrize("url, expect", [
    ("https://github.com/receive2/text2cypher_agent.git", "https://github.com/receive2/text2cypher_agent"),
    ("https://github.com/receive2/text2cypher_agent", "https://github.com/receive2/text2cypher_agent"),
    ("git@github.com:receive2/text2cypher_agent.git", "https://github.com/receive2/text2cypher_agent"),
    ("ssh://git@github.com/receive2/text2cypher_agent.git", "https://github.com/receive2/text2cypher_agent"),
])
def test_remote_https_url(monkeypatch, url, expect):
    monkeypatch.setattr(osw, "_git", lambda *a: url)
    assert osw._remote_https_url() == expect


# ── the run loop's per-cell decision (resume semantics) ──────────────────────

def _decided(complete, suspect, reruns, manual):
    c = {"complete": complete, "suspect": suspect, "n": 10, "err": 0, "why": "w"}
    return osw.decide_cell(c, {"suspect_reruns": reruns}, manual)[0]


def test_clean_cell_is_skipped():
    assert _decided(True, False, 0, False) == "skip"


def test_truncated_cell_always_runs_even_when_flagged_and_budget_spent():
    """A killed re-run leaves a truncated dir whose partial records may still be
    infra-dominated; it must go back to run_cell, never be parked as persistent."""
    assert _decided(False, False, 0, False) == "run"
    assert _decided(False, True, osw.SUSPECT_RERUN_MAX, False) == "run"


def test_flagged_complete_cell_uses_the_budget_then_parks():
    assert _decided(True, True, 0, False) == "rerun"
    assert _decided(True, True, osw.SUSPECT_RERUN_MAX - 1, False) == "rerun"
    assert _decided(True, True, osw.SUSPECT_RERUN_MAX, False) == "persistent"


def test_explicit_selection_reruns_a_parked_cell():
    """The Flagged-cells section tells the runner to use --graphs/--methods; that
    must work even after the automatic budget is spent."""
    assert _decided(True, True, osw.SUSPECT_RERUN_MAX, True) == "rerun"


def test_missing_budget_key_is_treated_as_zero():
    c = {"complete": True, "suspect": True, "n": 10, "err": 5, "why": "w"}
    assert osw.decide_cell(c, {"tries": 0}, False)[0] == "rerun"


# ── state files: smoke never touches the full run's history ──────────────────

def test_smoke_state_file_is_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(osw, "REPO", tmp_path)
    expected = {("cypherbench_augmented", "flight_accident"): 3}
    smoke = osw.load_state("m", expected, smoke=True)
    smoke["cells"]["cypherbench_augmented__flight_accident__react"] = {"tries": 3, "suspect_reruns": 2}
    osw.save_state(smoke)
    full = osw.load_state("m", {("cypherbench_augmented", "flight_accident"): 500})
    assert full["cells"] == {}                       # smoke tries do not consume the full run's budget
    assert full["expected"]["cypherbench_augmented__flight_accident"] == 500
    assert osw.state_path("m", True) != osw.state_path("m")
    assert osw.state_path("m", True).is_file() and not osw.state_path("m").is_file()
    osw.save_state(full)
    assert osw.state_path("m").is_file()


# ── third review pass: peers, gold-free reference, truncated cells, smoke guard, pasted commands ──

def test_rule2_reference_ignores_the_shared_gold_failures():
    """MindTheQuery graphs carry ~17% gold failures on EVERY method. A cell whose
    unclassified errors are lopsided against its peers must still be flagged —
    the peers' gold failures are the data, not a reference error rate."""
    weird = "SomethingNew: boom"
    cells = {("mindthequery_augmented", "covid", "cyanchor"): _cell(342, [GOLD] * 59 + [weird] * 120),   # 35% unclassified
             ("mindthequery_augmented", "covid", "react"):    _cell(342, [GOLD] * 59),
             ("mindthequery_augmented", "covid", "graphrag"): _cell(342, [GOLD] * 59 + [AGENT] * 4)}
    osw.flag_suspects(cells)
    assert cells[("mindthequery_augmented", "covid", "cyanchor")]["suspect"]
    assert "beyond the shared gold failures" in cells[("mindthequery_augmented", "covid", "cyanchor")]["why"]
    for m in ("react", "graphrag"):
        assert not cells[("mindthequery_augmented", "covid", m)]["suspect"], m


def test_truncated_cells_are_missing_not_flagged():
    """⚠ implies complete: a truncated dir full of timeouts is ✗ and re-run
    unconditionally; it must not also be counted and listed as ⚠."""
    cells = {("zograscope_augmented", "pole", "cyanchor"): _cell(900, [TIMEOUT] * 400, complete=False),
             ("zograscope_augmented", "pole", "react"):    _cell(1290, [])}
    osw.flag_suspects(cells)
    assert not cells[("zograscope_augmented", "pole", "cyanchor")]["suspect"]


def test_smoke_cannot_be_published():
    for argv in (["--smoke", "--publish"], ["--smoke", "--publish", "--allow-incomplete"]):
        with pytest.raises(SystemExit):
            osw.main(argv)


def test_pasted_commands_carry_skip_methods(monkeypatch):
    monkeypatch.setattr(osw, "SKIPPED_METHODS", ["react"])
    assert osw._cmd() == "python orchestrate_sweep.py --skip-methods react"
    assert osw._cmd("--graphs pole --methods cyanchor") == \
        "python orchestrate_sweep.py --graphs pole --methods cyanchor --skip-methods react"
    parked = {"complete": True, "suspect": True, "n": 1, "err": 1, "why": "w"}
    assert "--skip-methods react" in osw.decide_cell(parked, {"suspect_reruns": osw.SUSPECT_RERUN_MAX}, False)[1]
    monkeypatch.setattr(osw, "SKIPPED_METHODS", [])
    assert osw._cmd("--status") == "python orchestrate_sweep.py --status"


def test_rerun_that_produces_no_run_dir_is_not_reported_done(tmp_path, monkeypatch):
    """eval_run can stop before creating a run dir (archive refused, config
    error). The newest dir is then the PREVIOUS complete run; run_cell must not
    report that as this attempt's result."""
    import eval_config as cfg
    import eval_run
    monkeypatch.setattr(osw, "REPO", tmp_path)
    monkeypatch.setattr(osw, "save_state", lambda st: None)
    for k in ("METHOD", "EVAL_PAIRS", "LIMIT", "OUT_DIR", "VERBOSE", "SHARDS"):
        monkeypatch.setattr(cfg, k, getattr(cfg, k, None), raising=False)
    old = tmp_path / "logs" / "x" / f"cypherbench_augmented__movie__{osw.method_seg('react')}@m1__20260101-000000"
    old.mkdir(parents=True)
    (old / "records.jsonl").write_text('{"ea": null, "error": "example timeout: exceeded 900s"}\n' * 3)
    monkeypatch.setattr(eval_run, "main", lambda: 3)            # refuses; creates nothing
    state = {"model": "m1", "cells": {}, "expected": {"cypherbench_augmented__movie": 3}}
    c = osw.run_cell("cypherbench_augmented", "movie", "react", limit=None, out_dir="logs/x",
                     user_shards=1, model="m1", state=state)
    entry = state["cells"]["cypherbench_augmented__movie__react"]
    assert entry["status"] == "failed" and "no run directory" in entry["last_error"]
    assert entry["tries"] == osw.MAX_TRIES
    assert c["complete"] and "finished_at" not in entry           # the old dir is still on disk, but it is not 'done'
