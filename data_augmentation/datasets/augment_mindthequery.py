"""
data_augmentation.datasets.augment_mindthequery
===============================================
Augment the Mind-the-Query dataset.

Layout (under ``~/datasets/mindthequery/``):

    Train_Test_Splits/
        Manual/<graph>/test/<Category>_test.json
        Manual/<graph>/train/<Category>_train.json
        Automated/<graph>/...
        split_statistics.json
    Manually_Validated_Datasets/<graph>/<Category>_manual_annotation.json
    Automated_Validated_Datasets/...
    Datasets/...
    db_schema.jsonl
    incontext_few_shots.json
    LICENSE
    ReadMe.md
    requirements.txt
    nl_cypher_pair_generator.py
    automated_validators.py
    data_manager.py
    dataset_consolidator.py
    Prompt_Logs/
    utils/

Output: ``~/datasets/mindthequery_augmented/`` mirrors the source.

Augmentation policy
-------------------
* A file is "augmentable" if it ends with ``.json`` AND its filename
  matches the requested splits via :func:`split_filter` AND its content
  is a JSON list of dicts containing ``NL Question`` + ``Cypher``.
* Other JSON files (e.g. ``db_schema.jsonl``, statistics) are copied
  verbatim.
* Non-JSON files / directories not matching the above are copied
  verbatim.
* The eval harness reads from ``Train_Test_Splits/<Manual|Automated>/...``
  and ``Manually_Validated_Datasets/...`` — both layouts are
  augmented when they contain valid examples.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from data_augmentation.datasets._common import (
    ensure_clean_dir,
    split_filter,
)
from data_augmentation.llm import LLMClient
from data_augmentation.pipeline import augment_nl


_NL_KEYS     = ("NL Question", "nl_question", "question", "natural_language_question", "nl")
_CYPHER_KEYS = ("Cypher", "cypher", "gold_cypher", "ground_truth_cypher", "target_cypher")


def _first_present_key(d: Dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if k in d and d[k] is not None:
            return k
    return None


def _is_augmentable_json_list(data: Any) -> bool:
    if not isinstance(data, list) or not data:
        return False
    # Sample first entry: must be a dict carrying both an NL key and a Cypher key.
    head = data[0]
    if not isinstance(head, dict):
        return False
    return (
        _first_present_key(head, _NL_KEYS) is not None
        and _first_present_key(head, _CYPHER_KEYS) is not None
    )


def _augment_json_list_file(
    src:         Path,
    dst:         Path,
    *,
    proportions: Dict[str, float],
    llm:         LLMClient,
    use_llm_entity_fallback: bool,
    rng:         random.Random,
) -> tuple[int, int]:
    """Augment one Mind-the-Query JSON list file.  Returns (kept, dropped)."""
    with src.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        # Shouldn't happen — caller only invokes us for list-shape files.
        raise ValueError(f"Mind-the-Query file is not a list: {src}")

    out: List[Dict[str, Any]] = []
    dropped = 0
    for row in data:
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

        new_row = dict(row)
        new_row[nl_key] = new_nl
        new_row["_aug_meta"] = aug_meta
        out.append(new_row)

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as fh:
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
    Augment Mind-the-Query.  Walks the source tree; augments any JSON
    file that is a list of {NL Question, Cypher} dicts AND whose name
    matches the requested splits.  Everything else is copied verbatim.
    """
    if not source_root.is_dir():
        raise FileNotFoundError(f"Mind-the-Query source not found: {source_root}")

    ensure_clean_dir(target_root)
    rng = random.Random(seed)
    llm = LLMClient(llm_config)

    stats: Dict[str, Any] = {"per_file": {}, "kept": 0, "dropped": 0}

    # Use Path.rglob so we cover nested layouts under Train_Test_Splits/...
    # plus the flat Manually_Validated_Datasets/<graph>/*.json layout.
    for src in source_root.rglob("*"):
        rel = src.relative_to(source_root)
        dst = target_root / rel

        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue

        # By default, copy verbatim.
        copy_only = True

        if src.suffix.lower() == ".json" and split_filter(src.name, splits):
            try:
                with src.open("r", encoding="utf-8") as fh:
                    head = json.load(fh)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[mindthequery] skip non-JSON-list {rel}: {exc}")
                head = None
            if _is_augmentable_json_list(head):
                copy_only = False

        if copy_only:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            continue

        logger.info(f"[mindthequery] augmenting {rel} ...")
        kept, dropped = _augment_json_list_file(
            src, dst,
            proportions=proportions,
            llm=llm,
            use_llm_entity_fallback=use_llm_entity_fallback,
            rng=rng,
        )
        stats["per_file"][str(rel)] = {"kept": kept, "dropped": dropped}
        stats["kept"]    += kept
        stats["dropped"] += dropped

    logger.info(
        f"[mindthequery] DONE  kept={stats['kept']} dropped={stats['dropped']}"
    )
    return stats
