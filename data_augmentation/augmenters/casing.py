"""
data_augmentation.augmenters.casing
===================================
Casing perturbation — the cheapest robustness improvement.

::

    'Sacramento Kings' -> 'sacramento kings'  (lower)
    'Sacramento Kings' -> 'SACRAMENTO KINGS'  (upper)
    'sacramento kings' -> 'Sacramento Kings'  (title)
"""

from __future__ import annotations

from typing import Optional

from data_augmentation.augmenters.base import Augmenter, AugContext


class CasingAugmenter(Augmenter):
    name = "casing"

    # Variants attempted in order; first that produces a *change* wins.
    _VARIANTS: tuple[str, ...] = ("lower", "upper", "title")

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        if not surface or surface.strip() == "":
            return None

        # Pick a deterministic-but-shuffled variant order so multiple
        # entities in the same row don't all flip to identical casing.
        order = list(self._VARIANTS)
        ctx.rng.shuffle(order)

        for variant in order:
            if variant == "lower":
                cand = surface.lower()
            elif variant == "upper":
                cand = surface.upper()
            elif variant == "title":
                cand = surface.title()
            else:  # pragma: no cover — exhaustive above
                continue
            if cand != surface:
                return cand
        return None
