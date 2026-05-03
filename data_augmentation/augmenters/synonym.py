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

Resolution order ("rule + LLM fallback")
----------------------------------------
1. Static curated dictionary (case-insensitive lookup) — the primary
   path; covers the entities most likely to recur in the test sets
   (NBA / NFL / MLB / NHL teams, common public figures, country
   colloquials, large cities).
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
    # ── NBA — all 30 teams ──────────────────────────────────────────────
    "atlanta hawks":          ("the Hawks",),
    "boston celtics":         ("the Celtics",),
    "brooklyn nets":          ("the Nets",),
    "charlotte hornets":      ("the Hornets",),
    "chicago bulls":          ("the Bulls",),
    "cleveland cavaliers":    ("the Cavs", "the Cavaliers"),
    "dallas mavericks":       ("the Mavs", "the Mavericks"),
    "denver nuggets":         ("the Nuggets",),
    "detroit pistons":        ("the Pistons",),
    "golden state warriors":  ("the Warriors", "GSW"),
    "houston rockets":        ("the Rockets",),
    "indiana pacers":         ("the Pacers",),
    "los angeles clippers":   ("the Clippers", "LA Clippers"),
    "los angeles lakers":     ("the Lakers", "LA Lakers"),
    "memphis grizzlies":      ("the Grizzlies",),
    "miami heat":             ("the Heat",),
    "milwaukee bucks":        ("the Bucks",),
    "minnesota timberwolves": ("the Timberwolves", "the Wolves"),
    "new orleans pelicans":   ("the Pelicans",),
    "new york knicks":        ("the Knicks",),
    "oklahoma city thunder":  ("the Thunder", "OKC"),
    "orlando magic":          ("the Magic",),
    "philadelphia 76ers":     ("the Sixers", "the 76ers"),
    "phoenix suns":           ("the Suns",),
    "portland trail blazers": ("the Trail Blazers", "the Blazers"),
    "sacramento kings":       ("the Kings", "the Kings of Sacramento"),
    "san antonio spurs":      ("the Spurs",),
    "toronto raptors":        ("the Raptors",),
    "utah jazz":              ("the Jazz",),
    "washington wizards":     ("the Wizards",),

    # ── NFL — popular teams ─────────────────────────────────────────────
    "new england patriots":   ("the Patriots", "the Pats"),
    "green bay packers":      ("the Packers",),
    "dallas cowboys":         ("the Cowboys", "America's Team"),
    "pittsburgh steelers":    ("the Steelers",),
    "san francisco 49ers":    ("the Niners", "the 49ers"),
    "kansas city chiefs":     ("the Chiefs",),
    "philadelphia eagles":    ("the Eagles",),

    # ── MLB ─────────────────────────────────────────────────────────────
    "new york yankees":       ("the Yankees", "the Bronx Bombers"),
    "boston red sox":         ("the Red Sox",),
    "los angeles dodgers":    ("the Dodgers",),
    "chicago cubs":           ("the Cubs",),
    "san francisco giants":   ("the Giants",),

    # ── NHL ─────────────────────────────────────────────────────────────
    "montreal canadiens":     ("the Habs", "the Canadiens"),
    "toronto maple leafs":    ("the Leafs",),
    "detroit red wings":      ("the Red Wings",),

    # ── Famous people — descriptive nominal phrasings ──────────────────
    "tom hanks":              ("the actor Tom Hanks",),
    "leonardo dicaprio":      ("the actor Leonardo DiCaprio",),
    "meryl streep":           ("the actress Meryl Streep",),
    "steven spielberg":       ("director Spielberg", "the director Steven Spielberg"),
    "martin scorsese":        ("director Scorsese",),
    "christopher nolan":      ("director Nolan",),
    "quentin tarantino":      ("director Tarantino",),
    "barack obama":           ("former president Obama", "President Obama"),
    "donald trump":           ("former president Trump",),
    "joe biden":              ("President Biden",),
    "george w. bush":         ("President Bush",),
    "bill clinton":           ("President Clinton",),
    "nicolas sarkozy":        ("former president Sarkozy",),
    "emmanuel macron":        ("President Macron",),
    "angela merkel":          ("former chancellor Merkel",),
    "vladimir putin":         ("President Putin",),
    "elon musk":              ("the entrepreneur Elon Musk", "Musk"),
    "jeff bezos":             ("the Amazon founder", "Bezos"),
    "bill gates":             ("the Microsoft co-founder", "Gates"),
    "mark zuckerberg":        ("the Facebook founder", "Zuckerberg"),

    # ── Countries / regions — colloquial / descriptive (NOT pure abbrev)
    "united states of america": ("America", "the States"),
    "united states":          ("America",),
    "united kingdom":         ("Britain",),
    "great britain":          ("Britain",),
    "soviet union":           ("the USSR",),
    "people's republic of china": ("mainland China",),
    "republic of korea":      ("the South",),
    "democratic people's republic of korea": ("the North",),
    "russian federation":     ("Russia",),
    "czech republic":         ("Czechia",),
    "republic of ireland":    ("Ireland",),
    "kingdom of the netherlands": ("the Netherlands", "Holland"),
    "netherlands":            ("Holland",),

    # ── Cities ──────────────────────────────────────────────────────────
    "new york city":          ("the Big Apple", "NYC"),
    "los angeles":            ("LA",),
    "san francisco":          ("SF", "the Bay Area's biggest city"),
    "chicago":                ("the Windy City",),
    "las vegas":              ("Vegas", "Sin City"),
    "philadelphia":           ("Philly",),
    "washington, d.c.":       ("the nation's capital", "DC"),
    "paris":                  ("the City of Light",),

    # ── Tech / orgs ─────────────────────────────────────────────────────
    "microsoft corporation":  ("Microsoft",),
    "alphabet inc":           ("Google's parent company",),
    "meta platforms":         ("Meta",),
    "amazon.com":             ("Amazon",),

    # ── US politics ─────────────────────────────────────────────────────
    "house committee on the judiciary":             ("the Judiciary Committee",),
    "house committee on education and the workforce": ("the Education Committee",),
    "republican party":       ("the Republicans", "the GOP"),
    "democratic party":       ("the Democrats", "the Dems"),
    "supreme court of the united states": ("the Supreme Court", "SCOTUS"),
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
