# -*- coding: utf-8 -*-
"""component_names.py — the paper's name of a component is an alias of its switch:
both names set one value, and a run records the switch name only."""
from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import component_names as cn          # noqa: E402
import eval_config as cfg             # noqa: E402
import eval_run                       # noqa: E402
import scripts.audit_runs as ar       # noqa: E402

PAIRS = sorted(cn.ALIAS_OF.items())   # (switch, alias)


def _knobs(env):
    return {k: env[k] for k in (*eval_run._STR, *eval_run._BOOL, *eval_run._INT, *eval_run._TUPLE) if k in env}


# ── the eval_config panel ─────────────────────────────────────────────────────

@pytest.mark.parametrize("switch,alias", PAIRS)
def test_the_panel_has_one_value_per_switch(switch, alias, monkeypatch):
    assert getattr(cfg, switch) is getattr(cfg, alias)
    off = not getattr(cfg, alias)
    monkeypatch.setattr(cfg, switch, off)                  # what a driver written before the aliases does
    assert getattr(cfg, alias) is off and getattr(cfg, switch) is off
    monkeypatch.setattr(cfg, alias, not off)
    assert getattr(cfg, switch) is (not off)
    assert not (switch in vars(cfg) and alias in vars(cfg))   # never two stored values


@pytest.mark.parametrize("switch,alias", PAIRS)
def test_a_run_records_the_switch_name_whichever_name_was_set(switch, alias, monkeypatch):
    for name in (switch, alias):
        monkeypatch.setattr(cfg, name, False)
        env = eval_run._build_env("bolt://x", "u", "p", "neo4j")
        assert env[switch] == "0" and alias not in env
        monkeypatch.setattr(cfg, name, True)
        assert eval_run._build_env("bolt://x", "u", "p", "neo4j")[switch] == "1"


def test_recorded_knobs_keep_the_names_older_runs_recorded():
    """The audit compares a run's recorded knobs with the committed ones key by key, so the
    keys must stay the switch names: an alias in the summary would be a knob no older run has."""
    knobs = _knobs(eval_run._build_env("bolt://x", "u", "p", "neo4j"))
    assert set(cn.ALIAS_OF) <= set(knobs)
    assert not set(cn.SWITCH_OF) & set(knobs)
    assert ar.committed_knobs() == knobs


def test_the_audit_names_a_changed_component_by_its_switch(monkeypatch):
    recorded = ar.committed_knobs()                       # a run made under the committed configuration
    assert ar.config_mismatch("cyanchor", recorded, ar.committed_knobs()) == ""
    monkeypatch.setattr(cfg, "VALUE_EXISTENCE_GUARD", False)   # the committed panel now differs from that run
    assert ar.config_mismatch("cyanchor", recorded, ar.committed_knobs()) == "PLAN_EXEC_VALUE_SNAP=1 (committed 0)"


