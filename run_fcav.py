#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_fcav.py
===========
Run the evaluation harness in the FCAV baseline mode.

Thin wrapper around ``eval_run.main()`` that:
  * forces ``NER_MODE=fcav`` (FCAV value-retrieval instead of the NER agent),
  * optionally overrides the Cypher-generation LLM for this run, and
  * optionally overrides the output directory.

The (dataset, graph) pairs and per-dataset caps still come from
``eval_config.py`` (``EVAL_PAIRS`` / ``LIMIT``), and the produced records +
summary are byte-for-byte the same format as the other NER modes — so
``eval_aggregate.py`` tabulates FCAV exactly like ``full`` / ``node_only`` /
``no_ner``.

Prerequisite: ``python setup_fcav.py`` must have built the FCAV VectorDB for
the graph(s) being evaluated.

Usage
-----
    python run_fcav.py [--cypher-llm gpt-4.1]
                       [--cypher-provider openai|anthropic|hf_compatible]
                       [--out-dir logs/eval_fcav]
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the FCAV baseline evaluation.")
    ap.add_argument("--cypher-llm", default=None,
                    help="override the Cypher-generation model (e.g. gpt-4.1, "
                         "claude-opus-4-20250514, or a MODEL_REGISTRY key)")
    ap.add_argument("--cypher-provider", default=None,
                    help="override the Cypher-generation provider "
                         "(openai | anthropic | hf_compatible)")
    ap.add_argument("--out-dir", default=None,
                    help="override eval_config.OUT_DIR for this run")
    args = ap.parse_args()

    # Must be set BEFORE eval workers (subprocesses) are spawned so they
    # inherit it — config.py reads these env vars at import.
    os.environ["NER_MODE"] = "fcav"
    if args.cypher_llm:
        os.environ["CYPHER_LLM_MODEL"] = args.cypher_llm
    if args.cypher_provider:
        os.environ["CYPHER_LLM_PROVIDER"] = args.cypher_provider

    import eval_config as cfg
    if args.out_dir:
        cfg.OUT_DIR = args.out_dir

    print(f"[run_fcav] NER_MODE=fcav  cypher_llm={args.cypher_llm or '(config default)'}  "
          f"out_dir={getattr(cfg, 'OUT_DIR', 'logs/eval')}  pairs={cfg.EVAL_PAIRS}")

    import eval_run
    return eval_run.main()


if __name__ == "__main__":
    raise SystemExit(main())
