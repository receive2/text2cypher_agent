#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
difficulty.py
=============
Per-example difficulty bucketing for the text-to-Cypher evaluation harness.

Public API
----------
    classify(gold_cypher) -> "easy" | "medium" | "hard" | "extra" | None
    classify_explain(gold_cypher) -> (bucket, reason)
    aggregate_by_difficulty(records) -> dict   # used by metrics_*.evaluate_dataset

The classifier inspects the **gold** Cypher only — predictions can be
malformed and we want a stable bucket per example.  When ``gold_cypher``
is ``None`` or whitespace-only the bucket is ``None``; such examples
contribute to the ``"all"`` aggregate but to no individual bucket.

Bucketing rule (verbatim from the harness spec)
-----------------------------------------------
The bucket is the highest tier whose conditions match.  Check
**Extra → Hard → Medium → Easy** in order; the first tier whose
conditions are met wins.

Extra — any of:
    * Complex boolean filtering in WHERE: ≥2 boolean operators among
      AND / OR / NOT, or any mix of AND with OR regardless of count.
    * Nested subqueries: a ``CALL { ... }`` block whose body contains
      another ``CALL { ... }``, or any subquery expression
      (``EXISTS { ... }`` / ``COUNT { ... }`` / ``COLLECT { ... }``)
      nested inside another subquery clause or expression.
    * Variable-length paths: relationship patterns containing ``*``
      (e.g. ``[r*1..3]``, ``[*..5]``, ``[*]``).

Hard — any of (and not Extra):
    * Aggregation function calls: ``COUNT(...)``, ``SUM(...)``,
      ``AVG(...)``, ``MIN(...)``, ``MAX(...)``, ``COLLECT(...)``.
      Includes ``count(*)``.
    * Subquery / chaining clauses: ``CALL { ... }``, or any ``WITH``
      (including bare projection / rename — by design).
    * Top-level subquery expressions: ``EXISTS { ... }``,
      ``COUNT { ... }``, ``COLLECT { ... }``.
    * List ops: ``UNWIND``.
    * Path-pattern functions: ``shortestPath``, ``allShortestPaths``.
    * 4 or more fixed hops in the longest path (variable-length hops
      do NOT count here — they route to Extra).

Medium — any of (and not Hard/Extra):
    * ``ORDER BY``, ``LIMIT``, ``SKIP``, ``DISTINCT``.
    * Multi-hop fixed paths: 2 or 3 relationship patterns in the
      longest path.
    * ``OPTIONAL MATCH``.
    * Exactly one boolean operator in WHERE (one AND, OR, or NOT).

Easy — default when no higher tier matches AND the query satisfies all of:
    * Uses only the clauses ``MATCH`` / ``WHERE`` / ``RETURN`` (any of
      these may be absent — e.g. a bare ``MATCH (n:Person) RETURN n``
      with no WHERE qualifies).
    * Longest path is ≤1 relationship pattern.
    * WHERE, if present, contains no boolean operators.

