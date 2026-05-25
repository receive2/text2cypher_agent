"""
data_augmentation.pipeline
==========================
Top-level orchestrator: extract entities from a question, pick a
strategy per entity by weighted random choice, apply it, and assemble
the structured ``_aug_meta`` block.

Public API
----------
:func:`augment_nl` is the only entry point.  Dataset-specific scripts
call it once per row.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from data_augmentation.augmenters import STRATEGY_REGISTRY, AugContext
from data_augmentation.config import (
    DEFAULT_PROPORTIONS,
    MAX_EDITS_PER_ROW,
)
from data_augmentation.entity_extractor import EntitySpan, extract_entities
from data_augmentation.llm import LLMClient


# ──────────────────────────────────────────────────────────────────────────────
# Post-augmenter validation
# ──────────────────────────────────────────────────────────────────────────────
#
# Each strategy has its own contract about what a "safe" perturbation
# looks like.  These contracts exist because the gold Cypher is held
# constant: a perturbation that destroys NER's ability to recover the
# original entity literal makes the row unsolvable.
#
#   casing      : always safe (NER agents normalise case via toLower(...))
#   typo        : safe iff edit-distance(orig, new) ≤ 1 AND first char unchanged
#   partial     : safe iff orig has ≥ 3 tokens AND the LAST token of orig
#                 survives in new AND we did not strip a leading article
#                 ("the", "a", "an") that left a generic-looking remnant
#   synonym     : safe iff orig appears (case-insensitive) as substring of
#                 new — i.e. the strategy added scaffolding rather than
#                 *replacing* the entity.  This kills "Walt Disney
#                 Animation Studios" → "Disney animated" while keeping
#                 "Tom Hanks" → "the actor Tom Hanks".
#   paraphrase  : same substring-survives invariant as synonym.
#   abbrev      : has its own internal LLM-judge gate; trust the augmenter.

_ARTICLES = {"the", "a", "an"}

# Trailing tokens that are commonly "category" words rather than part of
# the canonical entity name — safe to drop as a trailing partial.
_TRAILING_FILLERS = {
    "series", "film", "films", "movie", "movies", "trilogy", "saga",
    "company", "corporation", "inc", "co", "ltd", "limited",
    "team", "fc", "club", "studios", "studio", "group", "press",
}


def _edit_distance_le1(a: str, b: str) -> bool:
    """True iff a and b differ by at most one single-character edit
    (insert, delete, or substitution).  Cheap; assumes short strings."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    # substitution
    if la == lb:
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs <= 1
    # insertion / deletion — make a the shorter one
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    # Walk and skip exactly once
    i = j = 0
    skipped = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            if skipped:
                return False
            skipped = True
            j += 1
    return True


def _validate_edit(
    strategy: str,
    orig:     str,
    new:      str,
) -> bool:
    """
    Reject post-hoc edits that violate per-strategy safety invariants.
    Returns True to keep, False to drop (pipeline then falls through to
    the next strategy in order).
    """
    if not new or new == orig:
        return False

    o_lc = orig.lower()
    n_lc = new.lower()

    if strategy == "casing":
        # Same characters modulo case → always safe.
        return o_lc == n_lc and orig != new

    if strategy == "typo":
        # ≤1 char edit AND first letter unchanged (preserves the most
        # distinctive char of most named entities).
        if not _edit_distance_le1(orig, new):
            return False
        if orig[:1].lower() != new[:1].lower():
            return False
        return True

    if strategy == "partial":
        o_toks = orig.split()
        n_toks = new.split()
        if len(o_toks) < 3:
            return False                               # don't truncate short names
        if len(n_toks) < 2:
            return False                               # need to keep some shape
        # Allowed shapes (matches the tightened augmenter that only drops
        # a SINGLE token from the leading or trailing edge):
        #   leading-drop:  new == orig[1:]
        #   trailing-drop: new == orig[:-1] AND orig[-1] is a known filler
        if n_toks == o_toks[1:]:
            return True
        if n_toks == o_toks[:-1] and o_toks[-1].lower() in _TRAILING_FILLERS:
            return True
        return False

    if strategy in ("synonym", "paraphrase"):
        # Substring-survives: the original entity literal (case-insensitive)
        # must still appear inside the new surface so NER can still pick
        # it up.  Kills replacement-style synonyms / runaway paraphrases.
        return o_lc in n_lc

    # abbrev / unknown strategies: trust the augmenter's own validation.
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Weighted strategy selection
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_proportions(props: Dict[str, float]) -> Dict[str, float]:
    """Drop unknown / non-positive entries, normalise to sum 1.0."""
    cleaned = {
        k: float(v) for k, v in props.items()
        if k in STRATEGY_REGISTRY and v > 0
    }
    total = sum(cleaned.values())
    if total <= 0:
        # Every strategy disabled — fall back to defaults so we don't
        # silently produce zero augmented rows.
        logger.warning(
            "data_augmentation.pipeline: all proportions <= 0; "
            "falling back to DEFAULT_PROPORTIONS."
        )
        cleaned = dict(DEFAULT_PROPORTIONS)
        total = sum(cleaned.values())
    return {k: v / total for k, v in cleaned.items()}


