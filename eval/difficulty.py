#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
difficulty.py
=============
Per-example query-difficulty bucketing for the text-to-Cypher evaluation
harness. **Graded rubric per docs/DIFFICULTY_REDESIGN.md.**

Public API
----------
    classify(gold_cypher) -> "easy" | "medium" | "hard" | None
    classify_explain(gold_cypher) -> (bucket, reason)
    aggregate_by_difficulty(records) -> dict   # used by metrics_*.evaluate_dataset

The classifier inspects the **gold** Cypher only — predictions can be
malformed and we want a stable bucket per example.  When ``gold_cypher``
is ``None`` or whitespace-only the bucket is ``None``.

**Three tiers, not four.**  text2cypher literature uses 2-3 tiers
(BIRD / DuSQL / SpCQL / Neo4j Text2Cypher); only Spider/CSpider use the
4-tier "extra" scheme, which doesn't fit curated graph-QA benchmarks
whose extra tail is naturally < 5%.  We keep Spider's *paradigm*
(static formula + global thresholds, graded accumulation) but use
**easy / medium / hard** like the rest of the text2cypher field.

Rubric (graded score — accumulation, not single-feature triggers)
-----------------------------------------------------------------
Three dimensions, each 0/1/2.  ``score = Reach + Operation + Filtering``
(0-6).  Bucket from the LOCKED global thresholds below.

**Reach** — max hops in any single comma-separated path across all
``MATCH`` / ``OPTIONAL MATCH`` clauses.

    0 :  ≤ 1 fixed hop
    1 :  2 or 3 fixed hops
    2 :  ≥ 4 fixed hops  OR  any variable-length pattern ``[*]`` / ``[r*..]``

**Operation** — MAX across detectors (do NOT sum within Operation).

    0 :  plain retrieval (no agg, no sort, no subquery, no special path)
    1 :  any single agg call (``count/sum/avg/min/max/collect``) /
         ``ORDER BY`` / ``LIMIT`` / ``SKIP`` (NOT the argmax pattern
         below) / ``OPTIONAL MATCH`` / ``UNWIND`` /
         ``shortestPath`` / ``allShortestPaths``
    2 :  grouping (agg + non-agg key in same RETURN/WITH projection) /
         argmax pattern (``ORDER BY <expr> [DESC] LIMIT 1``) /
         ``CASE WHEN`` / ``UNION`` / a flat subquery block
         (``CALL{}`` / ``EXISTS{}`` / ``COUNT{}`` / ``COLLECT{}``)

**Filtering** — predicates across all WHERE clauses + property-map filters in
MATCH patterns.  Per WHERE clause: ``preds_in_clause = 1 + #AND + #OR``;
sum across WHEREs; add the count of ``{k:v}`` property-map blocks in MATCH.

    0 :  0-1 predicates total
    1 :  exactly 2
    2 :  ≥ 3 total  OR  any single WHERE clause mixes AND and OR

**WITH dispatch** (the idiom fix — CypherBench has WITH/DISTINCT in 93% of
gold).  A ``WITH`` clause feeds Operation **iff its projection contains an
aggregation call** (then it is counted via the agg/group-by detectors);
otherwise the ``WITH`` itself is ignored.  ``DISTINCT`` is always ignored.

**Bucket thresholds (LOCKED globally — never re-tuned per dataset):**

    score 0      -> easy
    score 1-2    -> medium
    score >= 3   -> hard

**Hard-override** (-> hard regardless of score; reason carries the
``hard-override:`` prefix so callers can still filter for these):

    * a subquery block (CALL/EXISTS/COUNT/COLLECT ``{}``) contains
      *another* such block (depth >= 2);
    * ``UNION`` combined with a multi-hop path (Reach >= 1).

Single-level subqueries are Op=2 but do **not** trigger the override.

Pre-processing
--------------
Comments, string literals and backtick identifiers are stripped before
any keyword scan (line / block comments, single / double quoted strings,
backtick-quoted idents).  The stripping is applied once and all feature
checks run against the stripped text.  Keyword detection is case-insensitive.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from typing import Literal  # py3.8+
    Bucket = Literal["easy", "medium", "hard"]
