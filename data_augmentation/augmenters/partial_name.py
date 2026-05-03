"""
data_augmentation.augmenters.partial_name
=========================================
Partial-name simplification — the most common way users compress
multi-token entity names.

Examples
--------
::

    'Los Angeles Lakers' -> 'Lakers'         (drop leading tokens)
    'House Committee on Education and the Workforce' -> 'House Committee'  (drop trailing)
    'United States of America' -> 'United States'

Strategy
--------
Tokenise on whitespace, then choose to drop either the leading or the
trailing N tokens (1 ≤ N < #tokens).  Single-token entities are
declined.  We avoid dropping a single stop-word that would change the
entity referent (e.g. "of America" stays attached to "United States" —
we never strip purely interior content).
"""

from __future__ import annotations

import re
from typing import Optional

from data_augmentation.augmenters.base import Augmenter, AugContext


# Whitespace-only tokeniser (preserves casing/punctuation).
_TOKEN_RE = re.compile(r"\S+")


class PartialNameAugmenter(Augmenter):
    name = "partial"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        toks = _TOKEN_RE.findall(surface)
        if len(toks) < 2:
            return None

        # How many tokens to drop (1 ≤ k < n).  Bias toward dropping
        # one token so the perturbation stays close to natural usage.
        n = len(toks)
        # Weighted choice: 1 token → highest probability, more → less.
        weights = [1.0 / (i + 1) for i in range(n - 1)]
        k = ctx.rng.choices(range(1, n), weights=weights, k=1)[0]

        # Drop from leading or trailing — flip a coin.
        side = ctx.rng.choice(("leading", "trailing"))
        if side == "leading":
            kept = toks[k:]
        else:
            kept = toks[:-k]

        if not kept:
            return None
        cand = " ".join(kept)
        if cand == surface:
            return None
        return cand