Safety net
    If a query falls through all four checks (no higher tier matched,
    but the query also uses a clause not in Easy's whitelist), classify
    it as **Hard**.  This shouldn't happen on well-formed gold queries;
    when it does, ``classify_explain`` records the reason as
    ``"hard: safety-net (...)"`` so the case is visible in logs.

Hop counting
------------
"Longest path" is the maximum number of relationship patterns appearing
in any single comma-separated path expression across all
``MATCH`` / ``OPTIONAL MATCH`` clauses.  Paths in different MATCH
clauses or different comma-separated elements within one MATCH are
counted independently; we take the max.

    MATCH (a)-[:R]->(b)                                → 1
    MATCH (a)-[:R]->(b)-[:S]->(c)                      → 2
    MATCH (a)-[:R]->(b), (c)-[:S]->(d)                 → 1 (max(1, 1))
    MATCH (a)-[:R]->(b) MATCH (b)-[:S]->(c)            → 1 (max(1, 1))
    MATCH (a)-[r*1..3]->(b)                            → variable-length → Extra

Bare relationship patterns (``--``, ``-->``, ``<--``) count the same as
``-[...]->``.

Pre-processing
--------------
Before scanning for keywords, we strip the gold Cypher of:

    * Line comments: ``// ... <newline>``.
    * Block comments: ``/* ... */``.
    * Single-quoted strings (with backslash-escape handling).
    * Double-quoted strings (with backslash-escape handling).
    * Backtick-quoted identifiers.

A small regex-based stripper handles this — we deliberately avoid
pulling in a full Cypher parser.  Keyword detection is case-insensitive.
The stripping is applied once and all feature checks run against the
stripped text.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from typing import Literal  # py3.8+
    Bucket = Literal["easy", "medium", "hard", "extra"]
except ImportError:  # pragma: no cover
    Bucket = str  # type: ignore[misc,assignment]

_BUCKETS: Tuple[str, ...] = ("easy", "medium", "hard", "extra")


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
_SUBQUERY_EXPR_RE = re.compile(
    r"\b(?:EXISTS|COUNT|COLLECT)\s*\{", re.IGNORECASE
)
_CALL_BLOCK_RE = re.compile(r"\bCALL\s*\{", re.IGNORECASE)
_WITH_RE       = re.compile(r"\bWITH\b", re.IGNORECASE)
_UNWIND_RE     = re.compile(r"\bUNWIND\b", re.IGNORECASE)
_SHORTEST_PATH_RE = re.compile(
    r"\b(?:shortestPath|allShortestPaths)\s*\(", re.IGNORECASE
)
_ORDER_BY_RE = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
_LIMIT_RE    = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_SKIP_RE     = re.compile(r"\bSKIP\b", re.IGNORECASE)
_DISTINCT_RE = re.compile(r"\bDISTINCT\b", re.IGNORECASE)
_OPT_MATCH_RE = re.compile(r"\bOPTIONAL\s+MATCH\b", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
# 7. Public classifier
# ──────────────────────────────────────────────────────────────────────────────

def classify_explain(gold_cypher: Optional[str]) -> Tuple[Optional[str], str]:
    """
    Return ``(bucket, reason)`` where *bucket* is one of
    ``"easy" | "medium" | "hard" | "extra" | None`` and *reason* names
    the rule that fired (e.g. ``"extra: variable-length path"``,
    ``"medium: ORDER BY"``).

    Returns ``(None, "no gold cypher")`` when *gold_cypher* is ``None``
    or whitespace-only.
    """
    if gold_cypher is None or not gold_cypher.strip():
        return None, "no gold cypher"

    s = _strip(gold_cypher)

    # ── Extra ────────────────────────────────────────────────────────────────
    n_and, n_or, n_not = _where_bool_summary(s)
    total_bool = n_and + n_or + n_not
    if total_bool >= 2 or (n_and > 0 and n_or > 0):
        return "extra", (
            f"extra: complex boolean filtering in WHERE "
            f"(and={n_and} or={n_or} not={n_not})"
        )
    if _has_var_length_path(s):
        return "extra", "extra: variable-length path"
    if _has_nested_subquery(s):
        return "extra", "extra: nested subquery"

    # ── Hard ─────────────────────────────────────────────────────────────────
    if _AGG_FN_RE.search(s):
        return "hard", "hard: aggregation function"
    if _CALL_BLOCK_RE.search(s):
        return "hard", "hard: CALL { ... } subquery"
    if _WITH_RE.search(s):
        return "hard", "hard: WITH"
    if _SUBQUERY_EXPR_RE.search(s):
        return "hard", "hard: subquery expression (EXISTS/COUNT/COLLECT { })"
    if _UNWIND_RE.search(s):
        return "hard", "hard: UNWIND"
    if _SHORTEST_PATH_RE.search(s):
        return "hard", "hard: shortestPath / allShortestPaths"
    max_hops = _max_fixed_hops(s)
    if max_hops >= 4:
        return "hard", f"hard: {max_hops} fixed hops"

    # ── Medium ───────────────────────────────────────────────────────────────
    if _ORDER_BY_RE.search(s):
        return "medium", "medium: ORDER BY"
    if _LIMIT_RE.search(s):
        return "medium", "medium: LIMIT"
    if _SKIP_RE.search(s):
        return "medium", "medium: SKIP"
    if _DISTINCT_RE.search(s):
        return "medium", "medium: DISTINCT"
    if _OPT_MATCH_RE.search(s):
        return "medium", "medium: OPTIONAL MATCH"
    if 2 <= max_hops <= 3:
        return "medium", f"medium: {max_hops} fixed hops"
    if total_bool == 1:
        return "medium", "medium: single boolean operator in WHERE"

    # ── Easy (whitelist + path + boolean) ────────────────────────────────────
    seen = {kw for _, _, kw in _clause_headers(s)}
    allowed = {"MATCH", "WHERE", "RETURN"}
    if seen <= allowed and max_hops <= 1 and total_bool == 0:
        return "easy", "easy: simple MATCH/WHERE/RETURN"

    # ── Safety net — clauses outside Easy's whitelist that none of the
    #    higher tiers caught (rare on well-formed gold queries).
    extras = sorted(seen - allowed) if seen else []
    return "hard", f"hard: safety-net (clauses outside Easy whitelist: {extras})"


def classify(gold_cypher: Optional[str]) -> Optional[str]:
    """
    Classify a gold Cypher query into one of
    ``"easy" | "medium" | "hard" | "extra"`` or ``None`` (when no gold
    Cypher is available — e.g. Mind-the-Query NL-only examples).

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
            "extra":  {...},
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