except ImportError:  # pragma: no cover
    Bucket = str  # type: ignore[misc,assignment]

_BUCKETS: Tuple[str, ...] = ("easy", "medium", "hard")


# ──────────────────────────────────────────────────────────────────────────────
# 1. Pre-processing — strip comments, string literals, backtick identifiers
# ──────────────────────────────────────────────────────────────────────────────

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE  = re.compile(r"//[^\n]*")
# Strings: any backslash-escape sequence OR a non-quote / non-backslash char.
_SQ_STRING_RE = re.compile(r"'(?:\\.|[^'\\])*'", re.DOTALL)
_DQ_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"', re.DOTALL)
_BT_IDENT_RE  = re.compile(r"`(?:\\.|[^`\\])*`", re.DOTALL)


def _strip(cypher: str) -> str:
    """Remove comments, string literals and backtick identifiers."""
    s = _BLOCK_COMMENT_RE.sub(" ", cypher)
    s = _LINE_COMMENT_RE.sub(" ", s)
    s = _SQ_STRING_RE.sub("''", s)
    s = _DQ_STRING_RE.sub('""', s)
    s = _BT_IDENT_RE.sub("``", s)
    return s


# ──────────────────────────────────────────────────────────────────────────────
# 2. Clause segmentation — find clause headers anywhere in the query
# ──────────────────────────────────────────────────────────────────────────────

# Order matters within the alternation: longer/multi-word clauses must
# come before their shorter prefixes (OPTIONAL MATCH before MATCH,
# DETACH DELETE before DELETE, UNION ALL before UNION).
_CLAUSE_HEADER_RE = re.compile(
    r"\b("
    r"OPTIONAL\s+MATCH|MATCH|"
    r"DETACH\s+DELETE|DELETE|"
    r"ORDER\s+BY|"
    r"UNION\s+ALL|UNION|"
    r"WHERE|RETURN|WITH|CREATE|SET|MERGE|UNWIND|LIMIT|SKIP|FOREACH|CALL|"
    r"YIELD|REMOVE|USING"
    r")\b",
    re.IGNORECASE,
)


def _clause_headers(s: str) -> List[Tuple[int, int, str]]:
    """Return ``[(start, end, NORMALISED_KW), ...]`` for every clause header."""
    out: List[Tuple[int, int, str]] = []
    for m in _CLAUSE_HEADER_RE.finditer(s):
        kw = re.sub(r"\s+", " ", m.group(1).upper())
        out.append((m.start(), m.end(), kw))
    return out


def _clause_segments(s: str, target_kws: Tuple[str, ...]) -> List[str]:
    """
    Return the *content* (text between header end and the next header start)
    of every clause whose normalised keyword is in *target_kws*.
    """
    headers = _clause_headers(s)
    out: List[str] = []
    for i, (_, end, kw) in enumerate(headers):
        if kw in target_kws:
            next_start = headers[i + 1][0] if i + 1 < len(headers) else len(s)
            out.append(s[end:next_start])
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 3. Path / relationship-pattern feature detectors
# ──────────────────────────────────────────────────────────────────────────────

# Matches one Cypher relationship "edge" between two node patterns:
#   -[...]-, -[...]->, <-[...]-, <-[...]->, -->, <--, --
_REL_PATTERN_RE = re.compile(r"<?-(?:\[[^\]]*\])?-(?:>)?")

# Variable-length quantifier inside a relationship bracket: ``[*]``,
# ``[r*1..3]``, ``[:T*..5]``, etc.
_VAR_LEN_RE = re.compile(r"\[[^\]]*\*[^\]]*\]")


