"""
data_augmentation.augmenters.abbreviation
=========================================
Acronym / short-form perturbation (and its reverse expansion).

Resolution order, anti-circularity by construction:

  1. **Attested source** (``ctx.aliases.abbrevs``): CypherBench shipped
     (Wikidata) aliases + curated acronym tables.  Model-free, not flagged.
  2. **LLM proposer** (when no attested form and ``ctx.llm.enabled``): the
     two-stage recognizability prompt PROPOSES a form, which is returned
     ``needs_verification=True``.  The LLM never judges validity — the
     pipeline's DB collision check + downstream human verification are the
     gates.  This is what prevents the shipped FOLD / HIP / "Ford → F" class
     of hallucinated tickers/initialisms from silently entering the dataset.
"""

from __future__ import annotations

from typing import Optional

from data_augmentation.augmenters.base import (
    Augmenter, AugContext, EditProposal, SOURCE_LLM,
)
from data_augmentation.llm import first_nonempty_line

_JUDGE_SYSTEM = (
    "You decide whether a named entity has a WIDELY-RECOGNISED abbreviation, "
    "acronym or initialism that a typical reader of news or Wikipedia would "
    "unambiguously resolve back to the same entity. Answer with ONLY 'YES' or "
    "'NO' on a single line."
)
_JUDGE_PROMPT = "Entity: {entity}\nIs there a widely-recognised abbreviation? (YES/NO):"
_PRODUCE_SYSTEM = (
    "Output the canonical, widely-recognised abbreviation / acronym / "
    "initialism for the entity. Respond with ONLY the abbreviation on a single "
    "line. If you cannot produce one with high confidence, respond with NONE."
)
_PRODUCE_PROMPT = "Entity: {entity}\nWidely-recognised abbreviation (e.g. USA, NBA, FBI):"


class AbbreviationAugmenter(Augmenter):
    name = "abbrev"

    def apply(self, surface: str, ctx: AugContext) -> Optional[EditProposal]:
        if not surface:
            return None

        # 1. Attested sources (model-free).
        if ctx.aliases is not None:
            cands = ctx.aliases.abbrevs(surface)
            if cands:
                form, src = ctx.rng.choice(cands)
                return EditProposal(surface=form, source=src, needs_verification=False)

        # 2. LLM proposer — flagged for human verification.
        if not ctx.llm.enabled:
            return None
        verdict = first_nonempty_line(
            ctx.llm.complete(_JUDGE_PROMPT.format(entity=surface), system=_JUDGE_SYSTEM)
        )
        if not verdict or verdict.strip().rstrip(".").upper() != "YES":
            return None
        cand = first_nonempty_line(
            ctx.llm.complete(_PRODUCE_PROMPT.format(entity=surface), system=_PRODUCE_SYSTEM)
        )
        if not cand or cand.lower() == "none":
            return None
        if len(cand) >= len(surface) or cand.lower() == surface.lower():
            return None
        if cand.count(" ") > 1:
            return None
        return EditProposal(surface=cand, source=SOURCE_LLM, needs_verification=True)
