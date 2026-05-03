"""
data_augmentation.augmenters.typo
=================================
Real-world typing-noise simulation.

Uses ``nlpaug.augmenter.char`` (KeyboardAug + RandomCharAug) when the
package is available; falls back to a tiny built-in implementation if
nlpaug isn't installed (so the rest of the pipeline still works on a
slim env).

The injected noise is *small* by design — at most one or two char
changes per entity — because the goal is "user typed Balretta instead
of Barletta", not "user wrote a paragraph of gibberish".
"""

from __future__ import annotations

import string
from typing import List, Optional

from loguru import logger

from data_augmentation.augmenters.base import Augmenter, AugContext


# Lazy module-level state for nlpaug — built once.
_nlpaug_keyboard = None
_nlpaug_random = None
_nlpaug_attempted = False


def _ensure_nlpaug() -> None:
    global _nlpaug_keyboard, _nlpaug_random, _nlpaug_attempted
    if _nlpaug_attempted:
        return
    _nlpaug_attempted = True
    try:
        from nlpaug.augmenter.char import KeyboardAug, RandomCharAug

        # Conservative knobs: at most one word affected, at most one char
        # changed per word, no stop-words, preserve digits / punct.
        _nlpaug_keyboard = KeyboardAug(
            aug_char_min=1, aug_char_max=1,
            aug_word_min=1, aug_word_max=1,
            include_special_char=False,
            include_numeric=False,
            include_upper_case=False,
        )
        _nlpaug_random = RandomCharAug(
            action="swap",
            aug_char_min=1, aug_char_max=1,
            aug_word_min=1, aug_word_max=1,
            include_numeric=False,
            include_upper_case=False,
        )
        logger.debug("data_augmentation.typo: nlpaug initialised")
    except Exception as exc:  # noqa: BLE001
        logger.info(
            f"data_augmentation.typo: nlpaug unavailable ({exc}); "
            "falling back to built-in single-char swap."
        )


# ── Built-in fallback ───────────────────────────────────────────────────────

_ALPHA = string.ascii_letters


def _builtin_typo(surface: str, rng) -> Optional[str]:
    """One-character swap in a randomly-chosen alphabetic word."""
    words = surface.split()
    if not words:
        return None
    # Pick word indices that contain ≥ 2 alphabetic chars.
    candidates: List[int] = [
        i for i, w in enumerate(words)
        if sum(c.isalpha() for c in w) >= 2
    ]
    if not candidates:
        return None
    wi = rng.choice(candidates)
    word = words[wi]

    # Pick two adjacent alphabetic positions and swap them.
    alpha_positions = [i for i, c in enumerate(word) if c.isalpha()]
    # Need at least two consecutive-ish alphabetic chars.
    pairs = [
        (alpha_positions[i], alpha_positions[i + 1])
        for i in range(len(alpha_positions) - 1)
    ]
    if not pairs:
        return None
    a, b = rng.choice(pairs)
    chars = list(word)
    chars[a], chars[b] = chars[b], chars[a]
    new_word = "".join(chars)
    if new_word == word:
        return None
    words[wi] = new_word
    cand = " ".join(words)
    if cand == surface:
        return None
    return cand


# ── nlpaug-backed implementation ────────────────────────────────────────────

def _nlpaug_typo(surface: str, ctx: AugContext) -> Optional[str]:
    _ensure_nlpaug()
    if _nlpaug_keyboard is None and _nlpaug_random is None:
        return None

    # Pick keyboard or random-swap with equal probability — keyboard
    # mimics adjacent-key slips, random-swap mimics finger-order slips.
    aug = ctx.rng.choice([a for a in (_nlpaug_keyboard, _nlpaug_random) if a is not None])
    try:
        out = aug.augment(surface)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"data_augmentation.typo: nlpaug.augment failed: {exc}")
        return None

    # nlpaug returns either a string or a list of strings depending on version.
    if isinstance(out, list):
        if not out:
            return None
        cand = out[0]
    else:
        cand = out
    if not isinstance(cand, str):
        return None
    cand = cand.strip()
    if not cand or cand == surface:
        return None
    return cand


class TypoAugmenter(Augmenter):
    name = "typo"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        if not surface or len(surface.strip()) < 2:
            return None

        cand = _nlpaug_typo(surface, ctx)
        if cand:
            return cand
        return _builtin_typo(surface, ctx.rng)
