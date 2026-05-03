"""
data_augmentation
=================
Reusable text-augmentation primitives for the t2c text-to-Cypher
evaluation harness.

The package is split into three layers:

* ``augmenters/`` — one module per strategy (casing, partial_name,
  abbreviation, synonym, paraphrase, typo).  Each exposes an
  :class:`Augmenter` subclass that consumes one entity surface form and
  returns a perturbed surface form (or ``None`` if it declines to
  augment this entity).

* ``entity_extractor`` — finds entity spans in the natural-language
  question by intersecting literal strings inside the gold Cypher with
  substrings present in the NL.  Optional LLM fallback.

* ``pipeline`` — weighted-random strategy selection per detected entity,
  applies the chosen augmenter, and builds the structured ``_aug_meta``
  block recorded in every augmented row.

Dataset-specific glue lives in :mod:`data_augmentation.datasets`.
The repo-root ``run_data_augmentation.py`` is the user-facing runner.
"""

from data_augmentation.pipeline import augment_nl  # noqa: F401
from data_augmentation.entity_extractor import extract_entities  # noqa: F401
