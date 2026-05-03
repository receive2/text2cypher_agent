"""
eval.dataset_base
=================
Single source of truth for the ``<augmented> -> <base>`` dataset
mapping consumed by the evaluation harness.

Why
---
Every augmented variant (e.g. ``cypherbench_augmented``) shares its
loader, evaluator, and Neo4j graph state with its base variant
(``cypherbench``).  The augmentation layer only rewrites the natural-
language question — the gold Cypher, schema, and underlying database
remain untouched.  So the harness should:

    * dispatch to the base dataset's ``metrics_*`` module,
    * reuse the base dataset's setup archive / Neo4j connection,
    * but report results under the augmented dataset name so users can
      tell ``cypherbench`` and ``cypherbench_augmented`` apart in the
      aggregated table.

Usage
-----
::

    from eval.dataset_base import base_dataset, is_augmented
    base = base_dataset("cypherbench_augmented")  # -> "cypherbench"
"""

from __future__ import annotations


# ── The mapping ──────────────────────────────────────────────────────────────
# Keys are dataset names that may appear in eval_config.EVAL_PAIRS.
# Values are the underlying base dataset whose ``metrics_*`` module
# handles the actual evaluation work.

_DATASET_BASE: dict[str, str] = {
    "cypherbench":            "cypherbench",
    "cypherbench_augmented":  "cypherbench",
    "mindthequery":           "mindthequery",
    "mindthequery_augmented": "mindthequery",
    "zograscope":             "zograscope",
    "zograscope_augmented":   "zograscope",
}


_AUG_SUFFIX = "_augmented"


def base_dataset(name: str) -> str:
    """
    Return the base dataset name for *name*.

    Raises
    ------
    ValueError
        If *name* is not in :data:`_DATASET_BASE`.  The error message
        lists every registered key so callers can see what's available.
    """
    if name not in _DATASET_BASE:
        raise ValueError(
            f"Unknown dataset {name!r}; expected one of "
            f"{sorted(_DATASET_BASE.keys())}."
        )
    return _DATASET_BASE[name]


def is_augmented(name: str) -> bool:
    """True iff *name* is an augmented variant (ends in ``_augmented``)."""
    return name.endswith(_AUG_SUFFIX)


def augmented_for(name: str) -> str:
    """Return the augmented sibling of base name *name*."""
    return f"{name}{_AUG_SUFFIX}"


def known_datasets() -> list[str]:
    """Return every dataset name registered in the mapping."""
    return sorted(_DATASET_BASE.keys())
