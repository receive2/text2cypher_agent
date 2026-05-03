"""
data_augmentation.datasets.augment_zograscope
=============================================
Augment the ZOGRASCOPE dataset.

Layout (under ``~/datasets/zograscope/``):

    data/
        zograscope_test_v1.csv
        zograscope_train_v1.csv
        zograscope_length_test_v1.csv
        zograscope_length_train_v1.csv
        ids_compositional_test.txt
        ids_iid_test.txt
    graph/
    schema/
    README.md

Output: ``~/datasets/zograscope_augmented/`` mirrors the source.

CSV handling
------------
Each augmentable CSV has columns: ``id, nl, mr, nl_gold_linked,
nl_bracketed, entities, num_nodes, template_id, type, return_count``.
We rewrite the ``nl`` column and append a new ``_aug_meta`` column
holding a JSON-encoded blob.  Other columns pass through verbatim.

Files like ``ids_*.txt`` and ``length_*.csv`` need to remain consistent
with whatever IDs survive in the test CSV.  We preserve the original
``id`` field of every kept row and copy the IDs files verbatim — rows
dropped from the augmented CSV simply won't be hit by the loader.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from data_augmentation.datasets._common import (
    ensure_clean_dir,
    split_filter,
)
from data_augmentation.llm import LLMClient
from data_augmentation.pipeline import augment_nl


# ZOGRASCOPE Cypher in some columns is multi-clause and can be very long.
try:
    csv.field_size_limit(2**24)
except OverflowError:  # pragma: no cover
    csv.field_size_limit(2**20)


_NL_COL     = "nl"
_CYPHER_COL = "mr"


def _augment_csv_file(
    src:         Path,
    dst:         Path,
    *,
    proportions: Dict[str, float],
    llm:         LLMClient,
    use_llm_entity_fallback: bool,
    rng:         random.Random,
) -> tuple[int, int]:
    """Augment one ZOGRASCOPE CSV file.  Returns (kept, dropped)."""
    with src.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"ZOGRASCOPE CSV has no header: {src}")
        in_fields = list(reader.fieldnames)
        if _NL_COL not in in_fields or _CYPHER_COL not in in_fields:
            raise ValueError(
                f"ZOGRASCOPE CSV missing nl/mr columns: {src} (cols={in_fields})"
            )

        out_fields = list(in_fields)
        if "_aug_meta" not in out_fields:
            out_fields.append("_aug_meta")

        out_rows: List[Dict[str, Any]] = []
        dropped = 0
        for row in reader:
            nl = (row.get(_NL_COL) or "").strip()
            gold = (row.get(_CYPHER_COL) or "").strip()
            if not nl or not gold:
                dropped += 1
                continue
            result = augment_nl(
                nl,
                gold,
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
            new_row[_NL_COL]     = new_nl
            new_row["_aug_meta"] = json.dumps(aug_meta, ensure_ascii=False)
            out_rows.append(new_row)

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(out_rows)

    return len(out_rows), dropped


def _is_augmentable_csv(name: str, splits: List[str]) -> bool:
    if not name.lower().endswith(".csv"):
        return False
    if not split_filter(name, splits):
        return False
    return True


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
    if not source_root.is_dir():
        raise FileNotFoundError(f"ZOGRASCOPE source not found: {source_root}")

    ensure_clean_dir(target_root)
    rng = random.Random(seed)
    llm = LLMClient(llm_config)

    stats: Dict[str, Any] = {"per_file": {}, "kept": 0, "dropped": 0}

    for src in source_root.rglob("*"):
        rel = src.relative_to(source_root)
        dst = target_root / rel

        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue

        if _is_augmentable_csv(src.name, splits):
            logger.info(f"[zograscope] augmenting {rel} ...")
            try:
                kept, dropped = _augment_csv_file(
                    src, dst,
                    proportions=proportions,
                    llm=llm,
                    use_llm_entity_fallback=use_llm_entity_fallback,
                    rng=rng,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"[zograscope] failed to augment {rel}: {exc}; copying verbatim"
                )
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                continue
            stats["per_file"][str(rel)] = {"kept": kept, "dropped": dropped}
            stats["kept"]    += kept
            stats["dropped"] += dropped
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    logger.info(
        f"[zograscope] DONE  kept={stats['kept']} dropped={stats['dropped']}"
    )
    return stats
