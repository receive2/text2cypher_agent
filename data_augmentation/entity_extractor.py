"""
data_augmentation.entity_extractor
==================================
Find augmentable entity spans in a question.

1. **Cypher-literal extraction (primary):** parse quoted string literals out
   of the gold Cypher; each literal that appears in the NL is an entity span,
   tagged with the ``(label, property)`` it was compared against so validity
   checks can be scoped (e.g. ``x2.surname = "Hanson"`` → ``(Person, surname)``).

2. **LLM fallback (optional):** when step 1 finds nothing, ask the LLM for
   entity strings; same type filter applies.

**Type filter (DECIDED 2026-06-13):** only ``name``-type spans are augmentable.
Dates, times, emails and structured identifiers / postcodes are excluded — low
grounding value and collision-dense.  The numeric/date filter applies to BOTH
the literal and LLM paths (the pre-redesign LLM path had no filter, which is
how ``'1868'`` got perturbed).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from loguru import logger

from data_augmentation.config import AUGMENTABLE_ENTITY_TYPES, MIN_ENTITY_LEN
from data_augmentation.llm import LLMClient


@dataclass(frozen=True)
class EntitySpan:
    start:   int
    end:     int
    surface: str
    source:  str               # "cypher_literal" | "llm"
    label:   Optional[str] = None
    prop:    Optional[str] = None
    entity_type: str = "name"

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"invalid span: ({self.start}, {self.end})")


# ── Entity typing ─────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TIME_RE  = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_SSN_RE   = re.compile(r"^\d{3}-\d{2}-\d{4}$")        # SSN / structured id, not a date
_DATE_RE  = re.compile(r"^\d{1,4}[-/]\d{1,2}([-/]\d{1,4})?$")
_UK_POSTCODE_RE = re.compile(r"^[A-Za-z]{1,2}\d{1,2}[A-Za-z]?\s*\d?[A-Za-z]{0,2}$")


def classify_entity(s: str) -> str:
    """Return one of: ``name`` | ``date`` | ``time`` | ``email`` | ``id``."""
    t = s.strip()
    if not t:
        return "id"
    if _EMAIL_RE.match(t):
        return "email"
    if _TIME_RE.match(t):
        return "time"
    if _SSN_RE.match(t):
        return "id"
    if _DATE_RE.match(t):
        return "date"
    # all digits once separators are stripped → SSN / phone / numeric id
    if re.sub(r"[\s.\-/:]", "", t).isdigit():
        return "id"
    # short alnum codes / postcodes (e.g. WN5, BL5 2RN, M40 8DZ, SK4 2QB)
    if _UK_POSTCODE_RE.match(t) and any(c.isdigit() for c in t) and len(t) <= 8:
        return "id"
    return "name"


def is_augmentable(s: str) -> bool:
    return classify_entity(s) in AUGMENTABLE_ENTITY_TYPES


# ── Cypher literal extraction ──────────────────────────────────────────────────

_CYPHER_LITERAL_RE = re.compile(
    r"""(?P<sq>'(?:\\.|[^'\\])*')|(?P<dq>"(?:\\.|[^"\\])*")""", re.VERBOSE
)


def _cypher_literals(cypher: str) -> List[str]:
    if not cypher:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for m in _CYPHER_LITERAL_RE.finditer(cypher):
        body = m.group(0)[1:-1]
        body = body.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\").strip()
        if len(body) < MIN_ENTITY_LEN or body in seen:
            continue
        seen.add(body)
        out.append(body)
    return out