def _split_top_level_commas(s: str) -> List[str]:
    """Split *s* on commas that sit at depth 0 of ``()``, ``[]``, and ``{}``."""
    parts: List[str] = []
    cur: List[str] = []
    p = b = c = 0  # paren / bracket / brace depths
    for ch in s:
        if ch == "(":
            p += 1
        elif ch == ")":
            p -= 1
        elif ch == "[":
            b += 1
        elif ch == "]":
            b -= 1
        elif ch == "{":
            c += 1
        elif ch == "}":
            c -= 1
        if ch == "," and p == 0 and b == 0 and c == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _max_fixed_hops(s: str) -> int:
    """
    Maximum number of relationship patterns in any comma-separated path
    expression across all MATCH / OPTIONAL MATCH clauses.

    Counts variable-length patterns the same as fixed ones — but the
    Extra-tier "variable-length path" rule fires before this matters,
    so by the time Hard's "≥4 fixed hops" or Medium's "2 or 3 fixed
    hops" checks run, a query is guaranteed to have no variable-length
    rels.
    """
    max_h = 0
    for seg in _clause_segments(s, ("MATCH", "OPTIONAL MATCH")):
        for path in _split_top_level_commas(seg):
            n = len(_REL_PATTERN_RE.findall(path))
            if n > max_h:
                max_h = n
    return max_h


def _has_var_length_path(s: str) -> bool:
    """True if any relationship bracket contains ``*`` (var-length quantifier)."""
    return bool(_VAR_LEN_RE.search(s))


# ──────────────────────────────────────────────────────────────────────────────
# 4. Subquery / nesting detection
# ──────────────────────────────────────────────────────────────────────────────

_SUBQUERY_OPEN_RE = re.compile(
    r"\b(?:CALL|EXISTS|COUNT|COLLECT)\s*\{", re.IGNORECASE
)


def _has_nested_subquery(s: str) -> bool:
    """
    True iff at any point during a left-to-right brace walk the query has
    two simultaneously-open *subquery* braces — i.e. a CALL/EXISTS/COUNT/
    COLLECT block whose body contains another CALL/EXISTS/COUNT/COLLECT
    block.

    Property maps ``{name: 'foo'}`` are tracked as plain braces but do
    not count toward subquery-open depth.
    """
    sub_open_positions = {m.end() - 1 for m in _SUBQUERY_OPEN_RE.finditer(s)}
    stack: List[bool] = []  # True = subquery brace, False = plain map / projection
    sub_depth = 0
    for i, ch in enumerate(s):
        if ch == "{":
            is_sub = i in sub_open_positions
            stack.append(is_sub)
            if is_sub:
                sub_depth += 1
                if sub_depth >= 2:
                    return True
        elif ch == "}":
            if stack and stack.pop():
                sub_depth -= 1
    return False


# ──────────────────────────────────────────────────────────────────────────────
# 5. Boolean-operator counting in WHERE
# ──────────────────────────────────────────────────────────────────────────────

_AND_RE = re.compile(r"\bAND\b", re.IGNORECASE)
_OR_RE  = re.compile(r"\bOR\b",  re.IGNORECASE)
_NOT_RE = re.compile(r"\bNOT\b", re.IGNORECASE)


def _where_bool_summary(s: str) -> Tuple[int, int, int]:
    """
    Sum of (AND count, OR count, NOT count) across every WHERE clause in *s*.

    Boolean ops outside WHERE are intentionally ignored — the spec
    targets WHERE-clause complexity specifically.
    """
    total_and = total_or = total_not = 0
    for seg in _clause_segments(s, ("WHERE",)):
        total_and += len(_AND_RE.findall(seg))
        total_or  += len(_OR_RE.findall(seg))
        total_not += len(_NOT_RE.findall(seg))
    return total_and, total_or, total_not


# ──────────────────────────────────────────────────────────────────────────────
# 6. Other Hard / Medium feature regexes
# ──────────────────────────────────────────────────────────────────────────────