def _panel(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    sys.modules[name] = module
    return module


def test_a_panel_file_with_both_names_of_a_switch():
    try:
        same = _panel("_panel_same", ADAPTIVE_SEARCH_CONTROL=False, PLAN_EXEC_ESCALATE=False)
        cn.unify_panel("_panel_same")
        assert "PLAN_EXEC_ESCALATE" not in vars(same) and same.PLAN_EXEC_ESCALATE is False
        _panel("_panel_differ", ADAPTIVE_SEARCH_CONTROL=True, PLAN_EXEC_ESCALATE=False)
        with pytest.raises(ValueError, match="two names of one switch"):
            cn.unify_panel("_panel_differ")
    finally:
        sys.modules.pop("_panel_same", None); sys.modules.pop("_panel_differ", None)


def test_a_panel_file_written_with_the_switch_names():
    """An eval_config.py from before the aliases (or a private copy of one) keeps working."""
    try:
        old = _panel("_panel_old", PLAN_EXEC_ESCALATE=True, RETRIEVAL_FUZZY=False)
        cn.unify_panel("_panel_old")
        assert old.ADAPTIVE_SEARCH_CONTROL is True and old.TOKEN_LEVEL_FUZZY_MATCH is False
        old.ADAPTIVE_SEARCH_CONTROL = False
        assert old.PLAN_EXEC_ESCALATE is False and "ADAPTIVE_SEARCH_CONTROL" not in vars(old)
        assert cn.panel_get(old, "PLAN_EXEC_ESCALATE") is False and cn.panel_get(old, "RETRIEVAL_FUZZY") is False
        with pytest.raises(AttributeError):
            old.LEVENSHTEIN_RETRIEVAL                      # neither name is set on this panel
    finally:
        sys.modules.pop("_panel_old", None)


def test_an_object_standing_in_for_the_panel():
    ns = types.SimpleNamespace
    assert cn.panel_get(ns(ADAPTIVE_SEARCH_CONTROL=False), "PLAN_EXEC_ESCALATE") is False
    assert cn.panel_get(ns(PLAN_EXEC_ESCALATE=True), "PLAN_EXEC_ESCALATE") is True
    assert cn.panel_get(ns(), "PLAN_EXEC_ESCALATE") is None
    assert cn.panel_get(ns(PLAN_EXEC_SELECT_JUDGE=True), "PLAN_EXEC_SELECT_JUDGE") is True     # a switch without an alias
    with pytest.raises(ValueError, match="two names of one switch"):
        cn.panel_get(ns(ADAPTIVE_SEARCH_CONTROL=True, PLAN_EXEC_ESCALATE=False), "PLAN_EXEC_ESCALATE")


# ── the environment ───────────────────────────────────────────────────────────

def test_a_flag_is_read_under_either_name():
    assert cn.env_flag("PLAN_EXEC_ESCALATE", "1", {}) is True
    assert cn.env_flag("PLAN_EXEC_ESCALATE", "0", {}) is False
    assert cn.env_flag("PLAN_EXEC_ESCALATE", "1", {"PLAN_EXEC_ESCALATE": "0"}) is False
    assert cn.env_flag("PLAN_EXEC_ESCALATE", "1", {"ADAPTIVE_SEARCH_CONTROL": "0"}) is False
    assert cn.env_flag("PLAN_EXEC_ESCALATE", "0", {"ADAPTIVE_SEARCH_CONTROL": "true"}) is True
    assert cn.env_flag("PLAN_EXEC_ESCALATE", "1", {"PLAN_EXEC_ESCALATE": "1", "ADAPTIVE_SEARCH_CONTROL": "yes"}) is True
    with pytest.raises(ValueError, match="two names of one switch"):
        cn.env_flag("PLAN_EXEC_ESCALATE", "1", {"PLAN_EXEC_ESCALATE": "1", "ADAPTIVE_SEARCH_CONTROL": "0"})


def test_an_alias_in_the_environment_becomes_its_switch():
    env = {"VALUE_EXISTENCE_GUARD": "0", "LEVENSHTEIN_RETRIEVAL": "true", "RETRIEVAL_LEVENSHTEIN": "1", "PATH": "/bin"}
    cn.normalize_env(env)
    assert env == {"PLAN_EXEC_VALUE_SNAP": "0", "RETRIEVAL_LEVENSHTEIN": "1", "PATH": "/bin"}
    with pytest.raises(ValueError, match="two names of one switch"):
        cn.normalize_env({"TOKEN_LEVEL_FUZZY_MATCH": "0", "RETRIEVAL_FUZZY": "1"})


def test_the_panel_wins_over_a_shell_export_under_either_name(monkeypatch):
    monkeypatch.setenv("ADAPTIVE_SEARCH_CONTROL", "0")
    monkeypatch.setenv("CYPHER_SEMANTIC_REPAIR", "0")
    env = eval_run._build_env("bolt://x", "u", "p", "neo4j")
    assert env["PLAN_EXEC_ESCALATE"] == "1" and env["CYPHER_SEMANTIC_REPAIR"] == "1"
    assert not set(cn.SWITCH_OF) & set(env)


def test_a_switch_the_panel_leaves_unset_takes_the_shell_export(monkeypatch):
    monkeypatch.setattr(cfg, "ADAPTIVE_SEARCH_CONTROL", None)
    monkeypatch.setenv("ADAPTIVE_SEARCH_CONTROL", "0")
    monkeypatch.delenv("PLAN_EXEC_ESCALATE", raising=False)
    env = eval_run._build_env("bolt://x", "u", "p", "neo4j")
    assert env["PLAN_EXEC_ESCALATE"] == "0" and "ADAPTIVE_SEARCH_CONTROL" not in env


def _config_flags(**extra_env):
    """config.py's five component switches as a fresh interpreter resolves them."""
    env = {k: v for k, v in os.environ.items() if k not in cn.ALIAS_OF and k not in cn.SWITCH_OF}
    code = "import config; print(*[int(getattr(config, s)) for s in %r])" % (sorted(cn.ALIAS_OF),)
    return subprocess.run([sys.executable, "-c", code], cwd=REPO, env={**env, **extra_env}, text=True, capture_output=True)


def test_config_reads_a_switch_from_either_variable():
    assert _config_flags().stdout.split() == ["1"] * 5
    switches = sorted(cn.ALIAS_OF)
    for switch in switches:
        for name in (switch, cn.ALIAS_OF[switch]):
            want = ["0" if s == switch else "1" for s in switches]
            assert _config_flags(**{name: "0"}).stdout.split() == want, name
    clash = _config_flags(PLAN_EXEC_VALUE_SNAP="1", VALUE_EXISTENCE_GUARD="0")
    assert clash.returncode != 0 and "two names of one switch" in clash.stderr


# ── names ─────────────────────────────────────────────────────────────────────

def test_aliases_and_switches_do_not_collide():
    assert len(cn.SWITCH_OF) == len(cn.ALIAS_OF) == 5
    assert not set(cn.SWITCH_OF) & set(cn.ALIAS_OF)
    recorded = set((*eval_run._STR, *eval_run._BOOL, *eval_run._INT, *eval_run._TUPLE))
    assert set(cn.ALIAS_OF) <= recorded and not set(cn.SWITCH_OF) & recorded
    for alias in cn.SWITCH_OF:                             # the audit takes a recorded CyANCHOR knob by its prefix
        assert not alias.startswith(ar.CYANCHOR_KNOB_PREFIXES)


def test_ablation_cells_and_their_aliases():
    assert cn.cell_name("no_levenshtein_retrieval") == "fuzzy_only"
    assert cn.cell_name("no_token_level_fuzzy_match") == "lev_only"
    assert cn.cell_name("no_adaptive_search_control") == "no_escalate"
    assert cn.cell_name("fuzzy_only") == "fuzzy_only" and cn.cell_name("reference") == "reference"
    driver = (REPO / "scripts" / "tuning" / "run_ablation_model.py").read_text(encoding="utf-8")
    for cell, alias in cn.CELL_ALIAS.items():
        assert f'"{cell}": {{' in driver, cell             # every aliased cell is a cell of the driver
        assert alias in driver                             # and its docstring lists the alias
    assert not set(cn.CELL_ALIAS) & set(cn.CELL_ALIAS.values())
