# -*- coding: utf-8 -*-
"""verify_setup.py scopes: the default is EVAL_PAIRS (a developer's scratch
pair), --suite is the 13 sweep pairs the driver's pre-flight checks."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import eval_config as cfg           # noqa: E402
import verify_setup as vs           # noqa: E402
from scripts import artifact_manifest as am   # noqa: E402


def _quiet(monkeypatch):
    seen = []
    monkeypatch.setattr(vs, "_check_archive", lambda ds, gr: (seen.append((ds, gr)), ("OK", "ok"))[1])
    monkeypatch.setattr(am, "load_manifest", lambda p: {})
    monkeypatch.setattr(am, "check_pair", lambda manifest, root, ds, gr: (am.OK, ""))
    return seen


def test_suite_checks_the_13_sweep_pairs(monkeypatch, capsys):
    seen = _quiet(monkeypatch)
    assert vs.main(["--suite"]) == 0
    assert seen == [tuple(p) for p in cfg.FULL_EVAL_PAIRS_13_AUGMENTED] and len(seen) == 13
    assert "13 archive(s) from the sweep suite (--suite)" in capsys.readouterr().out


def test_default_checks_eval_pairs_not_the_suite(monkeypatch):
    seen = _quiet(monkeypatch)
    monkeypatch.setattr(cfg, "EVAL_PAIRS", [("cypherbench_augmented", "terrorist_attack")])
    assert vs.main([]) == 0
    assert seen == [("cypherbench_augmented", "terrorist_attack")]
