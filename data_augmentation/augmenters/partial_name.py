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
        # Require ≥3 tokens.  Two-token entities ("The Lakers",
        # "United States", "Caroline Link") have no token we can safely
        # drop without destroying the referent.
        if len(toks) < 3:
            return None

        # Always drop exactly ONE token.  The previous weighted multi-
        # token drop produced unrecoverable surfaces like
        # "House Committee on Education and the Workforce" →
        # "House Committee" that no NER could resolve.
        side = ctx.rng.choice(("leading", "trailing"))
        if side == "leading":
            kept = toks[1:]
        else:
            kept = toks[:-1]

        if len(kept) < 2:
            return None
        cand = " ".join(kept)
        if cand == surface:
            return None
        return cand
