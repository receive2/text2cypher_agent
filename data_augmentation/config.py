"""
data_augmentation.config
========================
Default knobs for the augmentation pipeline.  The repo-root
``run_data_augmentation.py`` is the canonical place for users to edit
proportions / LLM choice; values here are fall-back defaults consumed by
the pipeline when the runner doesn't pass an override.
"""

from __future__ import annotations

# ── Strategy proportions ─────────────────────────────────────────────────────
# Six strategies; weights are normalised at runtime so users can put in
# arbitrary positive numbers and trust the pipeline to do the math.
DEFAULT_PROPORTIONS: dict[str, float] = {
    "casing":     0.18,
    "partial":    0.18,
    "abbrev":     0.18,
    "synonym":    0.18,
    "paraphrase": 0.18,
    "typo":       0.10,
}

# ── Entity extraction ────────────────────────────────────────────────────────

# When the literal-cross-reference yields zero entities, optionally fall
# back to an LLM-based span extractor.  Disabled by default so cost-
# conscious smoke runs don't surprise the user with bills.
DEFAULT_USE_LLM_ENTITY_FALLBACK: bool = True

# Minimum entity length (chars) — anything shorter is treated as too
# noisy to be a real entity (e.g. a stray "of" / "in" in a gold filter).
MIN_ENTITY_LEN: int = 2

# ── LLM ──────────────────────────────────────────────────────────────────────

# Mirrors the shape of NER_LLM_CONFIG / CYPHER_LLM_CONFIG in config.py.
# The runner passes whatever the user set; this is the absolute fallback
# if neither runner nor caller specifies one.
DEFAULT_LLM_CONFIG: dict = {
    "provider":    "openai",
    "model":       "gpt-4.1-mini",
    "temperature": 0.4,
}

# ── Misc ─────────────────────────────────────────────────────────────────────

# Default RNG seed (overridden by the runner for reproducibility).
DEFAULT_SEED: int = 42

# When the augmenter pipeline finds zero entities in a row, drop it from
# the augmented dataset rather than emit an unmodified copy.
DROP_NO_ENTITY_ROWS: bool = True
