"""
data_augmentation.augmenters.casing
===================================
Casing perturbation — the difficulty floor / control condition.

``.title()`` was dropped: it mangled apostrophes ("Night's Watch" →
"Night'S Watch"), which is a Python artifact, not real user input.  Only
all-lower and all-UPPER remain — both are things users actually type.

::

    'Sacramento Kings' -> 'sacramento kings'   (lower)
    'Sacramento Kings' -> 'SACRAMENTO KINGS'   (upper)
"""

from __future__ import annotations

from typing import Optional

from data_augmentation.augmenters.base import (
    Augmenter, AugContext, EditProposal, SOURCE_ALGORITHMIC,
)


class CasingAugmenter(Augmenter):
    name = "casing"

    _VARIANTS = ("lower", "upper")

    def apply(self, surface: str, ctx: AugContext) -> Optional[EditProposal]:
        if not surface or not surface.strip():
            return None
        order = list(self._VARIANTS)
        ctx.rng.shuffle(order)
        for variant in order:
            cand = surface.lower() if variant == "lower" else surface.upper()
            if cand != surface:
                return EditProposal(surface=cand, source=SOURCE_ALGORITHMIC)
        return None
