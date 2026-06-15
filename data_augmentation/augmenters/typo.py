"""
data_augmentation.augmenters.typo
=================================
Typing-noise simulation — in-house, no nlpaug (whose version-dependent RNG
broke reproducibility, and whose swap action produced transpositions the old
plain-Levenshtein gate then rejected, driving typo to 0%).

Exactly one edit per surface, of one of four real-keyboard-slip kinds:

    keyboard substitution   'Sacramento' -> 'Sxcramento'   (adjacent key)
    adjacent transposition  'Barletta'   -> 'Balretta'     (finger order)
    deletion                'Barletta'   -> 'Barleta'
    doubling                'Barletta'   -> 'Barlettta'

Word-initial characters are never touched (entity recognition is anchored
on them; a leading-char change is a different entity, not a typo).  The
pipeline's margin check (validity.check_validity) additionally rejects any
result that lands within Damerau-1 of *another* DB value (the WN5→NW5 class).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from data_augmentation.augmenters.base import (
    Augmenter, AugContext, EditProposal, SOURCE_ALGORITHMIC,
)

# QWERTY adjacency for keyboard-slip substitutions.
_ADJ = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etdf", "t": "ryfg",
    "y": "tugh", "u": "yihj", "i": "uojk", "o": "ipkl", "p": "ol",
    "a": "qwsz", "s": "weadzx", "d": "ersfcx", "f": "rtdgcv", "g": "tyfhvb",
    "h": "yugjbn", "j": "uihknm", "k": "iojlm", "l": "opk",
    "z": "asx", "x": "sdzc", "c": "dfxv", "v": "fgcb", "b": "ghvn",
    "n": "hjbm", "m": "jkn",
}


def _alterable_positions(word: str) -> List[int]:
    """Alphabetic positions in *word* excluding index 0 (word-initial)."""
    return [i for i, c in enumerate(word) if c.isalpha() and i > 0]


class TypoAugmenter(Augmenter):
    name = "typo"

    def apply(self, surface: str, ctx: AugContext) -> Optional[EditProposal]:
        if not surface or len(surface.strip()) < 3:
            return None

        words = surface.split()
        # words with at least one alterable (non-initial alpha) position
        wi_candidates = [i for i, w in enumerate(words) if _alterable_positions(w)]
        if not wi_candidates:
            return None

        # A few attempts so a no-op op (e.g. doubling that equals nothing
        # useful, or a substitution picking the same char) still yields a typo.
        for _ in range(6):
            wi = ctx.rng.choice(wi_candidates)
            new_word = self._one_edit(words[wi], ctx)
            if new_word and new_word != words[wi]:
                out = list(words)
                out[wi] = new_word
                cand = " ".join(out)
                if cand != surface:
                    return EditProposal(surface=cand, source=SOURCE_ALGORITHMIC)
        return None

    def _one_edit(self, word: str, ctx: AugContext) -> Optional[str]:
        positions = _alterable_positions(word)
        if not positions:
            return None
        op = ctx.rng.choice(("sub", "transpose", "delete", "double"))
        chars = list(word)

        if op == "sub":
            p = ctx.rng.choice(positions)
            lo = chars[p].lower()
            repl = _ADJ.get(lo)
            if not repl:
                return None
            nc = ctx.rng.choice(repl)
            chars[p] = nc.upper() if chars[p].isupper() else nc
            return "".join(chars)

        if op == "transpose":
            pairs: List[Tuple[int, int]] = [
                (positions[i], positions[i + 1])
                for i in range(len(positions) - 1)
                if positions[i + 1] == positions[i] + 1
            ]
            if not pairs:
                return None
            a, b = ctx.rng.choice(pairs)
            chars[a], chars[b] = chars[b], chars[a]
            return "".join(chars)

        if op == "delete":
            # keep ≥2 chars so the word stays a word
            if len(word) <= 2:
                return None
            p = ctx.rng.choice(positions)
            del chars[p]
            return "".join(chars)

        if op == "double":
            p = ctx.rng.choice(positions)
            chars.insert(p, chars[p])
            return "".join(chars)

        return None
