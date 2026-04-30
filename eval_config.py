#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_config.py
==============
Single source of truth for the t2c text-to-Cypher evaluation harness.

This is *not* an argparse-driven CLI config — it's a plain Python module
that the user hand-edits between runs.  ``eval_run.py`` imports the
module-level variables defined below and feeds them straight into each
dataset's ``evaluate_dataset(...)`` entry point.

Edit, save, then run::

    python eval_run.py

Variables
---------
DATASETS
    Iterable of datasets to evaluate.  Any subset of
    ``{"cypherbench", "mindthequery", "zograscope"}``.

CYPHERBENCH_PATH / MINDTHEQUERY_PATH / ZOGRASCOPE_PATH
    Path each module's ``evaluate_dataset(path, ...)`` will read from.
    The variable names end in ``_PATH`` for consistency, but the value
    can point at *whatever* the corresponding loader expects:

    * **CypherBench** — a ``*.json`` or ``*.jsonl`` test file.
      See :mod:`eval.metrics_CypherBench` docstring.
    * **Mind-the-Query** — either a single ``*.json`` file (a JSON
      array of examples) or a directory containing ``*_test.json``
      files (walked recursively).  Mind-the-Query's native release
      format is a directory tree of JSON arrays — *do not* pre-convert
      it to JSONL.  See :mod:`eval.metrics_MindTheQuery` docstring.
    * **ZOGRASCOPE** — a ``*.csv`` file (typically
      ``data/zograscope_test_v1.csv``) or a directory containing it.
      ZOGRASCOPE's native format is CSV.  See
      :mod:`eval.metrics_ZOGRASCOPE` docstring.

OUT_DIR
    Output directory for per-dataset JSONL result files.  Each run
    writes ``<OUT_DIR>/<dataset>.jsonl`` containing one record per
    example, plus ``<OUT_DIR>/<dataset>.summary.json``.

LIMIT
    Optional cap on examples per dataset (``None`` = all).

VERBOSE
    Per-example log lines.
"""

from __future__ import annotations

# Which datasets to run: any subset of {"cypherbench", "mindthequery", "zograscope"}
DATASETS = ["cypherbench", "mindthequery", "zograscope"]

# ── Dataset paths ─────────────────────────────────────────────────────────────
# Each path may point at a JSONL file, a JSON file, a CSV file, or a
# directory — see each eval/metrics_*.py module's docstring for details.

# CypherBench: path to the test set JSON / JSONL
# (e.g. cypherbench's test split released under their HuggingFace repo).
CYPHERBENCH_PATH = "path/to/cypherbench_test.jsonl"

# Mind-the-Query: path to a single *_test.json file or a 'test/' directory
# (https://github.com/endeavorXx/Mind-the-Query, Train_Test_Splits/).
MINDTHEQUERY_PATH = "path/to/Mind-the-Query/Train_Test_Splits/Manual/bloom/test"

# ZOGRASCOPE: path to data/zograscope_test_v1.csv
# (https://github.com/interact-erc/ZOGRASCOPE).
ZOGRASCOPE_PATH = "path/to/ZOGRASCOPE/data/zograscope_test_v1.csv"

# ── Run-time switches ─────────────────────────────────────────────────────────

# Output directory for per-dataset jsonl results + summary json.
OUT_DIR = "logs/eval"

# Optional cap on examples per dataset (None = all).
LIMIT = None

# Verbose per-example logging.
VERBOSE = False
