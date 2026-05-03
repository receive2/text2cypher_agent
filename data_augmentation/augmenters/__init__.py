"""
data_augmentation.augmenters
============================
Strategy modules.  Each strategy defines an :class:`Augmenter` subclass
exposing ``apply(entity_surface, ctx) -> str | None`` — return a
perturbed surface form, or ``None`` to decline (so the pipeline falls
through to the next strategy).
"""

from data_augmentation.augmenters.base import Augmenter, AugContext
from data_augmentation.augmenters.casing import CasingAugmenter
from data_augmentation.augmenters.partial_name import PartialNameAugmenter
from data_augmentation.augmenters.abbreviation import AbbreviationAugmenter
from data_augmentation.augmenters.synonym import SynonymAugmenter
from data_augmentation.augmenters.paraphrase import ParaphraseAugmenter
from data_augmentation.augmenters.typo import TypoAugmenter

# Public registry — keys must match the strategy names in
# ``run_data_augmentation.AUG_PROPORTIONS``.
STRATEGY_REGISTRY: dict[str, type[Augmenter]] = {
    "casing":     CasingAugmenter,
    "partial":    PartialNameAugmenter,
    "abbrev":     AbbreviationAugmenter,
    "synonym":    SynonymAugmenter,
    "paraphrase": ParaphraseAugmenter,
    "typo":       TypoAugmenter,
}

__all__ = [
    "Augmenter",
    "AugContext",
    "STRATEGY_REGISTRY",
    "CasingAugmenter",
    "PartialNameAugmenter",
    "AbbreviationAugmenter",
    "SynonymAugmenter",
    "ParaphraseAugmenter",
    "TypoAugmenter",
]
