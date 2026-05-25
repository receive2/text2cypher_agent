"""
data_augmentation.augmenters.base
=================================
Augmenter ABC + per-call context.

An augmenter takes *one* entity surface form (the substring of NL we'll
replace) and returns a perturbed surface form, or ``None`` to decline.
Decline cases include: partial-name on a single-token entity, abbrev
with no known mapping and LLM disabled, etc.

The pipeline catches ``None`` and falls through to the next strategy
sampled by :func:`data_augmentation.pipeline._strategy_order` (weighted
sampling without replacement, recomputed per entity) so a declined pick
doesn't waste the row.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from data_augmentation.llm import LLMClient


@dataclass
class AugContext:
    """
    Per-call context handed to every augmenter.

    Parameters
    ----------
    nl
        The full original NL question — useful for augmenters (e.g.
        paraphrase) that want to scope their rewrite to the surrounding
        clause.
    rng
        Pipeline-wide :class:`random.Random` instance (seeded by the
        runner) for reproducible noise.
    llm
        :class:`LLMClient`; ``llm.enabled`` is False when no LLM was
        configured, in which case LLM-dependent augmenters must
        decline.
    """
    nl:      str
    rng:     random.Random
    llm:     LLMClient
    # Per-entity span offsets into ``nl``.  Set by the pipeline immediately
    # before calling an augmenter; ``None`` outside that window.  Context-
    # aware augmenters (paraphrase) read these to know what's adjacent to
    # the entity (e.g. a preceding article).
    span_start: Optional[int] = None
    span_end:   Optional[int] = None


class Augmenter(ABC):
    """Abstract base class for all augmentation strategies."""

    #: Short name used in ``_aug_meta.edits[].strategy`` (e.g. "casing").
    name: str = ""

    @abstractmethod
    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        """
        Return a perturbed surface form for *surface*, or ``None`` to
        decline.  Implementations must NOT mutate ``ctx``.
        """
        raise NotImplementedError
