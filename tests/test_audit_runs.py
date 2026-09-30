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


def _run(root: Path, dataset, graph, method, model, stamp, rows, knobs="committed"):
    """A run directory as eval_run leaves it: records plus a summary.json that records the knobs
    (the committed ones unless *knobs* is a dict, or None for a run with no summary at all)."""
    d = root / "logs" / "runs" / f"{dataset}__{graph}__{osw.method_seg(method)}@{model}__{stamp}"
    d.mkdir(parents=True)
    (d / "records.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    if knobs is not None:
        k = ar.committed_knobs() if knobs == "committed" else knobs
        (d / "summary.json").write_text(json.dumps({"run_config": {"knobs": k}}), encoding="utf-8")
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


def test_cyanchor_run_under_another_configuration_is_deleted(world):
    """The released configuration is the complete design (judge on, node + relation tools). A cyanchor
    run made under the reduced configuration that main carried from 2026-09-28 to 2026-09-30 (judge off,
    node tools) has the same directory name; only its recorded knobs tell, and they make it DELETE."""
    guard = datetime(2026, 9, 10, 18, 29)
    committed = ar.committed_knobs()
    assert committed["PLAN_EXEC_SELECT_JUDGE"] == "1" and committed["CYANCHOR_TOOL_SCOPE"] == "node_rel"
    N1 = [{"qid": "n1", "question": "q1", "ea": True}]
    reduced = dict(committed); reduced["PLAN_EXEC_SELECT_JUDGE"] = "0"; reduced["CYANCHOR_TOOL_SCOPE"] = "node"
    a = _run(world, "cypherbench_augmented", "movie", "cyanchor", "m1", "20260929-100000", OK, reduced)    # reduced configuration
    b = _run(world, "cypherbench_augmented", "movie", "cyanchor", "m1", "20260930-120000", OK)             # committed knobs
    c = _run(world, "cypherbench_augmented", "nba", "cyanchor", "m1", "20260929-120000", N1, None)         # no summary at all
    d = _run(world, "cypherbench_augmented", "nba", "graphrag", "m1", "20260920-120000", N1, None)         # baseline without tools: knobs not checked
    # before f04a37c there was no CYANCHOR_TOOL_SCOPE: TOOL_TYPE set the scope of CyANCHOR too
    early = dict(committed); early.pop("CYANCHOR_TOOL_SCOPE"); early["TOOL_TYPE"] = "node_rel"
    e = _run(world, "cypherbench_augmented", "nba", "cyanchor", "m1", "20260924-120000", N1, early)        # same system as the committed one
    early_node = dict(early); early_node["TOOL_TYPE"] = "node"
    f = _run(world, "cypherbench_augmented", "nba", "cyanchor", "m1", "20260925-120000", N1, early_node)   # its node-only variant
    v = {r["dir"].name: r for r in ar.audit(world / "logs" / "runs", "m1", False, guard)}
    assert v[a.name]["verdict"] == "DELETE"
    assert "PLAN_EXEC_SELECT_JUDGE=0 (committed 1)" in v[a.name]["reason"]
    assert "CYANCHOR_TOOL_SCOPE=node (committed node_rel)" in v[a.name]["reason"]
    assert v[b.name]["verdict"] == "keep"
    assert v[c.name]["verdict"] == "DELETE" and "no summary.json" in v[c.name]["reason"]
    assert v[d.name]["verdict"] == "keep"
    assert ar.cyanchor_config_mismatch(early, committed) == ""                # usable: not DELETE, only superseded by newer dirs
    assert v[e.name]["verdict"] == "older"
    assert v[f.name]["verdict"] == "DELETE" and "tool scope node (recorded as TOOL_TYPE; committed node_rel)" in v[f.name]["reason"]


def test_react_run_under_another_tool_scope_is_deleted(world):
    """The ReAct baseline grounds over the same tool set as CyANCHOR (TOOL_TYPE = node_rel). A run over
    the node tools only has the same ``react`` directory name; its recorded TOOL_TYPE tells."""
    guard = datetime(2026, 9, 10, 18, 29)
    committed = ar.committed_knobs()
    assert committed["TOOL_TYPE"] == "node_rel"
    old = dict(committed); old["TOOL_TYPE"] = "node"
    a = _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260929-100000", OK, old)          # node tools only
    b = _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260929-120000", OK)               # committed scope
    c = _run(world, "cypherbench_augmented", "nba", "react", "m1", "20260929-120000",
             [{"qid": "n1", "question": "q1", "ea": True}], None)                                  # no summary at all
    unstamped = dict(committed); unstamped.pop("TOOL_TYPE")
    d = _run(world, "cypherbench_augmented", "nba", "react", "m1", "20260929-130000",
             [{"qid": "n1", "question": "q1", "ea": True}], unstamped)                             # scope not recorded
    e = _run(world, "cypherbench_augmented", "nba", "cyanchor", "m1", "20260929-120000",
             [{"qid": "n1", "question": "q1", "ea": True}], old)                                   # cyanchor with its own scope knob recorded: TOOL_TYPE irrelevant
    v = {r["dir"].name: r for r in ar.audit(world / "logs" / "runs", "m1", False, guard)}
    assert v[a.name]["verdict"] == "DELETE" and "TOOL_TYPE=node (committed node_rel)" in v[a.name]["reason"]
    assert "ReAct tool scope" in v[a.name]["reason"]
    assert v[b.name]["verdict"] == "keep"
    assert v[c.name]["verdict"] == "DELETE" and "no summary.json" in v[c.name]["reason"]
    assert v[d.name]["verdict"] == "DELETE" and "TOOL_TYPE not recorded" in v[d.name]["reason"]
    assert v[e.name]["verdict"] == "keep"


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
    legacy = runs / "cypherbench_augmented__movie__react__20260908-120000"; legacy.mkdir()        # old layout, no summary.json: nobody's → also gone
    (legacy / "records.jsonl").write_text("")
    seen = []
    assert ar.discard_all("m1", runs, logs, lambda paths: (seen.extend(paths), False)[1]) == []   # declined: nothing happens
    assert d1.exists() and d2.exists() and legacy.exists() and (runs / "report_20260918_195430.md").exists()
    assert {p.name for p in seen} == {d1.name, d2.name, legacy.name, "report_20260918_195430.md", "sweep_m1.json", "sweep_m1_smoke.json"}
    gone = ar.discard_all("m1", runs, logs, lambda paths: True)
    assert {p.name for p in gone} == {p.name for p in seen}
    assert not d1.exists() and not d2.exists() and d3.exists() and not legacy.exists()
    assert not (logs / "sweep_m1.json").exists() and (logs / "sweep_m2.json").exists()
    assert ar.discard_all("m1", runs, logs, lambda paths: True) == []                         # nothing left to delete


def test_discard_all_cli_refuses_without_a_terminal_and_without_yes(world, monkeypatch, capsys):
    _run(world, "cypherbench_augmented", "movie", "react", "gpt-5.6-luna", "20260916-120000", OK)   # a real preset: the CLI checks the name
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert ar.main(["--model", "gpt-5.6-luna", "--discard-all"]) == 0
    assert "nothing deleted" in capsys.readouterr().out
    assert (world / "logs" / "runs").iterdir().__next__().exists()
    assert ar.main(["--model", "gpt-5.6-luna", "--discard-all", "--yes"]) == 0
    assert "deleted 1 item(s)" in capsys.readouterr().out


def test_discard_all_never_infers_the_model_from_eval_config(world, capsys):
    _run(world, "cypherbench_augmented", "movie", "react", "m1", "20260916-120000", OK)
    with pytest.raises(SystemExit) as exc:
        ar.main(["--discard-all", "--yes"])          # no --model: refused before anything is touched
    assert exc.value.code == 2
    assert next((world / "logs" / "runs").iterdir()).exists()


def test_a_mistyped_model_name_is_refused_with_the_list(world, capsys):
    _run(world, "cypherbench_augmented", "movie", "react", "gpt-5.6-luna", "20260916-120000", OK)
    with pytest.raises(SystemExit) as exc:
        ar.main(["--discard-all", "--yes", "--model", "gpt-5.6-lunna"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not a model preset" in err and "gpt-5.6-luna" in err
    assert next((world / "logs" / "runs").iterdir()).exists()


def test_every_model_in_the_handout_is_a_preset():
    import re, config
    text = (Path(__file__).resolve().parent.parent / "docs" / "EXPERIMENT_HANDOUT.md").read_text(encoding="utf-8")
    listed = re.findall(r"audit_runs\.py --discard-all --model (\S+)", text)
    assert len(listed) == 7 and all(m in config.MODEL_PRESETS for m in listed), listed
