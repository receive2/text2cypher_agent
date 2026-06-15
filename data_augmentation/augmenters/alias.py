"""
data_augmentation.augmenters.alias
==================================
Replacement-style nickname / colloquial / brand–generic swap — the hardest
grounding rung: the original surface string is *replaced* entirely, so there
is little or no character overlap with the canonical DB value
(``TOCILIZUMAB → Actemra``, ``United Kingdom → Britain``).  This is the
inverse of the pre-redesign "synonym" gate, which (wrongly) required the
original to survive and so degenerated into paraphrase.

Eligibility & sources:

  * **Declines on synthetic domains** (``ctx.synthetic_domain``): fabricated
    entities have no real-world alias, so an LLM would hallucinate one — the
    shipped ``Wagner → the Wagner Group`` / ``Hanson → the band Hanson``
    corruption.
  * **Attested source** (``ctx.aliases.aliases``): shipped aliases + curated +
    RxNorm.  Model-free, not flagged.
  * **LLM proposer** (fallback): returned ``needs_verification=True``; must
    NOT contain the original verbatim (enforces replacement), and is length-
    capped against runaway paraphrase.
"""

from __future__ import annotations

from typing import Optional

from data_augmentation.augmenters.base import (
    Augmenter, AugContext, EditProposal, SOURCE_LLM,
)
from data_augmentation.config import ALIAS_CLOSED_SET_MAX
from data_augmentation.llm import first_nonempty_line

_LLM_SYSTEM = (
    "You provide a colloquial nickname or short alternative name for a named "
    "entity — a DIFFERENT surface form that refers to the SAME entity (e.g. "
    "'United Kingdom' -> 'Britain', 'Tocilizumab' -> 'Actemra'). Constraints: "
    "output ONE substitution on a single line, no quotes; it must NOT simply "
    "contain the original name; do not produce a pure acronym; if no good "
    "alternative exists, output NONE."
)
_LLM_PROMPT = "Entity: {entity}\nAlternative name:"


class AliasAugmenter(Augmenter):
    name = "alias"

    def apply(self, surface: str, ctx: AugContext) -> Optional[EditProposal]:
        if not surface:
            return None
        if ctx.synthetic_domain:
            return None

        # 1. Attested sources (model-free).
        if ctx.aliases is not None:
            cands = ctx.aliases.aliases(surface)
            # enforce replacement: drop any candidate that just wraps the original
            cands = [(f, s) for (f, s) in cands if surface.lower() not in f.lower()]
            if cands:
                form, src = ctx.rng.choice(cands)
                return EditProposal(surface=form, source=src, needs_verification=False)

        # 2. LLM proposer — flagged for human verification.
        if not ctx.llm.enabled:
            return None
        # Closed-set guard: don't let the LLM invent an alias for a member of a
        # small enumerable category (divisions/conferences/positions/awards) —
        # it swaps siblings or hallucinates.  Attested/curated aliases above
        # still cover the ones that genuinely have alternative names.
        if ctx.values is not None and ctx.label and ctx.prop:
            n = len(ctx.values.values(ctx.label, ctx.prop))
            if 0 < n <= ALIAS_CLOSED_SET_MAX:
                return None
        cand = first_nonempty_line(ctx.llm.complete(_LLM_PROMPT.format(entity=surface),
                                                    system=_LLM_SYSTEM))
        if not cand or cand.lower() == "none" or cand.lower() == surface.lower():
            return None
        # Replacement semantics: original must NOT survive inside the alias.
        if surface.lower() in cand.lower():
            return None
        # Runaway-paraphrase guard.
        if len(cand.split()) > max(4, 4 * len(surface.split())):
            return None
        return EditProposal(surface=cand, source=SOURCE_LLM, needs_verification=True)
