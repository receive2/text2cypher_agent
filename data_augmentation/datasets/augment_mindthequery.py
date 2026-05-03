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
* A file is "augmentable" only when ALL of the following hold:
    1. its relative path is under ``Train_Test_Splits/Manual/<graph>/test/``
    2. its filename ends with ``_test.json``
    3. its filename matches the requested splits via :func:`split_filter`
    4. its content is a JSON list of dicts containing ``NL Question`` +
       ``Cypher``.
* All other files (Automated splits, train splits, top-level files,
  ``Manually_Validated_Datasets/``, ``Datasets/``, statistics, etc.) are
  copied verbatim so the directory structure stays complete in case
  future configs reference them.
* The eval harness (``eval/metrics_MindTheQuery.py::load_dataset``) only
  consumes ``Train_Test_Splits/Manual/<graph>/test/`` — augmenting
  anything else is wasted LLM calls.
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


def _is_manual_test_path(rel: Path) -> bool:
    """
    True iff *rel* is a ``Train_Test_Splits/Manual/<graph>/test/<file>_test.json``
    relative path.  Anything else (Automated splits, train splits,
    Manually_Validated_Datasets, Datasets, top-level files) is out of
    scope for augmentation — those files get copied verbatim.
    """
    parts = rel.parts
    if len(parts) < 5:
        return False
    if parts[0] != "Train_Test_Splits" or parts[1] != "Manual":
        return False
    # parts[2] is the <graph> name; parts[3] must be the "test" leaf dir.
    if parts[3] != "test":
        return False
    if not rel.name.endswith("_test.json"):
        return False
    return True


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

        # By default, copy verbatim.  Only files under
        # Train_Test_Splits/Manual/<graph>/test/*_test.json are eligible
        # for augmentation; everything else (Automated, train splits,
        # Manually_Validated_Datasets, Datasets, top-level files) is
        # copied as-is.
        copy_only = True

        if (
            _is_manual_test_path(rel)
            and src.suffix.lower() == ".json"
            and split_filter(src.name, splits)
        ):
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
