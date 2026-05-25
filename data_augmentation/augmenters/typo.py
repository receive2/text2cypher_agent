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
    """
    One-character swap in a randomly-chosen alphabetic word.

    Preserves the first letter of the entity (and of each word) — most
    entity-recognition pipelines are anchored to the leading character,
    so a typo there is functionally a different entity rather than a
    typo.  The pipeline's ``_validate_edit`` enforces the same
    invariant, so a typo that touches the first character is rejected
    upstream anyway.
    """
    words = surface.split()
    if not words:
        return None
    # Pick word indices that contain ≥ 3 alphabetic chars so we have
    # room to swap two letters AFTER position 0.
    candidates: List[int] = [
        i for i, w in enumerate(words)
        if sum(c.isalpha() for c in w) >= 3
    ]
    if not candidates:
        return None
    wi = rng.choice(candidates)
    word = words[wi]

    # Pick two adjacent alphabetic positions to swap — but exclude
    # position 0 of the FIRST word of the surface (which is the
    # surface's first character).  For other words we still avoid
    # position 0 since it's the word-initial character.
    alpha_positions = [i for i, c in enumerate(word) if c.isalpha() and i > 0]
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


def _first_char_preserved(orig: str, cand: str) -> bool:
    """True iff orig[0] == cand[0] (case-insensitive).  Empty inputs fail."""
    if not orig or not cand:
        return False
    return orig[:1].lower() == cand[:1].lower()


class TypoAugmenter(Augmenter):
    name = "typo"

    def apply(self, surface: str, ctx: AugContext) -> Optional[str]:
        # Require ≥3 stripped chars so we can meaningfully alter a
        # non-first character.
        if not surface or len(surface.strip()) < 3:
            return None

        # nlpaug doesn't expose a "preserve first letter" knob, so retry
        # a handful of times and reject any candidate that mangles the
        # leading character.  The pipeline-side ``_validate_edit`` will
        # also reject these, so retries here just keep the typo strategy
        # from being wasted on the safety gate.
        for _ in range(4):
            cand = _nlpaug_typo(surface, ctx)
            if cand and _first_char_preserved(surface, cand):
                return cand

        # Fall back to the deterministic built-in (already first-char safe).
        return _builtin_typo(surface, ctx.rng)
