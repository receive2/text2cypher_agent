"""
data_augmentation.augmenters.partial_name
=========================================
Partial-name simplification — how users compress multi-token entity names.

Hybrid strategy (algorithmic first, LLM fallback):

  1. **Algorithmic** (free, model-free, no human verification): generate
     conservative token reductions and keep the first that resolves uniquely
     to the canonical value in the DB.  Candidates are:
       * suffix reductions (drop leading modifiers, keep the head):
         "Los Angeles Lakers" → "Lakers", "shooting guard" → "guard";
       * prefix reductions of length ≥ 2 (keep a leading head phrase):
         "House Committee on Education..." → "House Committee".
     A SINGLE-token reduction is allowed only if it keeps the LAST token (the
     usual English head) — this kills the over-reductions staging surfaced
     ("shooting guard" → "shooting", "ACB ... Award" → "ACB", both leading
     modifiers).

  2. **LLM fallback** (when algorithmic yields nothing unique and
     ``ctx.llm.enabled``): ask for a natural shortening, restricted to words
     that already appear in the surface (so it stays a partial name, not an
     alias/rephrase), flagged ``needs_verification`` and still gated by the
     DB uniqueness check.
"""

from __future__ import annotations

import re
from typing import List, Optional

from data_augmentation import validity as V
from data_augmentation.augmenters.base import (
    Augmenter, AugContext, EditProposal, SOURCE_ALGORITHMIC, SOURCE_LLM,
)
from data_augmentation.llm import first_nonempty_line

_TOKEN_RE = re.compile(r"\S+")
_STOPish = {"of", "the", "a", "an", "and", "for", "on", "in", "to", "de", "del", "la"}

_LLM_SYSTEM = (
    "You shorten a named entity the way a person naturally would in "
    "conversation, keeping it unambiguous and using ONLY words that already "
    "appear in the name (drop words; do not add or reorder). Examples:\n"
    "  'House Committee on Education and the Workforce' -> 'House Committee'\n"
    "  'Los Angeles Lakers' -> 'Lakers'\n"
    "Output ONLY the shortened name on a single line, or NONE if it can't be "
    "shortened cleanly."
)
_LLM_PROMPT = "Name: {entity}\nNatural short form:"


def _clean(cand_tokens: List[str], surface: str) -> Optional[str]:
    if not cand_tokens:
        return None
    if cand_tokens[0].lower() in _STOPish or cand_tokens[-1].lower() in _STOPish:
        return None
    s = " ".join(cand_tokens)
    if not s or s == surface or len(s) < 2:
        return None
    return s


class PartialNameAugmenter(Augmenter):
    name = "partial"

    def apply(self, surface: str, ctx: AugContext) -> Optional[EditProposal]:
        toks = _TOKEN_RE.findall(surface)
        if len(toks) < 2:
            return None

        # Ranked algorithmic candidates.
        ranked: List[str] = []
        # suffix reductions, shortest first (drop leading modifiers; keep head)
        for i in range(len(toks) - 1, 0, -1):      # i = start index
            c = _clean(toks[i:], surface)
            if c:
                ranked.append(c)
        # prefix reductions of length >= 2 (keep a leading head phrase)
        for j in range(len(toks) - 1, 1, -1):      # j = end index, >= 2 tokens
            c = _clean(toks[:j], surface)
            if c:
                ranked.append(c)
        # de-dup, preserve order
        seen, cands = set(), []
        for c in ranked:
            if c.lower() not in seen:
                seen.add(c.lower())
                cands.append(c)

        # First algorithmic candidate that resolves uniquely.
        for c in cands:
            ok, _ = V.check_validity("partial", c, surface, ctx.label, ctx.prop, ctx.values)
            if ok:
                return EditProposal(surface=c, source=SOURCE_ALGORITHMIC)

        # LLM fallback for the hard cases (head not positionally determinable,
        # or all conservative reductions collide).
        if not ctx.llm.enabled:
            return None
        cand = first_nonempty_line(
            ctx.llm.complete(_LLM_PROMPT.format(entity=surface), system=_LLM_SYSTEM)
        )
        if not cand or cand.lower() == "none" or cand.lower() == surface.lower():
            return None
        if len(cand) >= len(surface):
            return None
        surf_words = {t.lower() for t in toks}
        if not all(w.lower() in surf_words for w in cand.split()):
            return None        # must be a subset of the original words (a partial, not a rephrase)
        ok, _ = V.check_validity("partial", cand, surface, ctx.label, ctx.prop, ctx.values)
        if not ok:
            return None
        return EditProposal(surface=cand, source=SOURCE_LLM, needs_verification=True)
