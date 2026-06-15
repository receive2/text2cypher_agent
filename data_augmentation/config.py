"""
data_augmentation.config
========================
Single source of truth for the augmentation pipeline's knobs.

This file was rewritten for the augmentation redesign
(see ``docs/AUGMENTATION_REDESIGN.md``).  The runner
``run_data_augmentation.py`` imports ``PROPORTIONS`` from here so the
configured mixture, the report header, and the pipeline all agree — the
pre-redesign code had three mutually-inconsistent proportion tables.
"""

from __future__ import annotations

# ── Strategy proportions ─────────────────────────────────────────────────────
# Balanced design: the four *informative* grounding-challenge categories get an
# equal share (uniform per-category statistical power, and no thumb on the scale
# toward the category a grounding agent is best at), with ``casing`` held low as
# the difficulty floor / control condition.  Weights are normalised at runtime.
#
# ``paraphrase`` is intentionally absent — its scaffold-style output left the
# entity verbatim (no value-grounding challenge); its replacement-style output
# is now ``alias``.
PROPORTIONS: dict[str, float] = {
    "casing": 0.10,   # control / floor
    "typo":   0.225,
    "partial":0.225,
    "abbrev": 0.225,
    "alias":  0.225,
}

# Back-compat alias: some callers historically imported DEFAULT_PROPORTIONS.
DEFAULT_PROPORTIONS = PROPORTIONS

# Strategies that must never EXCEED their target share.  When a strategy is
# supply-starved on a domain (e.g. abbrev on fictional characters, which have
# no abbreviations), the deficit-greedy sampler would otherwise let the surplus
# inflate every other strategy — including the trivial control.  Capping
# ``casing`` pins it at its floor across domains, so the surplus flows only to
# the informative strategies (typo / partial / alias).
CAPPED_STRATEGIES: frozenset[str] = frozenset({"casing"})

# ── Entity extraction & typing ───────────────────────────────────────────────

# Minimum entity length (chars).
MIN_ENTITY_LEN: int = 2

# Only entities classified as ``name`` are augmented.  Dates, times, emails and
# structured identifiers / postcodes are excluded from the entity pool by
# design (DECIDED 2026-06-13): low grounding value (exact lookups, no
# world-knowledge alias) and collision-dense (the WN5→NW5 class of silent
# label corruption).  See ``entity_extractor.classify_entity``.
AUGMENTABLE_ENTITY_TYPES: frozenset[str] = frozenset({"name"})

# When the literal cross-reference yields zero entities, optionally fall back to
# an LLM span extractor.  The same type filter applies to its output.
DEFAULT_USE_LLM_ENTITY_FALLBACK: bool = True

# ── Alias closed-set guard ───────────────────────────────────────────────────
# A (label, property) with at most this many distinct DB values is a
# closed / categorical set (e.g. NBA divisions=6, conferences=2, positions~5).
# The ``alias`` LLM fallback DECLINES on these: forced to alias an enumerable
# category, the LLM swaps siblings or hallucinates ("Central Division" →
# "Midwest Division", "All-NBA Team" → "NBA All-Star Team").  Attested / curated
# aliases for such sets are still used (they run before the LLM fallback), so
# real slang like "shooting guard" → "two guard" comes from the curated table.
ALIAS_CLOSED_SET_MAX: int = 30

# ── Synthetic domains ────────────────────────────────────────────────────────
# Graphs whose entities are fabricated (no real-world referent).  The ``alias``
# strategy is INELIGIBLE here: an LLM asked for an alias of a synthetic surname
# hallucinates a real-world entity (the shipped "Wagner"→"the Wagner Group",
# "Hanson"→"the band Hanson" corruption).  Matched case-insensitively against
# the row's graph name / dataset.
SYNTHETIC_GRAPHS: frozenset[str] = frozenset({
    "pole",        # ZOGRASCOPE — fabricated policing data
    "bloom",       # Mind-the-Query — fabricated fraud graph
    "er",          # Mind-the-Query — fabricated entity-resolution graph
})

# ── LLM ──────────────────────────────────────────────────────────────────────
# Proposer model for abbrev/alias and the entity-extraction fallback.
# DECIDED 2026-06-13: gpt-4.1 (not mini, not open-weight).  Every LLM-proposed
# abbrev/alias form is flagged ``needs_verification`` and provenance-tagged in
# ``_aug_meta`` — the LLM only proposes, it never judges validity.
DEFAULT_LLM_CONFIG: dict = {
    "provider":    "openai",
    "model":       "gpt-4.1",
    "temperature": 0.4,
}

# ── Edit budget ──────────────────────────────────────────────────────────────
# Exactly one (entity, strategy) edit per augmented row.  Multi-edit rows
# compounded splice artifacts; the redesign keeps this at 1.
MAX_EDITS_PER_ROW: int = 1

# ── Misc ─────────────────────────────────────────────────────────────────────
# Base RNG seed.  The pipeline derives a per-row seed as
# ``(DEFAULT_SEED, dataset, row_id)`` so adding/removing a source row does not
# reshuffle every downstream row's perturbation.
DEFAULT_SEED: int = 42

# Drop rows where no entity could be detected / validly augmented, rather than
# emitting an unmodified copy.
DROP_NO_ENTITY_ROWS: bool = True
