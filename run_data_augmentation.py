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

import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

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
# 2026-05-24: validating fix package on cypherbench only first; expand
# back to mindthequery / zograscope after the cypherbench eval rebound
# is confirmed.
DATASETS_TO_AUGMENT: List[str] = [
    "cypherbench",
]



# Which splits to augment per dataset.  ``["test"]`` is the default; add
# ``"train"`` (or ``"valid"`` / ``"dev"``) to widen.  Files that don't
# match a split token are copied verbatim.
SPLITS_TO_AUGMENT: List[str] = ["test"]

# Strategy proportions — six strategies, weights normalised at runtime.
#
# 2026-05-24: rebalanced after the pipeline post-augmenter safety gate
# was tightened.  ``abbrev`` is gated by a two-stage LLM recognizability
# judge so its effective output rate is naturally low even at this
# weight (most named entities have no widely-recognised abbreviation);
# ``paraphrase`` gets a small bump now that the prompt is context-aware
# and unlikely to introduce double-article artifacts.
AUG_PROPORTIONS: Dict[str, float] = {
    "casing":     0.20,
    "partial":    0.15,
    "abbrev":     0.08,
    "synonym":    0.17,
    "paraphrase": 0.25,
    "typo":       0.15,
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


_STRATEGIES = ("casing", "partial", "abbrev", "synonym", "paraphrase", "typo")
_TARGET_PCT = {
    "casing":     0.20,
    "partial":    0.15,
    "abbrev":     0.08,
    "synonym":    0.17,
    "paraphrase": 0.25,
    "typo":       0.15,
}


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────

def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _strategy_counts_for_aug_dir(aug_root: Path) -> Counter:
    """
    Walk an augmented-dataset directory and tally strategies recorded in
    each row's ``_aug_meta.edits[].strategy`` field.

    Supports both JSON-list shape (CypherBench, Mind-the-Query) and CSV
    shape (ZOGRASCOPE) where ``_aug_meta`` is a JSON string column.
    """
    c: Counter = Counter()
    if not aug_root.is_dir():
        return c

    for p in aug_root.rglob("*"):
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        if suf == ".json":
            try:
                with p.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(data, list):
                continue
            for row in data:
                if not isinstance(row, dict):
                    continue
                meta = row.get("_aug_meta")
                if not isinstance(meta, dict):
                    continue
                for e in meta.get("edits", []) or []:
                    s = e.get("strategy") if isinstance(e, dict) else None
                    if isinstance(s, str):
                        c[s] += 1
        elif suf == ".csv":
            try:
                with p.open("r", encoding="utf-8", newline="") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        raw_meta = row.get("_aug_meta")
                        if not raw_meta:
                            continue
                        try:
                            meta = json.loads(raw_meta)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(meta, dict):
                            continue
                        for e in meta.get("edits", []) or []:
                            s = e.get("strategy") if isinstance(e, dict) else None
                            if isinstance(s, str):
                                c[s] += 1
            except Exception:  # noqa: BLE001
                continue
    return c


def _print_strategy_distribution(per_dataset_counts: Dict[str, Counter]) -> None:
    """Print a per-dataset strategy distribution table with ⚠ flags."""
    if not per_dataset_counts:
        return

    print("══ strategy distribution (target: ~18% each, typo ~10%) ══")
    name_w = max(len("strategy"), max(len(s) for s in _STRATEGIES))
    col_w = 14
    header = " " * (name_w + 2) + "".join(f"{ds:>{col_w}}" for ds in per_dataset_counts)
    print(header)

    # Pre-compute totals.
    totals = {ds: sum(c.values()) for ds, c in per_dataset_counts.items()}
    skewed_lines: List[str] = []

    for strat in _STRATEGIES:
        cells: List[str] = []
        for ds, counts in per_dataset_counts.items():
            tot = totals[ds]
            if tot == 0:
                cells.append(f"{'  —':>{col_w}}")
                continue
            pct = counts.get(strat, 0) / tot
            cell = f"{pct * 100:>{col_w - 2}.1f}%"
            cells.append(cell)
            # Skewed-warning rule: flag if observed proportion is more
            # than 50% off the target in either direction.  abbrev's
            # target is low by design (gated by recognizability judge)
            # so we don't insist on a tight floor.
            target = _TARGET_PCT[strat]
            high = pct > target * 1.5
            low  = pct < target * 0.5
            if high or low:
                skewed_lines.append(
                    f"⚠ skewed: {ds} {strat} = {pct * 100:.1f}% "
                    f"(target {target * 100:.0f}%)"
                )
        print(f"  {strat:<{name_w}}" + "".join(cells))

    if skewed_lines:
        print()
        for line in skewed_lines:
            print(line)
    print()


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
    successful_datasets: List[str] = []
    for ds, info in overall.items():
        if info.get("ok"):
            stats = info["stats"]
            print(
                f"  ✓ {ds:<14}  kept={stats['kept']:<6}  dropped={stats['dropped']}"
            )
            successful_datasets.append(ds)
        else:
            any_failed = True
            print(f"  ✗ {ds:<14}  ERROR: {info['error']}")
    print()

    # ── Strategy distribution table ────────────────────────────────────────
    per_dataset_counts: Dict[str, Counter] = {}
    for ds in successful_datasets:
        aug_dir = source_root / f"{ds}{TARGET_SUFFIX}"
        per_dataset_counts[ds] = _strategy_counts_for_aug_dir(aug_dir)
    if per_dataset_counts:
        _print_strategy_distribution(per_dataset_counts)

    return 2 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
