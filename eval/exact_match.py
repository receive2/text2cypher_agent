#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exact_match.py
==============
Literal-string Exact-Match (EM) metric for predicted vs. gold Cypher.

This is a strict, surface-level definition of EM:

    pred_norm == gold_norm

after **light whitespace normalisation only**:

    * collapse runs of whitespace to a single space
    * strip leading/trailing whitespace
    * normalise trailing semicolons (drop one trailing ``;`` and any
      whitespace that follows it)

We deliberately do **NOT**:

    * alias-rewrite (``MATCH (m:Movie)`` vs ``MATCH (movie:Movie)`` → mismatch)
    * re-parse the AST or canonicalise clause order
    * lower-case keywords or identifiers
    * normalise property-map whitespace beyond the run-collapse rule above

The CypherBench paper and most subsequent text-to-Cypher benchmarks
(Mind-the-Query, ZOGRASCOPE) treat EM as a *literal* signal that
upper-bounds how often a system reproduces the canonical solution
character-for-character.  Any AST-level normalisation would confound EM
with semantic-equivalence metrics like Execution Accuracy.

This module is shared by ``metrics_CypherBench``, ``metrics_MindTheQuery``,
and ``metrics_ZOGRASCOPE`` so all three datasets compute EM identically.
"""

from __future__ import annotations

import re
from typing import Optional


# Single regex compiled at import time — runs of whitespace (including
# newlines / tabs) collapse to a single space.
_WS_RE = re.compile(r"\s+")

# Trailing-semicolon pattern: at most one ``;`` followed by optional
# whitespace at the very end of the string.
_TRAIL_SEMI_RE = re.compile(r";\s*$")


def normalize_cypher_for_em(cypher: str) -> str:
    """
    Apply the EM whitespace-normalisation pipeline to a single Cypher string.

    Steps
    -----
    1. Strip leading/trailing whitespace.
    2. Drop a single trailing semicolon (``;``) plus any whitespace after it.
    3. Collapse internal runs of whitespace to a single ASCII space.

    Parameters
    ----------
    cypher : str
        Raw Cypher source — predicted or gold.

    Returns
    -------
    str
        Normalised Cypher suitable for literal string comparison.
    """
    if cypher is None:
        return ""
    s = cypher.strip()
    s = _TRAIL_SEMI_RE.sub("", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def exact_match(pred_cypher: Optional[str], gold_cypher: Optional[str]) -> Optional[bool]:
    """
    Literal-string EM between *pred_cypher* and *gold_cypher*.

    Returns
    -------
    bool | None
        ``True`` iff the two normalised strings are identical.
        ``None`` if *gold_cypher* is ``None`` (EM is not applicable when
        the dataset does not ship a gold Cypher — e.g. Mind-the-Query
        examples that only have NL + expected rows).
        ``False`` otherwise (including when *pred_cypher* is empty or
        ``None`` while gold is present, since the prediction does not
        match the reference).
    """
    if gold_cypher is None:
        return None
    if pred_cypher is None:
        return False
    return normalize_cypher_for_em(pred_cypher) == normalize_cypher_for_em(gold_cypher)
