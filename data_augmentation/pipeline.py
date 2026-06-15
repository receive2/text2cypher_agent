"""
data_augmentation.pipeline
==========================
Top-level orchestrator for the redesigned augmentation.

Per row: extract augmentable (name-type) entity spans seeded from the gold
Cypher; choose ONE (entity, strategy) edit via a **deficit-greedy quota
sampler** (the strategy furthest below its target share that can actually
produce a DB-valid edit on some entity in the row); replace ALL occurrences of
that entity consistently; record provenance + validity in ``_aug_meta``.  Rows
where no eligible strategy yields a valid edit are dropped, with the reason
recorded — never silently substituted with casing (the pre-redesign failure
that let casing+paraphrase dominate).

Validity (DB collision / uniqueness / margin) and splice grammar are enforced
via :mod:`data_augmentation.validity`.  There is no ``_validate_edit`` — its
one-size-fits-all invariants contradicted the strategies they gated.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from data_augmentation.augmenters import STRATEGY_REGISTRY, AugContext
from data_augmentation.config import (
    CAPPED_STRATEGIES, DEFAULT_PROPORTIONS, SYNTHETIC_GRAPHS,
)
from data_augmentation.entity_extractor import EntitySpan, extract_entities
from data_augmentation.kb_aliases import AliasProvider
from data_augmentation.llm import LLMClient
from data_augmentation import validity as V
from eval.difficulty import classify as _classify_difficulty


# ──────────────────────────────────────────────────────────────────────────────
# Per-row deterministic RNG
# ──────────────────────────────────────────────────────────────────────────────

def row_rng(seed: int, dataset: str, row_id: Any) -> random.Random:
    """Stable per-row RNG so adding/removing a source row doesn't reshuffle the
    perturbation of every other row."""
    blob = f"{seed}|{dataset}|{row_id}".encode("utf-8")
    h = int.from_bytes(hashlib.sha256(blob).digest()[:8], "big")
    return random.Random(h)


# ──────────────────────────────────────────────────────────────────────────────
# Proportions + quota sampler
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_proportions(props: Dict[str, float]) -> Dict[str, float]:
    cleaned = {k: float(v) for k, v in props.items()
               if k in STRATEGY_REGISTRY and v > 0}
    total = sum(cleaned.values())
    if total <= 0:
        cleaned = {k: float(v) for k, v in DEFAULT_PROPORTIONS.items()}
        total = sum(cleaned.values())
    return {k: v / total for k, v in cleaned.items()}


class QuotaSampler:
    """Deficit-greedy strategy chooser, stateful across a dataset run.

    For each row it offers strategies ordered by ``target_share − realized_share``
    (largest deficit first), with a stochastic tie-break; the pipeline commits
    the first that yields a DB-valid edit and calls :meth:`commit`."""

    def __init__(self, proportions: Dict[str, float]):
        self.weights = _normalise_proportions(proportions)
        self.counts: Counter = Counter()
        self.total = 0

    def order(self, eligible: List[str], rng: random.Random) -> List[str]:
        def deficit(s: str) -> float:
            target = self.weights.get(s, 0.0)
            realized = (self.counts[s] / self.total) if self.total else 0.0
            return target - realized
        # Drop capped strategies that have already met their target share, so
        # surplus from a supply-starved strategy can't inflate the control.
        pool = [s for s in eligible
                if not (s in CAPPED_STRATEGIES and self.total
                        and self.counts[s] / self.total >= self.weights.get(s, 0.0))]
        if not pool:                       # never deadlock a row
            pool = list(eligible)
        # stochastic tie-break: jitter within a small epsilon
        jitter = {s: rng.random() * 1e-6 for s in pool}
        return sorted(pool, key=lambda s: (deficit(s) + jitter[s]), reverse=True)

    def commit(self, strategy: str) -> None:
        self.counts[strategy] += 1
        self.total += 1


# ──────────────────────────────────────────────────────────────────────────────
# Cheap per-entity eligibility prechecks (do NOT call the LLM)
# ──────────────────────────────────────────────────────────────────────────────

def _eligible_strategies(surface: str, ctx: AugContext) -> List[str]:
    out: List[str] = []
    s = surface.strip()
    if any(c.isalpha() for c in s) and (s != s.lower() or s != s.upper()):
        out.append("casing")
    if len(s) >= 3 and any(c.isalpha() for c in s[1:]):
        out.append("typo")
    if len(s.split()) >= 2:
        out.append("partial")
    has_abbrev = ctx.aliases is not None and bool(ctx.aliases.abbrevs(surface))
    if has_abbrev or ctx.llm.enabled:
        out.append("abbrev")
    if not ctx.synthetic_domain:
        has_alias = ctx.aliases is not None and bool(ctx.aliases.aliases(surface))
        if has_alias or ctx.llm.enabled:
            out.append("alias")
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Consistent replace-all-occurrences with splice grammar guard
# ──────────────────────────────────────────────────────────────────────────────

def _occurrences(nl: str, surface: str) -> List[Tuple[int, int]]:
    spans, h, n, i = [], nl.lower(), surface.lower(), 0
    while True:
        j = h.find(n, i)
        if j < 0:
            break
        spans.append((j, j + len(surface)))
        i = j + len(surface)        # non-overlapping
    return spans


def _replace_all(nl: str, surface: str, new_surface: str) -> Optional[str]:
    """Replace every occurrence of *surface* with *new_surface*, right-to-left,
    each through the splice grammar guard.  Returns None if any seam can't be
    cleaned."""
    occ = _occurrences(nl, surface)
    if not occ:
        return None
    out = nl
    for (s, e) in reversed(occ):
        spliced = V.splice(out, s, e, new_surface)
        if spliced is None:
            return None
        out = spliced
    return out if out != nl else None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def augment_nl(
    nl: str,
    gold_cypher: Optional[str] = None,
    *,
    proportions: Optional[Dict[str, float]] = None,
    llm: Optional[LLMClient] = None,
    use_llm_entity_fallback: bool = False,
    rng: Optional[random.Random] = None,
    graph: Optional[str] = None,
    values: Optional[V.ValueProvider] = None,
    aliases: Optional[AliasProvider] = None,
    sampler: Optional[QuotaSampler] = None,
    stats: Optional[Counter] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Augment one question.  Returns ``(new_nl, aug_meta)`` or ``None`` (drop).

    ``stats`` (if given) accrues drop/commit reason counters, keyed
    ``"<strategy>:<reason>"`` and ``"drop:<reason>"`` — used by the runner's
    drop-rate report.
    """
    rng = rng or random.Random()
    sampler = sampler or QuotaSampler(proportions or DEFAULT_PROPORTIONS)

    def note(key: str) -> None:
        if stats is not None:
            stats[key] += 1

    spans = extract_entities(nl, gold_cypher,
                             use_llm_fallback=use_llm_entity_fallback, llm=llm)
    if not spans:
        note("drop:no_entity")
        return None

    syn = bool(graph and graph.lower() in SYNTHETIC_GRAPHS)
    ctx = AugContext(nl=nl, rng=rng, llm=llm or LLMClient(None),
                     graph=graph, synthetic_domain=syn,
                     values=values, aliases=aliases)
    instances = {name: cls() for name, cls in STRATEGY_REGISTRY.items()}

    # distinct surfaces (case-insensitive); pick spans grouped by surface
    by_surface: Dict[str, EntitySpan] = {}
    for sp in spans:
        by_surface.setdefault(sp.surface.lower(), sp)
    surfaces = list(by_surface.values())

    # union of eligible strategies across the row's entities
    elig_per: Dict[str, List[str]] = {}
    union: set = set()
    for sp in surfaces:
        c = AugContext(nl=nl, rng=rng, llm=ctx.llm, span_start=sp.start, span_end=sp.end,
                       label=sp.label, prop=sp.prop, entity_type=sp.entity_type,
                       graph=graph, synthetic_domain=syn, values=values, aliases=aliases)
        e = _eligible_strategies(sp.surface, c)
        elig_per[sp.surface.lower()] = e
        union |= set(e)

    if not union:
        note("drop:no_eligible_strategy")
        return None

    # deficit-greedy: try strategies in order; within a strategy, try eligible
    # entities (shuffled) until one yields a DB-valid, splice-clean edit.
    for strat in sampler.order(sorted(union), rng):
        cands = [sp for sp in surfaces if strat in elig_per[sp.surface.lower()]]
        rng.shuffle(cands)
        aug = instances[strat]
        for sp in cands:
            c = AugContext(nl=nl, rng=rng, llm=ctx.llm, span_start=sp.start, span_end=sp.end,
                           label=sp.label, prop=sp.prop, entity_type=sp.entity_type,
                           graph=graph, synthetic_domain=syn, values=values, aliases=aliases)
            proposal = aug.apply(sp.surface, c)
            if proposal is None or not proposal.surface or proposal.surface == sp.surface:
                continue
            ok, reason = V.check_validity(strat, proposal.surface, sp.surface,
                                          sp.label, sp.prop, values)
            if not ok:
                note(f"{strat}:{reason}")
                continue
            new_nl = _replace_all(nl, sp.surface, proposal.surface)
            if new_nl is None:
                note(f"{strat}:splice_failed")
                continue
            # commit
            sampler.commit(strat)
            note(f"{strat}:committed")
            aug_meta = {
                "augmented": True,
                "original_nl": nl,
                "graph": graph,
                # query_difficulty is the bucket from eval/difficulty.py
                # (easy/medium/hard) computed from gold_cypher.  None when
                # gold_cypher is absent (MTQ NL-only rows).
                "query_difficulty": _classify_difficulty(gold_cypher),
                "edits": [{
                    "strategy": strat,
                    "from": sp.surface,
                    "to": proposal.surface,
                    "source": proposal.source,
                    "needs_verification": proposal.needs_verification,
                    "label": sp.label,
                    "prop": sp.prop,
                    "occurrences": len(_occurrences(nl, sp.surface)),
                    "validity": reason,
                }],
            }
            return new_nl, aug_meta

    note("drop:all_candidates_failed")
    return None
