#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Model scoping of run directories.

A report cell is resolved from a (dataset, graph, method) triple. Before the
generator model became part of the run-dir name, a second model's run was just
a newer stamp for that triple, so every reader silently switched to it. These
tests pin the properties that make a multi-model sweep safe:

  * a model's runs are only ever resolved for that model;
  * runs recorded before model tagging stay resolvable — but only for the model
    that actually produced them, proven from ``run_meta``;
  * the ``__`` component split that every parser depends on is unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import eval_paths


GPT, CLAUDE = "gpt-4.1", "claude-opus-5"


def _mk(root: Path, dataset: str, graph: str, seg: str, stamp: str,
        model: str | None = None) -> Path:
    d = root / f"{dataset}__{graph}__{seg}__{stamp}"
    d.mkdir(parents=True)
    meta = {"run_meta": {"cypher_llm": model}} if model else {}
    (d / "summary.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


# ── tagging ──────────────────────────────────────────────────────────────────

def test_method_tag_without_model_is_unchanged():
    assert eval_paths.method_tag("graphrag") == "graphrag"
    assert eval_paths.method_tag("cyanchor", fuzzy=True, lev=True) == "cyanchor_fl"


def test_method_tag_appends_model():
    assert eval_paths.method_tag("graphrag", model=CLAUDE) == f"graphrag@{CLAUDE}"
    assert eval_paths.method_tag("cyanchor", model=GPT) == f"cyanchor_fl@{GPT}"


def test_model_segment_never_breaks_the_component_split():
    # A model id with slashes/underscores must not introduce "__" or a path level.
    seg = eval_paths.method_tag("graphrag", model="meta-llama/Llama-3.3__70B")
    name = f"ds__graph__{seg}__20260909-101500"
    assert "/" not in seg
    assert len(name.split("__")) == 4
    assert eval_paths.split_method_seg(seg)[0] == "graphrag"


def test_split_method_seg_roundtrip():
    assert eval_paths.split_method_seg("cyanchor_fl") == ("cyanchor_fl", "")
    assert eval_paths.split_method_seg(f"cyanchor_fl@{GPT}") == ("cyanchor_fl", GPT)


# ── resolution ───────────────────────────────────────────────────────────────

def test_two_models_do_not_share_a_cell(tmp_path):
    _mk(tmp_path, "ds", "g", f"cyanchor_fl@{GPT}", "20260909-100000", GPT)
    later = _mk(tmp_path, "ds", "g", f"cyanchor_fl@{CLAUDE}", "20260909-110000", CLAUDE)

    got_gpt = eval_paths.latest_run_dir("ds", "g", "cyanchor_fl", root=tmp_path, model=GPT)
    got_cl = eval_paths.latest_run_dir("ds", "g", "cyanchor_fl", root=tmp_path, model=CLAUDE)

    assert got_cl == later
    # The newer Claude run must NOT be returned for GPT, even though it is newer.
    assert got_gpt is not None and got_gpt != later
    assert eval_paths.split_method_seg(got_gpt.name.split("__")[2])[1] == GPT


def test_newest_stamp_wins_within_one_model(tmp_path):
    _mk(tmp_path, "ds", "g", f"graphrag@{GPT}", "20260909-100000", GPT)
    newest = _mk(tmp_path, "ds", "g", f"graphrag@{GPT}", "20260909-120000", GPT)
    assert eval_paths.latest_run_dir("ds", "g", "graphrag", root=tmp_path, model=GPT) == newest


# ── backward compatibility with the pre-tagging layout ───────────────────────

def test_untagged_legacy_run_still_resolves_for_its_own_model(tmp_path):
    legacy = _mk(tmp_path, "ds", "g", "cyanchor_fl", "20260801-090000", GPT)
    assert eval_paths.latest_run_dir("ds", "g", "cyanchor_fl", root=tmp_path, model=GPT) == legacy


def test_untagged_legacy_run_is_not_reused_by_another_model(tmp_path):
    _mk(tmp_path, "ds", "g", "cyanchor_fl", "20260801-090000", GPT)
    assert eval_paths.latest_run_dir("ds", "g", "cyanchor_fl", root=tmp_path, model=CLAUDE) is None


def test_unstamped_legacy_dir_still_resolves(tmp_path):
    d = tmp_path / "ds__g__graphrag"
    d.mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps({"run_meta": {"cypher_llm": GPT}}), encoding="utf-8")
    assert eval_paths.latest_run_dir("ds", "g", "graphrag", root=tmp_path, model=GPT) == d


def test_legacy_run_without_run_meta_is_only_used_when_no_model_requested(tmp_path):
    d = _mk(tmp_path, "ds", "g", "graphrag", "20260801-090000", model=None)
    assert eval_paths.latest_run_dir("ds", "g", "graphrag", root=tmp_path, model=None) == d
    # Unknown provenance must not be claimed by a specific model.
    assert eval_paths.latest_run_dir("ds", "g", "graphrag", root=tmp_path, model=CLAUDE) is None


