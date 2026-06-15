"""
data_augmentation.augmenters
============================
Strategy modules.  Each strategy defines an :class:`Augmenter` subclass
exposing ``apply(entity_surface, ctx) -> EditProposal | None`` — return a
perturbed surface (with provenance), or ``None`` to decline (the pipeline's
deficit-greedy quota sampler then tries the next eligible strategy).

Taxonomy (post-redesign): casing / typo / partial / abbrev / alias.
``paraphrase`` was removed (entity left verbatim ⇒ no grounding challenge);
``synonym`` became ``alias`` (replacement semantics).
"""

from data_augmentation.augmenters.base import (
    Augmenter, AugContext, EditProposal,
)
from data_augmentation.augmenters.casing import CasingAugmenter
from data_augmentation.augmenters.typo import TypoAugmenter
from data_augmentation.augmenters.partial_name import PartialNameAugmenter
from data_augmentation.augmenters.abbreviation import AbbreviationAugmenter
from data_augmentation.augmenters.alias import AliasAugmenter

# Public registry — keys must match the strategy names in config.PROPORTIONS.
STRATEGY_REGISTRY: dict[str, type[Augmenter]] = {
    "casing":  CasingAugmenter,
    "typo":    TypoAugmenter,
    "partial": PartialNameAugmenter,
    "abbrev":  AbbreviationAugmenter,
    "alias":   AliasAugmenter,
}

__all__ = [
    "Augmenter",
    "AugContext",
    "EditProposal",
    "STRATEGY_REGISTRY",
    "CasingAugmenter",
    "TypoAugmenter",
    "PartialNameAugmenter",
    "AbbreviationAugmenter",
    "AliasAugmenter",
]
