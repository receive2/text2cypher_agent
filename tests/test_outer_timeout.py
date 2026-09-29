# -*- coding: utf-8 -*-
"""eval_run's outer worker timeout: a full-graph run is sized by the graph's question
count and never gets less than the former flat 4 h. Pole (1,283 questions) needs
4.3-4.6 h with CyANCHOR and was killed at the flat 4 h on 2026-09-29."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eval_config as cfg   # noqa: E402
import eval_run             # noqa: E402

FLAT = 4 * 60 * 60


def _full(n):
    return eval_run._outer_timeout_sec(n, limited=False, per_example_sec=65, explicit=None)


def test_count_examples_reads_the_release():
    assert eval_run._count_examples(cfg.ZOGRASCOPE_AUGMENTED_PATH, "pole") == 1283
    assert eval_run._count_examples(cfg.CYPHERBENCH_AUGMENTED_PATH, "flight_accident") == 168
    assert eval_run._count_examples(cfg.MINDTHEQUERY_AUGMENTED_PATH, "bloom") == 24


def test_count_examples_is_none_when_the_size_cannot_be_read():
    assert eval_run._count_examples(cfg.CYPHERBENCH_AUGMENTED_PATH, "no_such_graph") is None
    assert eval_run._count_examples("does/not/exist.json", "pole") is None
    assert eval_run._count_examples("some/test.csv", "pole") is None


def test_full_graph_run_is_sized_by_its_questions():
    assert _full(1283) == 1283 * 65 + 120
    assert _full(1283) > 4.6 * 3600          # what pole needs with CyANCHOR


def test_full_graph_run_never_gets_less_than_the_old_ceiling():
    assert _full(24) == FLAT                 # bloom
    assert _full(168) == FLAT                # flight_accident
    assert _full(None) == FLAT               # size unknown


def test_limited_run_and_explicit_override_are_unchanged():
    assert eval_run._outer_timeout_sec(3, limited=True, per_example_sec=65, explicit=None) == 3 * 65 + 120
    assert eval_run._outer_timeout_sec(1283, limited=False, per_example_sec=65, explicit="600") == 600.0
    assert eval_run._outer_timeout_sec(None, limited=False, per_example_sec=65, explicit="600") == 600.0