def _resolve_label_prop(cypher: str, literal: str) -> Tuple[Optional[str], Optional[str]]:
    """Best-effort: find the (label, property) a literal is compared against."""
    if not cypher:
        return None, None
    lit_re = re.escape(literal)
    # var.prop = 'lit'  |  var.prop = "lit"
    m = re.search(rf"(\w+)\s*\.\s*(\w+)\s*=\s*['\"]{lit_re}['\"]", cypher)
    if m:
        var, prop = m.group(1), m.group(2)
        lm = re.search(rf"\(\s*{re.escape(var)}\s*:\s*`?(\w+)`?", cypher)
        return (lm.group(1) if lm else None), prop
    # {prop: 'lit'} inside a node pattern — grab prop and the nearest preceding label
    m = re.search(rf"\{{[^{{}}]*?(\w+)\s*:\s*['\"]{lit_re}['\"]", cypher)
    if m:
        prop = m.group(1)
        pre = cypher[:m.start()]
        lm = re.findall(r":\s*`?(\w+)`?", pre)
        return (lm[-1] if lm else None), prop
    return None, None


# ── NL search ──────────────────────────────────────────────────────────────────

def _find_all_ci(haystack: str, needle: str) -> List[Tuple[int, int]]:
    if not needle:
        return []
    spans: List[Tuple[int, int]] = []
    h, n = haystack.lower(), needle.lower()
    start = 0
    while True:
        i = h.find(n, start)
        if i < 0:
            break
        spans.append((i, i + len(needle)))
        start = i + 1
    return spans


def _dedupe_spans(spans: Sequence[EntitySpan]) -> List[EntitySpan]:
    sorted_spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    out: List[EntitySpan] = []
    for s in sorted_spans:
        contained = False
        for kept in out:
            if kept.start <= s.start and kept.end >= s.end:
                contained = True
                break
            if not (s.end <= kept.start or s.start >= kept.end):
                contained = True
                break
        if not contained:
            out.append(s)
    out.sort(key=lambda s: s.start)
    return out


# ── LLM fallback ───────────────────────────────────────────────────────────────

_LLM_FALLBACK_SYSTEM = (
    "You extract named entities from natural-language questions for a "
    "knowledge-graph QA system. Entities are proper nouns / named groups. "
    "Common nouns and pronouns are NOT entities. Output ONLY a JSON array of "
    "entity strings copied verbatim from the question; if none, output []."
)
_LLM_FALLBACK_PROMPT_TMPL = "Question: {nl}\n\nReturn a JSON array of the entity strings."


def _llm_extract(nl: str, llm: LLMClient) -> List[str]:
    if not llm.enabled:
        return []
    resp = llm.complete(_LLM_FALLBACK_PROMPT_TMPL.format(nl=nl), system=_LLM_FALLBACK_SYSTEM)
    if not resp:
        return []
    m = re.search(r"\[.*?\]", resp, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list):
        return []
    return [x.strip() for x in arr if isinstance(x, str) and len(x.strip()) >= MIN_ENTITY_LEN]


# ── Public API ──────────────────────────────────────────────────────────────────

def extract_entities(
    nl: str,
    gold_cypher: Optional[str] = None,
    *,
    use_llm_fallback: bool = True,
    llm: Optional[LLMClient] = None,
) -> List[EntitySpan]:
    """Return augmentable (name-type) entity spans, sorted, overlaps resolved."""
    if not nl or not isinstance(nl, str):
        return []

    candidates: List[EntitySpan] = []

    for lit in _cypher_literals(gold_cypher or ""):
        etype = classify_entity(lit)
        if etype not in AUGMENTABLE_ENTITY_TYPES:
            logger.debug(f"entity_extractor: skip non-name literal {lit!r} (type={etype})")
            continue
        label, prop = _resolve_label_prop(gold_cypher or "", lit)
        for (s, e) in _find_all_ci(nl, lit):
            surf = nl[s:e]
            if len(surf) >= MIN_ENTITY_LEN:
                candidates.append(EntitySpan(s, e, surf, "cypher_literal", label, prop, etype))

    if not candidates and use_llm_fallback and llm is not None and llm.enabled:
        for ent in _llm_extract(nl, llm):
            etype = classify_entity(ent)
            if etype not in AUGMENTABLE_ENTITY_TYPES:
                continue
            for (s, e) in _find_all_ci(nl, ent):
                surf = nl[s:e]
                if len(surf) >= MIN_ENTITY_LEN:
                    candidates.append(EntitySpan(s, e, surf, "llm", None, None, etype))

    return _dedupe_spans(candidates)
