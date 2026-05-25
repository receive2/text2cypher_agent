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

Context-aware prompt
--------------------
Earlier versions asked the LLM "Entity: <X>\\nDescriptive paraphrase:"
in isolation, which produced surface-form artifacts when injected back:

* original: "...won **the** Amanda Award..."
* LLM reply: "the Amanda Award for Best Foreign Feature Film" (it
  prepended an article without knowing one was already there)
* spliced result: "...won **the the** Amanda Award..."

To kill this class of bug we now hand the LLM the WHOLE question with
the target entity wrapped in ``<ENT>...</ENT>`` markers and tell it to
return the rewritten question.  The augmenter then string-diffs the
markers' content and uses that as the perturbed surface.

Declines when ``ctx.llm.enabled`` is False — there is no static
fallback for paraphrase.
"""

from __future__ import annotations

import re
from typing import Optional

from data_augmentation.augmenters.base import Augmenter, AugContext


_ENT_OPEN  = "<ENT>"
_ENT_CLOSE = "</ENT>"

_EXTRACT_RE = re.compile(
    re.escape(_ENT_OPEN) + r"(.+?)" + re.escape(_ENT_CLOSE),
    re.DOTALL,
)


_LLM_SYSTEM = (
    "You rewrite a question by replacing the span wrapped in <ENT>...</ENT> "
    "with a short descriptive paraphrase that keeps the original entity "
    "string visible inside the paraphrase.  Examples:\n"
    "  Input : Who directed <ENT>Tom Hanks</ENT>'s latest film?\n"
    "  Output: Who directed <ENT>the actor Tom Hanks</ENT>'s latest film?\n"
    "  Input : How many championships have the <ENT>Sacramento Kings</ENT> won?\n"
    "  Output: How many championships have the <ENT>Kings of Sacramento</ENT> won?\n"
    "Constraints:\n"
    "  - Output the FULL rewritten question on a single line.\n"
    "  - Keep the <ENT>...</ENT> markers in the output.\n"
    "  - Change ONLY the text inside <ENT>...</ENT>.  Every character "
    "outside the markers must be byte-identical to the input.\n"
    "  - The new <ENT>...</ENT> content MUST contain the original "
    "entity string verbatim.\n"
    "  - If the word IMMEDIATELY before <ENT> is 'the', 'a' or 'an', do NOT "
    "repeat that article inside the paraphrase.\n"
    "  - Keep it short — the new content should be at most ~6 words longer "
    "than the original entity.\n"
    "  - Do NOT change the referent or generalise.\n"
    "  - If you cannot produce a faithful paraphrase under these rules, "
    "respond with the single word NONE."
)


def _build_marked_question(nl: str, start: int, end: int) -> str:
    return nl[:start] + _ENT_OPEN + nl[start:end] + _ENT_CLOSE + nl[end:]


def _outside_unchanged(input_marked: str, output_marked: str) -> bool:
    """
    Verify that every character OUTSIDE the <ENT>...</ENT> markers is
    byte-identical between the LLM's input and output.  Cheap belt-and-
    braces against runaway rewrites.
    """
    pat = re.escape(_ENT_OPEN) + r".*?" + re.escape(_ENT_CLOSE)
    in_stripped  = re.sub(pat, _ENT_OPEN + _ENT_CLOSE, input_marked,  count=1, flags=re.DOTALL)
    out_stripped = re.sub(pat, _ENT_OPEN + _ENT_CLOSE, output_marked, count=1, flags=re.DOTALL)
    return in_stripped == out_stripped


class ParaphraseAugmenter(Augmenter):
    name = "paraphrase"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        """
        Context-aware paraphrase.

        Unlike most augmenters, this one needs the surrounding sentence
        to avoid prefix duplication.  We pull the whole NL string and
        the span offsets from ``ctx`` (set by the pipeline at the start
        of each row).  When ``ctx`` doesn't carry an explicit span we
        fall back to a substring match of ``surface`` in ``ctx.nl``.
        """
        if not surface:
            return None
        if not ctx.llm.enabled:
            return None

        nl = getattr(ctx, "nl", None)
        if not nl:
            return None

        # Locate the span.  Prefer explicit (ctx.span_start, ctx.span_end)
        # set by the pipeline; fall back to first case-insensitive match.
        start = getattr(ctx, "span_start", None)
        end   = getattr(ctx, "span_end",   None)
        if start is None or end is None:
            lo = nl.lower().find(surface.lower())
            if lo < 0:
                return None
            start, end = lo, lo + len(surface)

        marked_in = _build_marked_question(nl, start, end)

        resp = ctx.llm.complete(marked_in, system=_LLM_SYSTEM)
        if not resp:
            return None
        resp = resp.strip()
        if resp.lower() == "none":
            return None

        # Extract the first <ENT>...</ENT> body from the reply.
        m = _EXTRACT_RE.search(resp)
        if not m:
            return None
        new_surface = m.group(1).strip()
        if not new_surface or new_surface.lower() == surface.lower():
            return None

        # Outside-markers byte-identical check.
        if not _outside_unchanged(marked_in, resp):
            return None

        # Substring-survives invariant: original entity must remain inside
        # the new surface (the paraphrase augmenter's whole contract).
        if surface.lower() not in new_surface.lower():
            return None

        # Length cap — same rule as before.
        max_words = max(len(surface.split()) + 6, 4 * len(surface.split()))
        if len(new_surface.split()) > max_words:
            return None

        return new_surface