_AGG_FN_RE = re.compile(
    r"\b(?:COUNT|SUM|AVG|MIN|MAX|COLLECT)\s*\(", re.IGNORECASE
)
_SUBQUERY_OPEN_ANY_RE = re.compile(
    r"\b(?:CALL|EXISTS|COUNT|COLLECT)\s*\{", re.IGNORECASE
)
_SHORTEST_PATH_RE = re.compile(
    r"\b(?:shortestPath|allShortestPaths)\s*\(", re.IGNORECASE
)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_LIMIT_RE    = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_LIMIT_1_RE  = re.compile(r"\bLIMIT\s+1\b(?!\s*\d)", re.IGNORECASE)
_SKIP_RE     = re.compile(r"\bSKIP\b", re.IGNORECASE)
_OPT_MATCH_RE = re.compile(r"\bOPTIONAL\s+MATCH\b", re.IGNORECASE)
_UNWIND_RE   = re.compile(r"\bUNWIND\b", re.IGNORECASE)
_UNION_RE    = re.compile(r"\bUNION(?:\s+ALL)?\b", re.IGNORECASE)
_CASE_WHEN_RE = re.compile(r"\bCASE\s+WHEN\b", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
# 7. Dimension scorers — Reach / Operation / Filtering
# ──────────────────────────────────────────────────────────────────────────────

def _reach_score(s: str) -> int:
    """0:≤1 hop · 1:2–3 hops · 2:≥4 hops or variable-length."""
    if _has_var_length_path(s):
        return 2
    h = _max_fixed_hops(s)
    if h >= 4:
        return 2
    if h >= 2:
        return 1
    return 0


def _has_groupby(s: str) -> bool:
    """True if any RETURN or WITH projection has BOTH an aggregation call AND
    a non-aggregation key (= group-by)."""
    for seg in _clause_segments(s, ("RETURN", "WITH")):
        parts = _split_top_level_commas(seg)
        if len(parts) < 2:
            continue
        has_agg = any(_AGG_FN_RE.search(p) for p in parts)
        has_non_agg = any(not _AGG_FN_RE.search(p) for p in parts)
        if has_agg and has_non_agg:
            return True
    return False


def _has_argmax_pattern(s: str) -> bool:
    """``ORDER BY <expr> [DESC] LIMIT 1`` — argmax / argmin / time-sensitive."""
    return bool(_ORDER_BY_RE.search(s) and _LIMIT_1_RE.search(s))


def _operation_score(s: str) -> int:
    """MAX across Operation detectors (do NOT sum within Operation)."""
    # Op = 2 detectors
    if (_has_groupby(s)
            or _has_argmax_pattern(s)
            or _CASE_WHEN_RE.search(s)
            or _UNION_RE.search(s)
            or _SUBQUERY_OPEN_ANY_RE.search(s)):
        return 2
    # Op = 1 detectors
    if (_AGG_FN_RE.search(s)
            or _ORDER_BY_RE.search(s)
            or _LIMIT_RE.search(s)
            or _SKIP_RE.search(s)
            or _OPT_MATCH_RE.search(s)
            or _UNWIND_RE.search(s)
            or _SHORTEST_PATH_RE.search(s)):
        return 1
    return 0


# Property-map opener inside a MATCH pattern: ``Label {``, ``rel {``, or
# ``)`` immediately followed by ``{`` (the closing-paren-then-map case is
# rare; the common forms are ``Label {`` and ``var:Label {``).
_PROPMAP_OPEN_RE = re.compile(r"[A-Za-z0-9_)\]]\s*\{")


def _count_propmap_filters(s: str) -> int:
    """Count of ``{k:v}`` property-map blocks inside MATCH / OPTIONAL MATCH
    patterns.  Each block = ≥ 1 filter; we count blocks, not keys."""
    n = 0
    for seg in _clause_segments(s, ("MATCH", "OPTIONAL MATCH")):
        n += len(_PROPMAP_OPEN_RE.findall(seg))
    return n


def _filtering_score(s: str) -> int:
    """0: 0–1 preds · 1: 2 preds · 2: ≥3 preds OR mixed AND+OR in any WHERE."""
    preds = 0
    any_mixed = False
    for seg in _clause_segments(s, ("WHERE",)):
        n_and = len(_AND_RE.findall(seg))
        n_or  = len(_OR_RE.findall(seg))
        preds += 1 + n_and + n_or
        if n_and > 0 and n_or > 0:
            any_mixed = True
    preds += _count_propmap_filters(s)
    if any_mixed:
        return 2
    if preds >= 3:
        return 2
    if preds == 2:
        return 1
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# 8. Public classifier — graded score + extra-override
# ──────────────────────────────────────────────────────────────────────────────

def _hard_override(s: str) -> Optional[str]:
    """Return an override reason if the query is unconditionally hard."""
    if _has_nested_subquery(s):
        return "hard-override: nested subquery (depth ≥ 2)"
    if _UNION_RE.search(s) and _max_fixed_hops(s) >= 2:
        return "hard-override: UNION + multi-hop"
    return None


def classify_explain(gold_cypher: Optional[str]) -> Tuple[Optional[str], str]:
    """
    Return ``(bucket, reason)`` where *bucket* is one of
    ``"easy" | "medium" | "hard" | None`` and *reason* describes the score
    breakdown.  Returns ``(None, "no gold cypher")`` when *gold_cypher*
    is ``None`` or whitespace-only.
    """
    if gold_cypher is None or not gold_cypher.strip():
        return None, "no gold cypher"

    s = _strip(gold_cypher)

    override = _hard_override(s)
    if override is not None:
        return "hard", override

    reach = _reach_score(s)
    op    = _operation_score(s)
    filt  = _filtering_score(s)
    score = reach + op + filt

    if score >= 3:
        bucket = "hard"
    elif score >= 1:
        bucket = "medium"
    else:
        bucket = "easy"
    return bucket, f"{bucket}: reach={reach} op={op} filter={filt} score={score}"


def classify(gold_cypher: Optional[str]) -> Optional[str]:
    """
    Classify a gold Cypher query into one of
    ``"easy" | "medium" | "hard"`` or ``None`` (when no gold Cypher is
    available — e.g. Mind-the-Query NL-only examples).

    See :func:`classify_explain` for the rule definitions and a
    machine-readable reason string.

    The classifier inspects the **gold** Cypher only — predictions can
    be malformed and we want a stable bucket per example.
    """
    bucket, _ = classify_explain(gold_cypher)
    return bucket


# ──────────────────────────────────────────────────────────────────────────────
# 8. Aggregation helper used by metrics_*.evaluate_dataset
# ──────────────────────────────────────────────────────────────────────────────

def aggregate_by_difficulty(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate per-example evaluation records into the unified
    ``by_difficulty`` summary shape consumed by ``eval_run.py``.

    Parameters
    ----------
    records
        List of ``evaluate_one`` records.  Each record must have:
        ``"difficulty"`` (str | None), ``"ea"`` / ``"em"`` / ``"psjs"``
        (each bool/float/None) and an ``"error"`` field.

    Returns
    -------
    dict
        ``{
            "all":    {ea, em, psjs, n, n_scored, n_errors},
            "easy":   {...},
            "medium": {...},
            "hard":   {...},
        }``

        Per-bucket cell layout::

            {
              "ea":    float | None,
              "em":    float | None,
              "psjs":  float | None,
              "n":     int,
              "n_scored": {"ea": int, "em": int, "psjs": int},
              "n_errors": int,
            }

    Aggregation rule
    ----------------
    ``ea`` / ``em`` / ``psjs`` are the **mean** of the metric over
    examples where (a) the example falls in that bucket (``"all"``
    counts everything) and (b) the metric value is not ``None``.
    A bucket cell's metric is ``None`` when no examples scored it
    (n_scored[metric] == 0).

    Errored examples count toward ``n`` but contribute to no metric
    mean.  Examples whose ``difficulty`` is ``None`` (no gold Cypher)
    contribute to ``"all"`` but to no individual bucket.
    """
    cells = {
        name: {
            "ea": None, "em": None, "psjs": None,
            "n": 0,
            "n_scored": {"ea": 0, "em": 0, "psjs": 0},
            "n_errors": 0,
        }
        for name in ("all",) + _BUCKETS
    }
    sums = {name: {"ea": 0.0, "em": 0.0, "psjs": 0.0}
            for name in ("all",) + _BUCKETS}

    for rec in records:
        diff = rec.get("difficulty")
        targets = ["all"]
        if diff in _BUCKETS:
            targets.append(diff)

        for name in targets:
            cell = cells[name]
            cell["n"] += 1
            if rec.get("error"):
                cell["n_errors"] += 1
            for k in ("ea", "em", "psjs"):
                v = rec.get(k)
                if v is None:
                    continue
                cell["n_scored"][k] += 1
                sums[name][k] += float(v)

    for name in ("all",) + _BUCKETS:
        for k in ("ea", "em", "psjs"):
            ns = cells[name]["n_scored"][k]
            cells[name][k] = (sums[name][k] / ns) if ns > 0 else None

    return cells
