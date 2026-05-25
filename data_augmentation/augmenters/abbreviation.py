"""
data_augmentation.augmenters.abbreviation
=========================================
Abbreviation / acronym compression — entity *form* gets shorter (or
longer) while the referent stays the same.

::

    'United States of America' -> 'USA'
    'Republican Party'         -> 'GOP'
    'United Kingdom'           -> 'UK'
    'USA'                      -> 'United States of America'   # reverse
    'NYC'                      -> 'New York City'              # reverse

Distinct from the *synonym* augmenter, which swaps to a colloquial
nickname or descriptive phrase ("the Kings", "the actor X").

Resolution order
----------------
1. **Curated pair table** (case-insensitive, *bidirectional*).  If the
   surface matches the long form, return the short form; if it matches
   the short form, return the long form.  This is the primary source —
   the table is hand-curated for the entities most likely to appear in
   the cypherbench / mind-the-query / zograscope test sets.
2. **LLM fallback** (when ``ctx.llm.enabled``): one short prompt asking
   for the canonical short form / acronym, validated by checking the
   reply is shorter than the input and isn't a paraphrase.

Maintenance note
----------------
When new datasets surface entities that should expand / contract,
extend ``_PAIRS`` rather than the LLM prompt.  The static path is much
cheaper and stays consistent across runs.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from data_augmentation.augmenters.base import Augmenter, AugContext
from data_augmentation.llm import first_nonempty_line


# ── Curated bidirectional pair table ────────────────────────────────────────
# Hand-curated (long_form, short_form) pairs.  At module load both
# directions are loaded into ``_KNOWN_ABBREVIATIONS``: long → short and
# short → long.  The first pair that defines a short form wins for the
# reverse direction (so "US" → "United States" rather than "United
# States of America" because the former pair comes first).

_PAIRS: List[Tuple[str, str]] = [
    # Countries / regions / supranational orgs
    ("United States",                                 "US"),
    ("United States of America",                      "USA"),
    ("United Kingdom",                                "UK"),
    ("United Kingdom of Great Britain",               "UK"),
    ("United Arab Emirates",                          "UAE"),
    ("Soviet Union",                                  "USSR"),
    ("Union of Soviet Socialist Republics",           "USSR"),
    ("European Union",                                "EU"),
    ("People's Republic of China",                    "PRC"),
    ("Republic of Korea",                             "South Korea"),
    ("Democratic People's Republic of Korea",         "North Korea"),
    ("Czech Republic",                                "Czechia"),
    ("Republic of Ireland",                           "Ireland"),
    ("Russian Federation",                            "Russia"),
    ("Federative Republic of Brazil",                 "Brazil"),
    ("Federal Republic of Germany",                   "Germany"),
    ("Kingdom of the Netherlands",                    "Netherlands"),
    ("Kingdom of Spain",                              "Spain"),

    # International organisations
    ("United Nations",                                "UN"),
    ("North Atlantic Treaty Organization",            "NATO"),
    ("World Health Organization",                     "WHO"),
    ("World Trade Organization",                      "WTO"),
    ("International Monetary Fund",                   "IMF"),
    ("Organisation for Economic Co-operation and Development", "OECD"),
    ("Association of Southeast Asian Nations",        "ASEAN"),

    # US politics
    ("Republican Party",                              "GOP"),
    ("Democratic Party",                              "Dems"),
    ("Democratic National Committee",                 "DNC"),
    ("Republican National Committee",                 "RNC"),
    ("House of Representatives",                      "House"),
    ("Supreme Court of the United States",            "SCOTUS"),

    # US federal agencies
    ("Federal Bureau of Investigation",               "FBI"),
    ("Central Intelligence Agency",                   "CIA"),
    ("National Aeronautics and Space Administration", "NASA"),
    ("National Security Agency",                      "NSA"),
    ("Internal Revenue Service",                      "IRS"),
    ("Food and Drug Administration",                  "FDA"),
    ("Centers for Disease Control and Prevention",    "CDC"),
    ("Department of Defense",                         "DoD"),
    ("Department of Justice",                         "DoJ"),
    ("Environmental Protection Agency",               "EPA"),

    # Tech companies
    ("International Business Machines",               "IBM"),
    ("Microsoft Corporation",                         "Microsoft"),
    ("Alphabet Inc",                                  "Google"),
    ("Meta Platforms",                                "Meta"),
    ("Amazon.com",                                    "Amazon"),

    # Sports leagues
    ("National Basketball Association",               "NBA"),
    ("National Football League",                      "NFL"),
    ("National Hockey League",                        "NHL"),
    ("Major League Baseball",                         "MLB"),
    ("Federation Internationale de Football Association", "FIFA"),
    ("Union of European Football Associations",       "UEFA"),

    # Cities
    ("New York City",                                 "NYC"),
    ("Los Angeles",                                   "LA"),
    ("San Francisco",                                 "SF"),
    ("Washington, D.C.",                              "DC"),

    # Common adjectivals / common nouns
    ("American",                                      "US"),
    ("Soviet",                                        "USSR"),
]


def _build_lookup(pairs: List[Tuple[str, str]]) -> Dict[str, str]:
    """
    Build a case-insensitive bidirectional lookup.  Long forms always
    map to their paired short form.  Short forms map to the FIRST long
    form they're paired with (so "US" → "United States", not "American").
    """
    out: Dict[str, str] = {}
    for long_form, short_form in pairs:
        long_key = long_form.strip().lower()
        short_key = short_form.strip().lower()
        # Long → short: always set (later pairs overwrite earlier — the
        # last-defined short form wins, which matches the "more specific
        # wins" intuition for entries like "United States of America" →
        # "USA" coming after "American" → "US".
        out[long_key] = short_form
        # Short → long: first pair wins, so the most natural expansion
        # ("US" → "United States") comes from earlier-defined pairs.
        if short_key not in out:
            out[short_key] = long_form
    return out


_KNOWN_ABBREVIATIONS: Dict[str, str] = _build_lookup(_PAIRS)


# ── LLM gates ──────────────────────────────────────────────────────────────
#
# Earlier versions used a single "produce a short form" prompt with only
# `len(cand) < len(surface)` validation.  That accepted Wikipedia-style
# hallucinations like "The Saul Zaentz Company" → "SZC" and
# "Walt Disney Animation Studios" → "WDAS" — surface forms that aren't
# recognised anywhere outside the LLM's prior.
#
# The replacement is a strict two-stage gate:
#
#   Stage 1 (recognizability judge):
#       Ask the LLM whether the entity has a widely-recognised
#       abbreviation that a typical reader of news / Wikipedia would
#       resolve unambiguously back to the same entity.  Must return
#       YES / NO on a single line.
#   Stage 2 (production):
#       Only if stage 1 returned YES, ask for the abbreviation.  Reply
#       must be strictly shorter than the input and case-insensitively
#       different.
#
# Stage 1 is the load-bearing filter: it cuts the SZC / WDAS class
# entirely.  Stage 2 retains the existing length / equality validation.
# Two-shot prompting (vs. one merged prompt) keeps the judge's decision
# disentangled from the LLM's eagerness to "produce something".

_JUDGE_SYSTEM = (
    "You decide whether a named entity has a WIDELY-RECOGNISED "
    "abbreviation, acronym or initialism.  A widely-recognised "
    "abbreviation is one that a typical reader of news or Wikipedia "
    "would unambiguously resolve back to the same entity, and that "
    "appears as an alternative name in mainstream reference works.\n\n"
    "Examples:\n"
    "  - 'United States of America' → YES (USA)\n"
    "  - 'National Basketball Association' → YES (NBA)\n"
    "  - 'Federal Bureau of Investigation' → YES (FBI)\n"
    "  - 'New York City' → YES (NYC)\n"
    "  - 'The Saul Zaentz Company' → NO (no widely-known abbreviation)\n"
    "  - 'Walt Disney Animation Studios' → NO\n"
    "  - 'Mirage Enterprises' → NO\n"
    "  - 'BAFTA Award for Best Production Design' → NO\n"
    "  - 'Caroline Link' → NO (personal name, no standard abbreviation)\n\n"
    "Answer with ONLY 'YES' or 'NO' on a single line — nothing else."
)

_JUDGE_PROMPT = "Entity: {entity}\nIs there a widely-recognised abbreviation? (YES/NO):"

_PRODUCE_SYSTEM = (
    "You output the canonical, widely-recognised abbreviation / "
    "acronym / initialism for the entity below.  Respond with ONLY the "
    "abbreviation on a single line — no quotes, no punctuation, no "
    "explanation.  Use the form that would appear on Wikipedia or in "
    "major news outlets.  If you cannot produce one with high "
    "confidence, respond with NONE."
)

_PRODUCE_PROMPT = (
    "Entity: {entity}\n"
    "Widely-recognised abbreviation (e.g. USA, NBA, FBI, NYC):"
)


class AbbreviationAugmenter(Augmenter):
    """
    Static curated bidirectional dict + two-stage LLM recognizability judge.

    Static-dict path
        Returns the paired form whenever ``surface`` (case-insensitive)
        is on either side of a curated pair.  This is the cheapest path
        and most reliable for the ~50 hand-picked entries.

    LLM path (when ``ctx.llm.enabled`` and static dict misses)
        Stage 1: judge whether a widely-recognised abbreviation exists
        for the entity (YES/NO).  Stage 2 only fires on YES, asking
        for the abbreviation itself.  This kills the prior LLM-fallback's
        habit of inventing plausible-but-unknown acronyms like "SZC"
        for "The Saul Zaentz Company".
    """
    name = "abbrev"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        if not surface:
            return None

        # 1. Static curated bidirectional dict.
        key = surface.strip().lower()
        if key in _KNOWN_ABBREVIATIONS:
            cand = _KNOWN_ABBREVIATIONS[key]
            if cand and cand.lower() != key:
                return cand

        # 2. Two-stage LLM judge.
        if not ctx.llm.enabled:
            return None

        # Stage 1: recognizability judge.
        judge_resp = ctx.llm.complete(
            _JUDGE_PROMPT.format(entity=surface),
            system=_JUDGE_SYSTEM,
        )
        verdict = first_nonempty_line(judge_resp)
        if not verdict:
            return None
        verdict_norm = verdict.strip().rstrip(".").upper()
        if verdict_norm != "YES":
            return None

        # Stage 2: produce the abbreviation.
        resp = ctx.llm.complete(
            _PRODUCE_PROMPT.format(entity=surface),
            system=_PRODUCE_SYSTEM,
        )
        cand = first_nonempty_line(resp)
        if not cand:
            return None
        if cand.lower() == "none":
            return None
        # Strictly shorter than original AND different (case-insensitive).
        if len(cand) >= len(surface):
            return None
        if cand.lower() == surface.lower():
            return None
        # Reject anything containing whitespace longer than one space —
        # genuine abbreviations are compact tokens, not phrases.
        if cand.count(" ") > 1:
            return None
        return cand
