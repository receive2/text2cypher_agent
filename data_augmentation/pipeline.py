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
)
from data_augmentation.entity_extractor import EntitySpan, extract_entities
from data_augmentation.llm import LLMClient


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
        order = _strategy_order(rng, weights)
        chosen_strategy: Optional[str] = None
        new_surface: Optional[str] = None
        for strat_name in order:
            aug = instances.get(strat_name)
            if aug is None:
                continue
            try:
                cand = aug.apply(span.surface, ctx)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"data_augmentation.pipeline: strategy {strat_name!r} "
                    f"raised on {span.surface!r}: {exc}"
                )
                cand = None
            if cand and cand != span.surface:
                chosen_strategy = strat_name
                new_surface = cand
                break

        if chosen_strategy is None or new_surface is None:
            skipped.append({"surface": span.surface, "tried": order})
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
