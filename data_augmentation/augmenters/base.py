"""
data_augmentation.augmenters.base
=================================
Augmenter ABC, per-call context, and the provenance-carrying result type.

An augmenter takes *one* entity surface form and returns an
:class:`EditProposal` (perturbed surface + provenance), or ``None`` to
decline.  Decline cases include: partial-name on a single-token entity,
abbrev/alias with no attested source and the LLM disabled, alias on a
synthetic-domain entity, etc.

The pipeline records provenance in ``_aug_meta.edits[]`` and routes every
``needs_verification`` proposal (LLM-proposed abbrev/alias forms) to the
human-verification queue.  Validity (DB collision / uniqueness / splice
grammar) is enforced by the pipeline via :mod:`data_augmentation.validity`,
NOT here — augmenters only generate.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from data_augmentation.llm import LLMClient

if TYPE_CHECKING:  # avoid import cycles at runtime
    from data_augmentation.kb_aliases import AliasProvider
    from data_augmentation.validity import ValueProvider


# Provenance tags for ``EditProposal.source`` (also written to _aug_meta).
SOURCE_ALGORITHMIC = "algorithmic"   # casing / typo / partial — no external source
SOURCE_KB_SIMPLEKG = "kb:simplekg"   # CypherBench shipped (Wikidata-derived) aliases
SOURCE_KB_CURATED  = "kb:curated"    # hand-curated tables in kb_aliases
SOURCE_RXNORM      = "kb:rxnorm"     # RxNorm brand↔generic (Mind-the-Query drugs)
SOURCE_LLM         = "llm"           # LLM proposal — always needs human verification


@dataclass
class EditProposal:
    """A proposed perturbation of a single entity surface form."""
    surface: str               # the new (perturbed) surface form
    source: str                # one of the SOURCE_* tags above
    needs_verification: bool = False   # True for all LLM-proposed forms


@dataclass
class AugContext:
    """
    Per-call context handed to every augmenter.  Augmenters must NOT mutate it.

    Fields
    ------
    nl, rng, llm
        Full original question, the per-row seeded RNG, and the LLM client
        (``llm.enabled`` is False when no LLM was configured).
    span_start, span_end
        Char offsets of the current entity in ``nl`` (set by the pipeline).
    label, prop
        Graph label / property the entity's gold-cypher literal was compared
        against (e.g. ``Person`` / ``surname``), or ``None`` if unresolved.
    entity_type
        Classification from the extractor; only ``"name"`` reaches augmenters.
    graph
        The row's graph name (for provider routing and synthetic-domain rules).
    synthetic_domain
        True when ``graph`` is fabricated — the ``alias`` strategy declines.
    values
        DB-grounded :class:`~data_augmentation.validity.ValueProvider` for this
        graph (``None`` ⇒ validity checks are skipped; pipeline warns).
    aliases
        Attested-alias provider (:class:`~data_augmentation.kb_aliases.AliasProvider`).
    """
    nl:      str
    rng:     random.Random
    llm:     LLMClient
    span_start: Optional[int] = None
    span_end:   Optional[int] = None
    label:   Optional[str] = None
    prop:    Optional[str] = None
    entity_type: str = "name"
    graph:   Optional[str] = None
    synthetic_domain: bool = False
    values:  Optional["ValueProvider"] = None
    aliases: Optional["AliasProvider"] = None


class Augmenter(ABC):
    """Abstract base class for all augmentation strategies."""

    #: Short name used in ``_aug_meta.edits[].strategy`` (e.g. "casing").
    name: str = ""

    @abstractmethod
    def apply(self, surface: str, ctx: AugContext) -> Optional[EditProposal]:
        """
        Return an :class:`EditProposal` for *surface*, or ``None`` to decline.
        Implementations must NOT mutate ``ctx``.
        """
        raise NotImplementedError
