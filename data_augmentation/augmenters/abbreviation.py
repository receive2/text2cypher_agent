"""
data_augmentation.augmenters.abbreviation
=========================================
Abbreviation / acronym compression — entity *form* gets shorter while
the referent stays the same.

::

    'United States of America' -> 'USA'
    'Republican Party'         -> 'GOP'
    'United Kingdom'           -> 'UK'

Distinct from the *synonym* augmenter, which swaps to a colloquial
nickname or descriptive phrase ("the Kings", "the actor X").

Resolution order
----------------
1. Static curated dictionary (case-insensitive lookup).
2. LLM fallback (when ``ctx.llm.enabled``): one short prompt asking
   for the canonical short form / acronym, validated by checking the
   reply is shorter than the input and isn't a paraphrase.
"""

from __future__ import annotations

from typing import Optional

from data_augmentation.augmenters.base import Augmenter, AugContext
from data_augmentation.llm import first_nonempty_line


# ── Curated dictionary ──────────────────────────────────────────────────────
# Lower-cased keys → canonical short form.  Extend as new datasets surface
# new entities.  Keep entries domain-agnostic — we don't ship a sports
# nickname dictionary here; that's the synonym augmenter's job.

_KNOWN_ABBREVIATIONS: dict[str, str] = {
    # Countries / regions
    "united states of america":         "USA",
    "united states":                    "US",
    "united kingdom":                   "UK",
    "united kingdom of great britain":  "UK",
    "european union":                   "EU",
    "people's republic of china":       "PRC",
    "soviet union":                     "USSR",
    "united nations":                   "UN",
    "north atlantic treaty organization": "NATO",
    # US politics
    "republican party":                 "GOP",
    "democratic party":                 "Dems",
    "democratic national committee":    "DNC",
    "republican national committee":    "RNC",
    "house of representatives":         "House",
    "supreme court of the united states": "SCOTUS",
    # Tech / orgs
    "international business machines":  "IBM",
    "national aeronautics and space administration": "NASA",
    "federal bureau of investigation":  "FBI",
    "central intelligence agency":      "CIA",
    "world health organization":        "WHO",
    "world trade organization":         "WTO",
    # Sports leagues
    "national basketball association":  "NBA",
    "national football league":         "NFL",
    "national hockey league":           "NHL",
    "major league baseball":            "MLB",
    # Common adjectivals (also useful as compressions)
    "american":                         "US",
    "soviet":                           "USSR",
}


_LLM_SYSTEM = (
    "You output the canonical short form / acronym for a named entity.  "
    "Respond with ONLY the short form on a single line — no quotes, no "
    "punctuation, no explanation.  If no widely-recognised short form "
    "exists, respond with the single word NONE."
)

_LLM_PROMPT = (
    "Entity: {entity}\n"
    "Short form (acronym, initialism, or shortened name):"
)


class AbbreviationAugmenter(Augmenter):
    name = "abbrev"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        if not surface:
            return None

        # 1. Static dict
        key = surface.strip().lower()
        if key in _KNOWN_ABBREVIATIONS:
            cand = _KNOWN_ABBREVIATIONS[key]
            if cand and cand.lower() != key:
                return cand

        # 2. LLM fallback
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
        # Sanity-check: must be shorter than original and different.
        if len(cand) >= len(surface):
            return None
        if cand.lower() == surface.lower():
            return None
        return cand
