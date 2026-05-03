"""
data_augmentation.entity_extractor
==================================
Find entity spans in a natural-language question for downstream
augmentation.

Strategy
--------
1. **Cypher-literal extraction (primary):** parse single- and double-
   quoted string literals out of the gold Cypher.  Each literal that
   appears as a substring of the NL question (case-insensitive) is
   recorded as an entity span anchored to the NL.

2. **LLM fallback (optional):** when step 1 yields zero entities and
   ``use_llm_fallback`` is True, ask the LLM to enumerate the entities
   in the NL (proper nouns, named groups, places, organisations,
   people, etc.).  Only entities that map back to a substring of the NL
   are kept.

Each returned entity is a :class:`EntitySpan` with
``(start, end, surface, source)`` so the pipeline can replace the span
in-place without touching the rest of the sentence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from loguru import logger

from data_augmentation.config import MIN_ENTITY_LEN
from data_augmentation.llm import LLMClient


# ──────────────────────────────────────────────────────────────────────────────
# Data class
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EntitySpan:
    """One entity occurrence inside the NL question."""
    start:   int        # inclusive char offset in the original NL
    end:     int        # exclusive char offset in the original NL
    surface: str        # NL substring at [start:end] — preserves NL casing
    source:  str        # "cypher_literal" | "llm" — where it was found

    def __post_init__(self) -> None:  # pragma: no cover — invariants
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"invalid span: ({self.start}, {self.end})")


# ──────────────────────────────────────────────────────────────────────────────
# Cypher literal extraction
# ──────────────────────────────────────────────────────────────────────────────

# Match single- or double-quoted strings, allowing simple backslash escapes.
# Cypher also supports backtick-quoted *identifiers* but those are schema
# names (labels / property names), not entity values, so we skip them.
_CYPHER_LITERAL_RE = re.compile(
    r"""
    (?P<sq>'(?:\\.|[^'\\])*')     # 'single quoted'
    |
    (?P<dq>"(?:\\.|[^"\\])*")     # "double quoted"
    """,
    re.VERBOSE,
)


def _cypher_literals(cypher: str) -> List[str]:
    """Return the set of unique non-empty string literals inside *cypher*."""
    if not cypher:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for m in _CYPHER_LITERAL_RE.finditer(cypher):
        raw = m.group(0)
        # Strip the matching outer quotes.
        body = raw[1:-1]
        # Unescape the standard Cypher escapes we care about for matching.
        body = body.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
        body = body.strip()
        if len(body) < MIN_ENTITY_LEN:
            continue
        # Numeric-only literals (rare but possible) are not interesting
        # to the augmenter — they aren't named entities.
        if body.replace(".", "").replace("-", "").isdigit():
            continue
        if body in seen:
            continue
        seen.add(body)
        out.append(body)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# NL substring search
# ──────────────────────────────────────────────────────────────────────────────

def _find_all_ci(haystack: str, needle: str) -> List[Tuple[int, int]]:
    """Find all case-insensitive occurrences of *needle* in *haystack*."""
    if not needle:
        return []
    spans: List[Tuple[int, int]] = []
    h_lower = haystack.lower()
    n_lower = needle.lower()
    start = 0
    while True:
        i = h_lower.find(n_lower, start)
        if i < 0:
            break
        spans.append((i, i + len(needle)))
        start = i + 1   # allow overlapping matches; dedup happens later
    return spans


def _dedupe_spans(spans: Sequence[EntitySpan]) -> List[EntitySpan]:
    """
    Drop spans fully contained inside a longer span at the same offset
    family, then sort by start.  Keeps the longest match — e.g.
    'Sacramento Kings' wins over 'Kings' if both are detected.
    """
    sorted_spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    out: List[EntitySpan] = []
    for s in sorted_spans:
        contained = False
        for kept in out:
            # contained == kept fully covers s
            if kept.start <= s.start and kept.end >= s.end:
                contained = True
                break
            # overlap (partial) — drop the later, shorter one to avoid
            # double-rewriting the same characters
            if not (s.end <= kept.start or s.start >= kept.end):
                contained = True
                break
        if not contained:
            out.append(s)
    out.sort(key=lambda s: s.start)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# LLM fallback
# ──────────────────────────────────────────────────────────────────────────────

_LLM_FALLBACK_SYSTEM = (
    "You extract named entities from natural-language questions for a "
    "knowledge-graph QA system.  Entities are proper nouns / named groups: "
    "people, organisations, places, named events, named products, named "
    "concepts.  Common nouns ('movie', 'lake', 'company') and pronouns are "
    "NOT entities.  Output ONLY a JSON array of entity strings, copied "
    "verbatim from the question; no commentary.  If there are no entities, "
    "output []."
)

_LLM_FALLBACK_PROMPT_TMPL = (
    "Question: {nl}\n\nReturn a JSON array of the entity strings."
)


def _llm_extract(nl: str, llm: LLMClient) -> List[str]:
    if not llm.enabled:
        return []
    try:
        resp = llm.complete(
            _LLM_FALLBACK_PROMPT_TMPL.format(nl=nl),
            system=_LLM_FALLBACK_SYSTEM,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"data_augmentation.entity_extractor: LLM fallback failed: {exc}")
        return []
    if not resp:
        return []
    # Be lenient: extract the first JSON-array-looking substring.
    m = re.search(r"\[.*?\]", resp, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for x in arr:
        if isinstance(x, str) and len(x.strip()) >= MIN_ENTITY_LEN:
            out.append(x.strip())
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def extract_entities(
    nl:                str,
    gold_cypher:       Optional[str] = None,
    *,
    use_llm_fallback:  bool = True,
    llm:               Optional[LLMClient] = None,
) -> List[EntitySpan]:
    """
    Return entity spans inside *nl*.

    Parameters
    ----------
    nl
        The natural-language question.
    gold_cypher
        The reference Cypher whose string literals seed the primary
        entity list.  Pass ``None`` if unavailable.
    use_llm_fallback
        When True and the literal pass yields no entities, fall through
        to an LLM-based extractor.
    llm
        :class:`LLMClient` used when ``use_llm_fallback`` is True.
        Required only if the fallback is enabled.

    Returns
    -------
    list[EntitySpan]
        Possibly empty list, sorted by ``start`` offset, with overlaps
        resolved (longest match wins).
    """
    if not nl or not isinstance(nl, str):
        return []

    candidates: List[EntitySpan] = []

    # ── Primary: Cypher-literal cross-reference ────────────────────────────
    for lit in _cypher_literals(gold_cypher or ""):
        for (s, e) in _find_all_ci(nl, lit):
            surface = nl[s:e]
            if len(surface) >= MIN_ENTITY_LEN:
                candidates.append(EntitySpan(s, e, surface, "cypher_literal"))

    # ── Fallback: LLM extraction ───────────────────────────────────────────
    if not candidates and use_llm_fallback and llm is not None and llm.enabled:
        for ent in _llm_extract(nl, llm):
            for (s, e) in _find_all_ci(nl, ent):
                surface = nl[s:e]
                if len(surface) >= MIN_ENTITY_LEN:
                    candidates.append(EntitySpan(s, e, surface, "llm"))

    return _dedupe_spans(candidates)
