#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The generator-LLM switch: one name in eval_config selects every stage, tags
the run directory, and reaches the worker through the same env channel as
METHOD. Plus the Anthropic parameter rules the sweep depends on."""
from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _load_anthropic_kwargs():
    """Pull the pure helper out of agent_helper without importing the module
    (it opens a Neo4j connection at import time)."""
    src = io.open(REPO / "agent" / "agent_helper.py", encoding="utf-8").read()
    import typing
    ns = {"re": re, "Optional": typing.Optional}
    for n in ast.parse(src).body:
        if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_NO_SAMPLING_PARAMS") or \
           (isinstance(n, ast.FunctionDef) and n.name == "_anthropic_generation_kwargs"):
            exec(ast.get_source_segment(src, n), ns)
    return ns["_anthropic_generation_kwargs"]


@pytest.mark.parametrize("model,no_temp,thinking_off", [
    ("claude-opus-5", True, True),
    ("claude-sonnet-5", True, True),
    ("claude-opus-4-8", True, True),
    ("claude-sonnet-4-6", True, True),
    ("claude-fable-5-1", True, True),
    ("claude-haiku-4-5", False, False),
    ("claude-opus-4-20250514", False, False),
])
def test_anthropic_kwargs_follow_the_model_generation(model, no_temp, thinking_off):
    kw = _load_anthropic_kwargs()(model, 0)
    assert ("temperature" not in kw) == no_temp
    assert (kw.get("model_kwargs", {}).get("thinking") == {"type": "disabled"}) == thinking_off
    assert kw["max_tokens"] >= 2048


def test_eval_run_injects_generator_llm_like_method():
    import eval_run
    assert "GENERATOR_LLM" in eval_run._STR
    assert "METHOD" in eval_run._STR


def test_control_panel_declares_a_valid_preset():
    import config
    import eval_config
    name = eval_config.GENERATOR_LLM
    assert name in config.MODEL_PRESETS, f"eval_config.GENERATOR_LLM={name!r} is not a preset"


def test_run_dir_tag_uses_the_preset_name():
    import eval_paths
    seg = eval_paths.method_tag("cyanchor", model="claude-haiku-4.5")
    assert seg == "cyanchor_fl@claude-haiku-4.5"
    assert eval_paths.split_method_seg(seg) == ("cyanchor_fl", "claude-haiku-4.5")


def test_env_holds_keys_only():
    """The convention: .env carries credentials, never model choices."""
    text = io.open(REPO / ".env.example", encoding="utf-8").read()
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key = line.split("=", 1)[0]
        assert key.endswith(("_KEY", "_TOKEN", "_ID", "_URI", "_USERNAME", "_PASSWORD", "_DATABASE")), key
    for needed in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPINFRA_API_KEY"):
        assert needed in text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def _load_openai_kwargs():
    src = io.open(REPO / "agent" / "agent_helper.py", encoding="utf-8").read()
    import typing
    ns = {"re": re, "Optional": typing.Optional}
    for n in ast.parse(src).body:
        if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in
                ("_OPENAI_REASONING_FAMILY", "_OPENAI_REASONING_EFFORT_FIELD")) or \
           (isinstance(n, ast.FunctionDef) and n.name == "_openai_generation_kwargs"):
            exec(ast.get_source_segment(src, n), ns)
    return ns["_openai_generation_kwargs"]


@pytest.mark.parametrize("model,keeps_temperature,reasoning_low", [
    ("gpt-4.1", True, False),
    ("gpt-4o", True, False),
    ("gpt-5.6-terra", False, True),
    ("gpt-5.6-luna", False, True),
    ("gpt-5", False, True),
    ("o3", False, True),
])
def test_openai_kwargs_follow_the_model_family(model, keeps_temperature, reasoning_low):
    kw = _load_openai_kwargs()(model, 0)
    assert ("temperature" in kw) == keeps_temperature
    effort = kw.get("reasoning_effort") or kw.get("model_kwargs", {}).get("reasoning_effort")
    assert (effort == "low") == reasoning_low


def test_preset_params_are_flattened_into_the_stage_config(monkeypatch):
    """A preset's "params" reach the stage config as plain keys (constructor
    kwargs), and the "params" wrapper itself never leaks through."""
    import config
    monkeypatch.setitem(config.MODEL_PRESETS, "probe-preset",
                        {"provider": "openai", "model": "gpt-4.1", "params": {"seed": 7}})
    monkeypatch.setattr(config, "GENERATOR_LLM", "probe-preset")
    stage = config._apply_llm_override({"provider": "openai", "model": "x", "temperature": 0})
    assert stage["seed"] == 7 and "params" not in stage and stage["model"] == "gpt-4.1"
    assert "params" not in config.MODEL_PRESETS["probe-preset"] or True   # resolve_preset copies; original untouched
    assert config.MODEL_PRESETS["probe-preset"]["params"] == {"seed": 7}
