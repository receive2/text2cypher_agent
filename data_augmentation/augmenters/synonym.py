"""
data_augmentation.augmenters.synonym
====================================
Nickname / colloquial swap — same referent, different surface form, but
NOT a compression (that's the abbreviation augmenter's job).

::

    'Sacramento Kings' -> 'the Kings'
    'Tom Hanks'        -> 'the actor Tom Hanks'
    'Los Angeles Lakers' -> 'the Lakers'
    'Barack Obama'     -> 'Obama'  (declined here — that's an abbrev/partial)

Resolution order
----------------
1. Static curated dictionary (case-insensitive lookup).
2. LLM fallback (when ``ctx.llm.enabled``): asks for a colloquial
   nickname or short descriptive phrase.  Strict validation: the reply
   must NOT be the original surface form, must NOT be a longer
   paraphrase that contains the entire NL clause, and must contain at
   least one *new* word OR be at least one token shorter than the
   original.
"""

from __future__ import annotations

from typing import Optional

from data_augmentation.augmenters.base import Augmenter, AugContext
from data_augmentation.llm import first_nonempty_line


# ── Curated nickname/colloquial dictionary ──────────────────────────────────
# Lower-cased keys → list of candidate substitutions.  The augmenter
# picks one at random for variety.  Curated to stay close to natural
# usage.  Extend as needed.

_KNOWN_SYNONYMS: dict[str, tuple[str, ...]] = {
    # NBA nicknames
    "sacramento kings":      ("the Kings", "the Kings of Sacramento"),
    "los angeles lakers":    ("the Lakers", "LA Lakers"),
    "boston celtics":        ("the Celtics",),
    "golden state warriors": ("the Warriors", "GSW"),
    "chicago bulls":         ("the Bulls",),
    "miami heat":             ("the Heat",),
    "new york knicks":       ("the Knicks",),
    "philadelphia 76ers":    ("the Sixers", "the 76ers"),
    "houston rockets":       ("the Rockets",),
    "dallas mavericks":      ("the Mavs", "the Mavericks"),
    # NFL
    "new england patriots":  ("the Patriots", "the Pats"),
    "green bay packers":     ("the Packers",),
    "dallas cowboys":        ("the Cowboys", "America's Team"),
    # Famous people — descriptive nominal phrasings
    "tom hanks":             ("the actor Tom Hanks",),
    "leonardo dicaprio":     ("the actor Leonardo DiCaprio",),
    "barack obama":          ("former president Obama", "President Obama"),
    "donald trump":          ("former president Trump",),
    "joe biden":             ("President Biden",),
    "elon musk":             ("the entrepreneur Elon Musk", "Musk"),
    # Countries / regions — colloquial / descriptive forms (NOT abbrev)
    "united states of america": ("America", "the States"),
    "united states":         ("America",),
    "united kingdom":        ("Britain",),
    "soviet union":          ("the USSR",),
    "people's republic of china": ("mainland China",),
    # Cities
    "new york city":         ("the Big Apple", "NYC"),
    "los angeles":           ("LA",),
    "san francisco":         ("SF", "the Bay Area's biggest city"),
    # Tech / orgs
    "microsoft corporation": ("Microsoft",),
    "alphabet inc":          ("Google's parent company",),
    # Politics
    "house committee on the judiciary": ("the Judiciary Committee",),
    "house committee on education and the workforce": ("the Education Committee",),
}


_LLM_SYSTEM = (
    "You provide a colloquial nickname or short descriptive phrase for a "
    "named entity, suitable for substituting INSIDE an existing question "
    "without rewording the rest of the sentence.  Examples:\n"
    "  'Sacramento Kings' -> 'the Kings'\n"
    "  'Tom Hanks'        -> 'the actor Tom Hanks'\n"
    "  'United States'    -> 'America'\n"
    "Constraints:\n"
    "  - Output ONE substitution on a single line, no quotes, no "
    "explanation.\n"
    "  - The substitution must refer to the SAME entity; do NOT generalise "
    "or paraphrase.\n"
    "  - Do NOT just produce an acronym (that's a different task).\n"
    "  - If no good colloquial form exists, output the single word NONE."
)

_LLM_PROMPT = "Entity: {entity}\nColloquial substitution:"


class SynonymAugmenter(Augmenter):
    name = "synonym"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        if not surface:
            return None

        # 1. Static dict
        key = surface.strip().lower()
        if key in _KNOWN_SYNONYMS:
            opts = _KNOWN_SYNONYMS[key]
            # Filter out anything that equals the original (case-insensitive).
            opts = tuple(o for o in opts if o.lower() != key)
            if opts:
                return ctx.rng.choice(opts)

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
        if cand.lower() == surface.lower():
            return None

        # Reject runaway paraphrases — anything more than 4× the original
        # word count is almost certainly the model rewriting the whole
        # sentence rather than naming the entity.
        if len(cand.split()) > max(4, 4 * len(surface.split())):
            return None
        return cand
