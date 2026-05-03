"""
data_augmentation.datasets.augment_cypherbench
==============================================
Augment the CypherBench dataset.

Layout (under ``~/datasets/cypherbench/``):

    test.json           — JSON list of examples
    train.json          — JSON list of examples
    graphs/             — graph dumps used by Neo4j; copied verbatim
    README.md           — copied verbatim

Output: ``~/datasets/cypherbench_augmented/`` mirrors the source.  The
NL question is rewritten in-place; ``_aug_meta`` is added per example.
Examples for which no entity could be detected/augmented are dropped.

Field handling
--------------
CypherBench uses ``nl_question`` for the NL string and ``gold_cypher``
for the reference Cypher.  We preserve every other field of every row
verbatim.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from data_augmentation.datasets._common import (
    copy_tree,
    ensure_clean_dir,
    split_filter,
)
from data_augmentation.llm import LLMClient
from data_augmentation.pipeline import augment_nl


_NL_KEYS     = ("nl_question", "question", "natural_language_question", "nl")
_CYPHER_KEYS = ("gold_cypher", "cypher", "target_cypher", "ground_truth_cypher")

# Files at the cypherbench root that look like split files.
_SPLIT_FILES = ("test.json", "train.json", "valid.json", "dev.json")


def _first_present_key(d: Dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if k in d and d[k] is not None:
            return k
    return None


def _augment_one_split_file(
    src_file:    Path,
    dst_file:    Path,
    *,
    proportions: Dict[str, float],
    llm:         LLMClient,
    use_llm_entity_fallback: bool,
    rng:         random.Random,
) -> tuple[int, int]:
    """Read *src_file*, augment, write *dst_file*.  Return (kept, dropped)."""
    with src_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(
            f"CypherBench split file {src_file} is not a JSON list "
            f"(got {type(data).__name__})."
        )

    out: List[Dict[str, Any]] = []
    dropped = 0
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            dropped += 1
            continue
        nl_key = _first_present_key(row, _NL_KEYS)
        cy_key = _first_present_key(row, _CYPHER_KEYS)
        if not nl_key or not cy_key:
            dropped += 1
            continue
        nl = str(row[nl_key])
        gold_cypher = str(row[cy_key])

        result = augment_nl(
            nl,
            gold_cypher,
            proportions=proportions,
            llm=llm,
            use_llm_entity_fallback=use_llm_entity_fallback,
            rng=rng,
        )
        if result is None:
            dropped += 1
            continue
        new_nl, aug_meta = result

        new_row = dict(row)              # shallow copy preserves unrelated fields
        new_row[nl_key] = new_nl
        new_row["_aug_meta"] = aug_meta
        out.append(new_row)

        if (i + 1) % 200 == 0:
            logger.info(
                f"[cypherbench:{src_file.name}] augmented {i + 1}/{len(data)}"
            )

    dst_file.parent.mkdir(parents=True, exist_ok=True)
    with dst_file.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    return len(out), dropped


def run(
    *,
    source_root:  Path,
    target_root:  Path,
    splits:       List[str],
    proportions:  Dict[str, float],
    llm_config:   Optional[Dict[str, Any]],
    use_llm_entity_fallback: bool,
    seed:         int,
) -> Dict[str, Any]:
    """
    Augment CypherBench.

    Parameters
    ----------
    source_root
        ``~/datasets/cypherbench``.
    target_root
        ``~/datasets/cypherbench_augmented``.
    splits
        Subset of ``["test", "train"]``; only files whose name contains
        one of these tokens are augmented.  All other files / dirs are
        copied verbatim so loaders that touch them still work.
    """
    if not source_root.is_dir():
        raise FileNotFoundError(f"CypherBench source not found: {source_root}")

    ensure_clean_dir(target_root)
    rng = random.Random(seed)
    llm = LLMClient(llm_config)

    stats: Dict[str, Any] = {"per_file": {}, "kept": 0, "dropped": 0}

    # Iterate the source root; copy verbatim by default, augment split files.
    for entry in sorted(source_root.iterdir()):
        rel = entry.name
        if entry.is_dir():
            # graphs/, etc. — copied verbatim
            copy_tree(entry, target_root / rel)
            continue

        if entry.is_file() and rel in _SPLIT_FILES and split_filter(rel, splits):
            logger.info(f"[cypherbench] augmenting {rel} ...")
            kept, dropped = _augment_one_split_file(
                entry,
                target_root / rel,
                proportions=proportions,
                llm=llm,
                use_llm_entity_fallback=use_llm_entity_fallback,
                rng=rng,
            )
            stats["per_file"][rel] = {"kept": kept, "dropped": dropped}
            stats["kept"]    += kept
            stats["dropped"] += dropped
        else:
            # README.md, license, untouched split (e.g. train when only
            # test is requested), etc. — copy verbatim.
            (target_root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target_root / rel)

    logger.info(
        f"[cypherbench] DONE  kept={stats['kept']} dropped={stats['dropped']}"
    )
    return stats
