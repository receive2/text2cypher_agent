"""
data_augmentation.augmenters.paraphrase
=======================================
LLM paraphrasing — the most expensive but closest to real-world usage.
Adds descriptive scaffolding around the entity while preserving the
original surface form (the entity name itself stays present so the
referent is unambiguous).

::

    'Tom Hanks'        -> 'the actor Tom Hanks'
    'Sacramento Kings' -> 'the Kings of Sacramento'
    'USA'              -> 'the country known as the USA'

Distinct from the *synonym* augmenter: paraphrase prefers ADDING
descriptive context around the original entity string, not replacing
it with a different surface form.

Declines when ``ctx.llm.enabled`` is False — there is no static
fallback for paraphrase.
"""

from __future__ import annotations

from typing import Optional

from data_augmentation.augmenters.base import Augmenter, AugContext
from data_augmentation.llm import first_nonempty_line


_LLM_SYSTEM = (
    "You add a short descriptive paraphrase around a named entity so it "
    "fits naturally inside a question without rewriting the rest of the "
    "sentence.  Examples:\n"
    "  'Tom Hanks'        -> 'the actor Tom Hanks'\n"
    "  'Sacramento Kings' -> 'the Kings of Sacramento'\n"
    "  'Microsoft'        -> 'the tech giant Microsoft'\n"
    "Constraints:\n"
    "  - Output ONE paraphrase on a single line.  No quotes, no "
    "explanation.\n"
    "  - Keep it short — at most ~6 words longer than the entity.\n"
    "  - Do NOT change the referent or generalise.\n"
    "  - Prefer keeping the original entity string visible inside the "
    "paraphrase when natural.\n"
    "  - If you cannot produce a paraphrase, output NONE."
)

_LLM_PROMPT = "Entity: {entity}\nDescriptive paraphrase:"


class ParaphraseAugmenter(Augmenter):
    name = "paraphrase"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        if not surface:
            return None
        if not ctx.llm.enabled:
            return None

        resp = ctx.llm.complete(
            _LLM_PROMPT.format(entity=surface),
            system=_LLM_SYSTEM,
        )
        cand = first_nonempty_line(resp)
        if not cand:
            return None
        if cand.lower() == "none":
            return None
        if cand.lower() == surface.lower():
            return None
        # Cap paraphrase length: original words + 6, or 4× original,
        # whichever is larger.  This blocks runaway model output that
        # rewrites the sentence around the entity.
        max_words = max(len(surface.split()) + 6, 4 * len(surface.split()))
        if len(cand.split()) > max_words:
            return None
        return cand
