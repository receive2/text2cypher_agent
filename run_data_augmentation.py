#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_data_augmentation.py
========================
Top-level driver for the data-augmentation pipeline.

Edit the constants at the top of this file, then::

    python run_data_augmentation.py

The runner produces three new dataset directories under
``~/datasets/`` (or whatever ``SOURCE_ROOT`` points at):

    cypherbench_augmented/
    mindthequery_augmented/
    zograscope_augmented/

These mirror the source layouts file-for-file.  Files matching the
requested splits (``SPLITS_TO_AUGMENT``) are NL-perturbed; everything
else is copied verbatim so downstream loaders don't break.

Each augmented row carries a structured ``_aug_meta`` field (a JSON
column for ZOGRASCOPE CSVs, a dict field elsewhere) recording the
original NL, the strategy, and the substituted text.  Rows with no
detectable entity are dropped.

LLM
---
``AUG_LLM_CONFIG`` has the same shape as ``NER_LLM_CONFIG`` /
``CYPHER_LLM_CONFIG`` in ``config.py`` — set provider/model exactly
the way you'd configure any other LLM stage.  Set it to ``None`` to
disable LLM-driven strategies entirely (paraphrase + LLM fallbacks for
abbrev/synonym + the LLM entity fallback all become no-ops).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

# Ensure the repo root is importable when invoked from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_augmentation.datasets import get_runner


# ──────────────────────────────────────────────────────────────────────────────
# USER KNOBS — edit these between runs
# ──────────────────────────────────────────────────────────────────────────────

# Which datasets to augment.  Comment out / shrink for partial runs.
DATASETS_TO_AUGMENT: List[str] = [
    "cypherbench",
    "mindthequery",
    "zograscope",
]



# Which splits to augment per dataset.  ``["test"]`` is the default; add
# ``"train"`` (or ``"valid"`` / ``"dev"``) to widen.  Files that don't
# match a split token are copied verbatim.
SPLITS_TO_AUGMENT: List[str] = ["test"]

# Strategy proportions — six strategies, weights normalised at runtime.
AUG_PROPORTIONS: Dict[str, float] = {
    "casing":     0.18,
    "partial":    0.18,
    "abbrev":     0.18,
    "synonym":    0.18,
    "paraphrase": 0.18,
    "typo":       0.10,
}

# LLM config — same shape as config.py LLM dicts.  Set to None to
# disable every LLM-dependent strategy and fallback.
AUG_LLM_CONFIG: Dict[str, Any] | None = {
    "provider":    "anthropic",
    "model":       "claude-opus-4-20250514",
    "temperature": 0.4,
}

# When the cypher-literal pass yields zero entities for a row, fall back
# to an LLM-based entity extractor.  Disable to keep cost down.
USE_LLM_ENTITY_FALLBACK: bool = True

# RNG seed for reproducibility.
SEED: int = 42

# Source / target roots.  ``TARGET_SUFFIX`` is appended to each source
# dataset name to form the augmented dataset name.
SOURCE_ROOT:   str = "~/datasets"
TARGET_SUFFIX: str = "_augmented"


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────

def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def main() -> int:
    source_root = _expand(SOURCE_ROOT)
    if not source_root.is_dir():
        print(
            f"[run_data_augmentation] SOURCE_ROOT does not exist: {source_root}",
            file=sys.stderr,
        )
        return 1

    if not DATASETS_TO_AUGMENT:
        print(
            "[run_data_augmentation] DATASETS_TO_AUGMENT is empty — nothing to do.",
            file=sys.stderr,
        )
        return 1

    if not SPLITS_TO_AUGMENT:
        print(
            "[run_data_augmentation] SPLITS_TO_AUGMENT is empty — nothing to do.",
            file=sys.stderr,
        )
        return 1

    logger.info(
        "data_augmentation: starting\n"
        f"  source_root  = {source_root}\n"
        f"  splits       = {SPLITS_TO_AUGMENT}\n"
        f"  datasets     = {DATASETS_TO_AUGMENT}\n"
        f"  proportions  = {AUG_PROPORTIONS}\n"
        f"  llm_enabled  = {AUG_LLM_CONFIG is not None}\n"
        f"  llm_entity_fb= {USE_LLM_ENTITY_FALLBACK}\n"
        f"  seed         = {SEED}"
    )

    overall: Dict[str, Any] = {}
    for ds in DATASETS_TO_AUGMENT:
        src_dir = source_root / ds
        dst_dir = source_root / f"{ds}{TARGET_SUFFIX}"

        try:
            runner = get_runner(ds)
        except ValueError as exc:
            print(f"[run_data_augmentation] {exc}", file=sys.stderr)
            return 2

        logger.info(f"[{ds}] {src_dir} → {dst_dir}")
        try:
            stats = runner(
                source_root=src_dir,
                target_root=dst_dir,
                splits=SPLITS_TO_AUGMENT,
                proportions=AUG_PROPORTIONS,
                llm_config=AUG_LLM_CONFIG,
                use_llm_entity_fallback=USE_LLM_ENTITY_FALLBACK,
                seed=SEED,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{ds}] augmentation failed: {exc}")
            overall[ds] = {"ok": False, "error": str(exc)}
            continue
        overall[ds] = {"ok": True, "stats": stats}

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n══ data augmentation summary ══")
    any_failed = False
    for ds, info in overall.items():
        if info.get("ok"):
            stats = info["stats"]
            print(
                f"  ✓ {ds:<14}  kept={stats['kept']:<6}  dropped={stats['dropped']}"
            )
        else:
            any_failed = True
            print(f"  ✗ {ds:<14}  ERROR: {info['error']}")
    print()
    return 2 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
