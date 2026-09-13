"""summary.json must record the model the run ACTUALLY used.

Regression for the generator sweep: the parent process stamps run_config, but
only the worker sees GENERATOR_LLM, so the stamp must resolve the preset from
the injected env (the same value that tags the run dir), not from config.py's
static stage literals.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import config as _config          # noqa: E402
import eval_run                   # noqa: E402


def _stamp(tmp_path, env):
    out = tmp_path / "summary.json"
    out.write_text(json.dumps({"n": 1, "ea": 1.0}), encoding="utf-8")
    eval_run._stamp_summary(out, env, dataset="d", graph="g", method_seg="m",
                            stamp="s", shards=1, limit=None)
    return json.loads(out.read_text(encoding="utf-8"))["run_config"]["llm"]


def test_stamp_records_preset_model_not_static_literal(tmp_path):
    preset = next(k for k in _config.MODEL_PRESETS if k != "gpt-4.1")
    want = _config.MODEL_PRESETS[preset]["model"]
    llm = _stamp(tmp_path, {"GENERATOR_LLM": preset})
    assert llm["generator_llm"] == preset
    for stage in ("ner", "cypher", "qa"):
        assert llm[stage]["model"] == want, (stage, llm[stage])


def test_stamp_without_preset_falls_back_to_static_config(tmp_path):
    llm = _stamp(tmp_path, {})
    assert llm["generator_llm"] is None
    assert llm["cypher"]["model"] == _config.CYPHER_LLM_CONFIG["model"]
