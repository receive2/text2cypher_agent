"""
data_augmentation.validity
===========================
DB-grounded validity judging + the splice grammar guard.

Design rule (anti-circularity): LLMs *propose* surface forms; this module
*judges* them, using only the graph database's own values and string
structure — never an LLM and never the system under test.  Because every
entity span is seeded from a gold-cypher literal, the canonical DB value
``v`` is known per sample, so we can check, with no model in the loop:

  * **collision** — the perturbed surface must not (case-insensitively)
    equal a *different* existing value of the same (label, property);
    this is what stops ``WN5 → NW5`` and ``Wagner → <another Wagner>``.
  * **uniqueness** (partial) — the reduced surface must, by case-insensitive
    containment, match exactly the canonical value and no other.
  * **margin** (typo) — the canonical value is the unique value within
    Damerau-Levenshtein distance 1 of the perturbed surface; no other value
    sits within distance 1.

When no :class:`ValueProvider` is supplied the checks return
``("unchecked", ...)`` and the pipeline records the edit as unverified —
generation against live graphs (Phase 2/3) must supply a provider.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Dict, FrozenSet, Optional, Tuple

from loguru import logger


# ──────────────────────────────────────────────────────────────────────────────
# Damerau–Levenshtein (optimal string alignment) — adjacent transposition = 1
# ──────────────────────────────────────────────────────────────────────────────

def damerau_distance(a: str, b: str) -> int:
    """
    Optimal string alignment distance: insert / delete / substitute /
    transpose-adjacent each cost 1.  Used by the typo strategy (a single
    transposition is one typo, which plain Levenshtein wrongly scores as 2 —
    the bug that drove typo to 0%) and by the margin check.
    """
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev2 = list(range(lb + 1))      # row i-2
    prev = None                      # row i-1
    cur = [0] * (lb + 1)
    # row 0
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(
                prev[j] + 1,        # deletion
                cur[j - 1] + 1,     # insertion
                prev[j - 1] + cost  # substitution
            )
            if (i > 1 and j > 1
                    and a[i - 1] == b[j - 2]
                    and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)  # transposition
        prev2, prev = prev, cur
    return prev[lb]


def damerau_le(a: str, b: str, k: int = 1) -> bool:
    """True iff the Damerau (OSA) distance between *a* and *b* is ≤ k."""
    if abs(len(a) - len(b)) > k:
        return False
    return damerau_distance(a, b) <= k


# ──────────────────────────────────────────────────────────────────────────────
# Value providers
# ──────────────────────────────────────────────────────────────────────────────

class ValueProvider(ABC):
    """Supplies the set of distinct text values for a (label, property)."""

    @abstractmethod
    def values(self, label: Optional[str], prop: Optional[str]) -> FrozenSet[str]:
        """All distinct non-null string values of ``label.prop`` in the graph.

        Implementations should return an empty set for unknown (label, prop).
        """
        raise NotImplementedError


class InMemoryValueProvider(ValueProvider):
    """Backed by a literal ``{(label, prop): {values...}}`` mapping. For tests
    and offline development."""

    def __init__(self, table: Dict[Tuple[Optional[str], Optional[str]], FrozenSet[str]]):
        self._t = {k: frozenset(v) for k, v in table.items()}
        # also index by prop-only and a global union for fallback when the
        # extractor couldn't resolve the label.
        self._by_prop: Dict[Optional[str], FrozenSet[str]] = {}
        allv: set = set()
        for (lbl, prop), vals in self._t.items():
            allv |= set(vals)
            self._by_prop[prop] = self._by_prop.get(prop, frozenset()) | vals
        self._all = frozenset(allv)

    def values(self, label, prop):
        if (label, prop) in self._t:
            return self._t[(label, prop)]
        if label is None and prop in self._by_prop:
            return self._by_prop[prop]
        if label is None and prop is None:
            return self._all
        return frozenset()


class Neo4jValueProvider(ValueProvider):
    """
    Live-graph provider.  **Phase 2 — requires a reachable Neo4j; untested
    without one.**  Caches distinct-value sets per (label, prop).  Uses the
    same distinct-value pattern as ``embedding.embedding_helper``.
    """

    def __init__(self, driver, database: str):
        self._driver = driver
        self._db = database
        self._cache: Dict[Tuple[Optional[str], Optional[str]], FrozenSet[str]] = {}

    def values(self, label, prop):
        if prop is None:
            return frozenset()
        key = (label, prop)
        if key in self._cache:
            return self._cache[key]
        # Node-label scoped if we know the label, else scan any node carrying prop.
        if label:
            q = (f"MATCH (n:`{label}`) WHERE n.`{prop}` IS NOT NULL "
                 f"RETURN DISTINCT toString(n.`{prop}`) AS v")
        else:
            q = (f"MATCH (n) WHERE n.`{prop}` IS NOT NULL "
                 f"RETURN DISTINCT toString(n.`{prop}`) AS v")
        out: set = set()
        try:
            with self._driver.session(database=self._db) as s:
                for rec in s.run(q):
                    v = rec.get("v")
                    if isinstance(v, str) and v.strip():
                        out.add(v.strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"validity.Neo4jValueProvider: query failed for {key}: {exc}")
        fs = frozenset(out)
        self._cache[key] = fs
        return fs


# ──────────────────────────────────────────────────────────────────────────────
# Validity checks
# ──────────────────────────────────────────────────────────────────────────────

# Reason codes (also written to _aug_meta on drop).
OK         = "ok"
UNCHECKED  = "unchecked"   # no provider — generation must supply one
COLLISION  = "collision"   # surface equals a different existing value
NOT_UNIQUE = "not_unique"  # partial: containment matches >1 value
MARGIN     = "margin"      # typo: another value within Damerau-1


def _ci_set(values: FrozenSet[str]) -> Dict[str, str]:
    """Lower-cased value → original (last wins; only identity matters here)."""
    return {v.lower(): v for v in values}


def check_validity(
    strategy: str,
    surface: str,
    canonical: str,
    label: Optional[str],
    prop: Optional[str],
    provider: Optional[ValueProvider],
) -> Tuple[bool, str]:
    """
    Judge a proposed perturbation ``canonical → surface`` against the DB.

    Returns ``(ok, reason)``.  ``ok`` is True for both ``OK`` and ``UNCHECKED``
    (the pipeline still commits an unchecked edit but flags it unverified);
    it is False for COLLISION / NOT_UNIQUE / MARGIN.
    """
    if provider is None:
        return True, UNCHECKED

    values = provider.values(label, prop)
    if not values:
        return True, UNCHECKED

    s_lc = surface.lower()
    c_lc = canonical.lower()
    ci = _ci_set(values)

    # Universal collision check: the new surface must not BE a different value.
    if s_lc in ci and s_lc != c_lc:
        return False, COLLISION

    if strategy == "partial":
        # Case-insensitive containment must resolve to exactly the canonical.
        hits = [orig for lc, orig in ci.items() if s_lc in lc]
        # the canonical itself contains the reduced surface; ensure no OTHER does.
        others = [h for h in hits if h.lower() != c_lc]
        if others:
            return False, NOT_UNIQUE

    if strategy == "typo":
        # Margin: no value other than the canonical sits within Damerau-1.
        for lc in ci:
            if lc == c_lc:
                continue
            if damerau_le(surface, ci[lc], 1):
                return False, MARGIN

    return True, OK


# ──────────────────────────────────────────────────────────────────────────────
# Splice grammar guard
# ──────────────────────────────────────────────────────────────────────────────

_ARTICLES = {"the", "a", "an"}
_WORD_RE = re.compile(r"\S+")


def _vowel_sound(word: str) -> bool:
    """Crude a/an heuristic: does *word* start with a vowel sound?"""
    w = word.lower().lstrip("\"'([")
    if not w:
        return False
    return w[0] in "aeiou"


def splice(nl: str, start: int, end: int, new_surface: str) -> Optional[str]:
    """
    Replace ``nl[start:end]`` with *new_surface* and repair the seam:

      * duplicated article  ("... the <the X>"  → "... the X")
      * a/an agreement before the inserted surface
      * immediate word doubling at either seam ("X X" → "X")

    Returns the cleaned NL, or ``None`` if a duplication can't be resolved
    cleanly (caller then declines the edit).
    """
    before = nl[:start]
    after = nl[end:]

    prev_words = _WORD_RE.findall(before)
    new_words = new_surface.split()
    if not new_words:
        return None

    # 1. Duplicated leading article: drop it from the inserted surface.
    if prev_words and new_words:
        if prev_words[-1].lower() in _ARTICLES and new_words[0].lower() in _ARTICLES:
            new_words = new_words[1:]
            if not new_words:
                return None

    # 2. a/an agreement: if the preceding word is an article, make it agree
    #    with the (possibly new) first word of the inserted surface.
    if prev_words and prev_words[-1].lower() in {"a", "an"} and new_words:
        correct = "an" if _vowel_sound(new_words[0]) else "a"
        # preserve capitalization of the original article
        if prev_words[-1][0].isupper():
            correct = correct.capitalize()
        if prev_words[-1] != correct:
            # rewrite the last word of `before`
            idx = before.rfind(prev_words[-1])
            before = before[:idx] + correct + before[idx + len(prev_words[-1]):]

    # 3. Seam word-doubling on the left: last word of `before` == first new word.
    if prev_words and new_words and prev_words[-1].lower() == new_words[0].lower():
        new_words = new_words[1:]
        if not new_words:
            return None

    cleaned_surface = " ".join(new_words)

    # 4. Seam word-doubling on the right: last new word == first word after.
    after_words = _WORD_RE.findall(after)
    if after_words and cleaned_surface:
        cs_words = cleaned_surface.split()
        if cs_words and cs_words[-1].lower() == after_words[0].lower():
            # drop the duplicate from `after`
            idx = after.find(after_words[0])
            after = after[:idx] + after[idx + len(after_words[0]):]

    out = before + cleaned_surface + after
    # Final safety net: no residual doubled article / word at any boundary.
    if re.search(r"\b(the|a|an)\s+\1\b", out, re.IGNORECASE):
        return None
    if re.search(r"\b(\w+)\s+\1\b", out, re.IGNORECASE):
        # allow legitimately repeated words only if they were in the source;
        # any NEW doubling we couldn't fix → decline.
        if not re.search(r"\b(\w+)\s+\1\b", nl, re.IGNORECASE):
            return None
    return out