def test_tagged_run_beats_legacy_for_the_same_model(tmp_path):
    _mk(tmp_path, "ds", "g", "cyanchor_fl", "20260801-090000", GPT)
    tagged = _mk(tmp_path, "ds", "g", f"cyanchor_fl@{GPT}", "20260909-090000", GPT)
    assert eval_paths.latest_run_dir("ds", "g", "cyanchor_fl", root=tmp_path, model=GPT) == tagged


def test_missing_triple_returns_none(tmp_path):
    assert eval_paths.latest_run_dir("ds", "g", "fcav", root=tmp_path, model=GPT) is None


# ── the generator preset (config receiver <- eval_config control panel) ──────

def _reload_config(monkeypatch, preset):
    import importlib
    import config
    if preset is None:
        monkeypatch.delenv("GENERATOR_LLM", raising=False)
    else:
        monkeypatch.setenv("GENERATOR_LLM", preset)
    return importlib.reload(config)


def test_preset_switches_every_stage(monkeypatch):
    try:
        cfg = _reload_config(monkeypatch, CLAUDE)
        assert cfg.active_generator_model() == CLAUDE
        for stage in (cfg.NER_LLM_CONFIG, cfg.QA_LLM_CONFIG, cfg.CYPHER_LLM_CONFIG, cfg.DEFAULT_LLM_CONFIG):
            assert stage["model"] == "claude-sonnet-5" or stage["model"] == cfg.MODEL_PRESETS[CLAUDE]["model"]
            assert stage["provider"] == "anthropic"
    finally:
        _reload_config(monkeypatch, None)


def test_preset_covers_the_whole_sweep(monkeypatch):
    import config
    for name in ("gpt-4.1", "gpt-5.6-terra", "gpt-5.6-luna", "claude-opus-5",
                 "claude-haiku-4.5", "deepseek-v3.1", "llama-3.3-70b"):
        spec = config.resolve_preset(name)
        assert spec["provider"] in ("openai", "anthropic", "hf_compatible")
        if spec["provider"] == "hf_compatible":
            assert spec["model"] in config.MODEL_REGISTRY, name


def test_unknown_preset_fails_loudly(monkeypatch):
    import importlib
    import config
    monkeypatch.setenv("GENERATOR_LLM", "not-a-model")
    try:
        with pytest.raises(KeyError):
            importlib.reload(config)
    finally:
        _reload_config(monkeypatch, None)


def test_no_receiver_resolves_to_the_baseline_preset(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.active_generator_model() == "gpt-4.1"
    assert cfg.CYPHER_LLM_CONFIG["provider"] == "openai"


def test_reader_default_follows_the_control_panel(monkeypatch):
    import eval_config
    monkeypatch.setattr(eval_config, "GENERATOR_LLM", "gpt-5.6-luna", raising=False)
    assert eval_paths.default_model() == "gpt-5.6-luna"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── fixes from the second review ─────────────────────────────────────────────

def test_any_model_mode_sees_tagged_dirs_too(tmp_path):
    """model=None is the explicit 'any model' mode: it must not go blind to
    tagged dirs once a sweep starts writing them."""
    _mk(tmp_path, "ds", "g", "graphrag", "20260801-090000", GPT)
    newest = _mk(tmp_path, "ds", "g", f"graphrag@{CLAUDE}", "20260909-120000", CLAUDE)
    assert eval_paths.latest_run_dir("ds", "g", "graphrag", root=tmp_path, model=None) == newest


def test_default_llm_config_follows_the_preset(monkeypatch):
    """DEFAULT_LLM_CONFIG feeds the entity-extraction tool inside the NER
    agent. It is *derived* from NER_LLM_CONFIG, so it must be derived after
    the preset is applied or that stage silently runs the baseline model."""
    import importlib
    import config

    monkeypatch.setenv("GENERATOR_LLM", CLAUDE)
    try:
        cfg = importlib.reload(config)
        assert cfg.DEFAULT_LLM_CONFIG["model"] == cfg.MODEL_PRESETS[CLAUDE]["model"]
        assert cfg.DEFAULT_LLM_CONFIG["provider"] == "anthropic"
    finally:
        monkeypatch.delenv("GENERATOR_LLM", raising=False)
        importlib.reload(config)


def test_run_meta_model_prefers_cypher_then_ner_then_qa(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "summary.json").write_text(
        json.dumps({"run_meta": {"ner_llm": "a", "qa_llm": "b"}}), encoding="utf-8")
    assert eval_paths.run_meta_model(d) == "a"
    (d / "summary.json").write_text(
        json.dumps({"run_meta": {"cypher_llm": "c", "ner_llm": "a"}}), encoding="utf-8")
    assert eval_paths.run_meta_model(d) == "c"
    (d / "summary.json").write_text("not json", encoding="utf-8")
    assert eval_paths.run_meta_model(d) is None