def _pick_strategy(
    rng: random.Random,
    weights: Dict[str, float],
) -> str:
    keys = list(weights.keys())
    w    = [weights[k] for k in keys]
    return rng.choices(keys, weights=w, k=1)[0]


def _strategy_order(
    rng: random.Random,
    weights: Dict[str, float],
) -> List[str]:
    """
    Sample strategies one-by-one without replacement, weighted at each
    step.  This eliminates the over-representation that a fixed-order
    fallback chain produces when the primary pick declines: every
    position's distribution stays close to the configured weights, so a
    universally-succeeding strategy (e.g. ``casing``) cannot dominate
    the augmented dataset.
    """
    order: List[str] = []
    remaining = dict(weights)
    while remaining:
        keys = list(remaining)
        w = [remaining[k] for k in keys]
        pick = rng.choices(keys, weights=w, k=1)[0]
        order.append(pick)
        del remaining[pick]
    return order


# ──────────────────────────────────────────────────────────────────────────────
# In-place span replacement
# ──────────────────────────────────────────────────────────────────────────────

def _apply_replacements(
    nl:           str,
    replacements: List[Tuple[EntitySpan, str]],
) -> Tuple[str, List[Tuple[int, int]]]:
    """
    Apply a list of (span, new_surface) replacements to *nl*, processed
    right-to-left so character offsets in earlier replacements stay
    valid.  Returns (new_nl, new_spans) where new_spans is a list of
    [start, end] in the OUTPUT string (matching ordering of input).
    """
    # Sort by start offset; we'll rewrite right-to-left.
    sorted_repls = sorted(replacements, key=lambda x: x[0].start)
    out = nl
    # Compute new spans by walking left-to-right and tracking offset drift.
    new_spans: List[Tuple[int, int]] = []
    drift = 0
    for span, new_surface in sorted_repls:
        new_start = span.start + drift
        new_end   = new_start + len(new_surface)
        drift += len(new_surface) - (span.end - span.start)
        new_spans.append((new_start, new_end))
    # Apply right-to-left to preserve original offsets in slicing.
    for span, new_surface in reversed(sorted_repls):
        out = out[:span.start] + new_surface + out[span.end:]
    return out, new_spans


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def augment_nl(
    nl:                str,
    gold_cypher:       Optional[str] = None,
    *,
    proportions:       Optional[Dict[str, float]] = None,
    llm_config:        Optional[Dict[str, Any]] = None,
    llm:               Optional[LLMClient] = None,
    use_llm_entity_fallback: bool = False,
    rng:               Optional[random.Random] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Augment one NL question.

    Parameters
    ----------
    nl
        The natural-language question.
    gold_cypher
        The reference Cypher; its string literals seed entity detection.
    proportions
        Strategy weights (will be normalised).  Falls back to
        :data:`DEFAULT_PROPORTIONS` when None.
    llm_config
        LLM config dict; mutually exclusive with *llm*.  Used to build
        an :class:`LLMClient` lazily.
    llm
        Pre-built :class:`LLMClient`.  Pass this when augmenting many
        rows in a row to avoid rebuilding the underlying chat model.
    use_llm_entity_fallback
        Forwarded to :func:`extract_entities`.
    rng
        Pipeline-wide :class:`random.Random` instance for reproducibility.
        Default: an unseeded fresh instance.

    Returns
    -------
    (new_nl, _aug_meta) or None
        ``None`` is returned when the pipeline could not augment the row
        (no entities detected, or every strategy declined for every
        entity).  The dataset script drops these.

        Otherwise, ``new_nl`` is the perturbed question and ``_aug_meta``
        is a dict of the form::

            {
              "augmented":   True,
              "original_nl": <original NL>,
              "edits": [
                  {"strategy": "...", "from": "...", "to": "...",
                   "src_span": [s, e], "dst_span": [s', e']},
                  ...
              ],
              "skipped": [
                  {"surface": "...", "tried": ["...", ...]},
                  ...
              ]
            }
    """
    if not nl or not isinstance(nl, str):
        return None

    rng = rng or random.Random()
    weights = _normalise_proportions(proportions or DEFAULT_PROPORTIONS)

    # Build / reuse LLM client.
    if llm is None:
        llm = LLMClient(llm_config) if llm_config else LLMClient(None)

    # 1. Extract entities.
    spans = extract_entities(
        nl,
        gold_cypher,
        use_llm_fallback=use_llm_entity_fallback,
        llm=llm,
    )
    if not spans:
        return None

    # 2. For each entity, try the picked strategy then fall through.
    ctx = AugContext(nl=nl, rng=rng, llm=llm)
    replacements: List[Tuple[EntitySpan, str]] = []
    edits_pending: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    # Cache strategy instances — they're stateless after construction.
    instances: Dict[str, Any] = {
        name: cls() for name, cls in STRATEGY_REGISTRY.items()
    }

    for span in spans:
        # Expose the current span's offsets to context-aware augmenters
        # (e.g. paraphrase) so they can inspect surrounding text.
        ctx.span_start = span.start
        ctx.span_end   = span.end
        order = _strategy_order(rng, weights)
        chosen_strategy: Optional[str] = None
        new_surface: Optional[str] = None
        tried: List[str] = []
        for strat_name in order:
            aug = instances.get(strat_name)
            if aug is None:
                continue
            tried.append(strat_name)
            try:
                cand = aug.apply(span.surface, ctx)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"data_augmentation.pipeline: strategy {strat_name!r} "
                    f"raised on {span.surface!r}: {exc}"
                )
                cand = None
            if not cand or cand == span.surface:
                continue
            # Post-augmenter safety gate (Fix B).
            if not _validate_edit(strat_name, span.surface, cand):
                logger.debug(
                    f"data_augmentation.pipeline: rejected {strat_name!r} "
                    f"edit {span.surface!r} → {cand!r} (failed safety invariant)"
                )
                continue
            chosen_strategy = strat_name
            new_surface = cand
            break

        if chosen_strategy is None or new_surface is None:
            skipped.append({"surface": span.surface, "tried": tried})
            continue

        replacements.append((span, new_surface))
        edits_pending.append({
            "strategy": chosen_strategy,
            "from":     span.surface,
            "to":       new_surface,
            "src_span": [span.start, span.end],
            "source":   span.source,
        })

    if not replacements:
        return None

    # ── Fix A: cap edits per row ───────────────────────────────────────────
    # The pipeline used to apply every successful edit, which produced
    # compositional artifacts ("the the X", "the movie the movie X")
    # when adjacent / overlapping spans both got rewritten.  Cap at
    # MAX_EDITS_PER_ROW (default 1) by sampling without replacement.
    if MAX_EDITS_PER_ROW is not None and len(replacements) > MAX_EDITS_PER_ROW:
        # Sample uniformly without replacement; keep both lists in lock-step.
        idxs = list(range(len(replacements)))
        keep_idxs = sorted(rng.sample(idxs, MAX_EDITS_PER_ROW))
        # Move the rest to `skipped`.
        for i in idxs:
            if i in keep_idxs:
                continue
            sp = replacements[i][0]
            skipped.append({
                "surface": sp.surface,
                "tried":   [edits_pending[i]["strategy"]],
                "reason":  "max_edits_per_row",
            })
        replacements   = [replacements[i]   for i in keep_idxs]
        edits_pending  = [edits_pending[i]  for i in keep_idxs]

    # 3. Apply replacements right-to-left and capture output spans.
    new_nl, new_spans = _apply_replacements(nl, replacements)
    for edit, dst_span in zip(edits_pending, new_spans):
        edit["dst_span"] = [dst_span[0], dst_span[1]]

    aug_meta: Dict[str, Any] = {
        "augmented":   True,
        "original_nl": nl,
        "edits":       edits_pending,
    }
    if skipped:
        aug_meta["skipped"] = skipped

    return new_nl, aug_meta
