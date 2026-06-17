# -*- coding: utf-8 -*-
"""
tests/test_difficulty.py
========================
Golden test cases anchoring the redesigned `eval/difficulty.py` rubric
(docs/DIFFICULTY_DESIGN.md). Each case is a deliberate boundary marker
in the §3.1 detector table — together they pin the rubric so future edits
to the parser can't silently regress a tier.
"""

from __future__ import annotations

import pytest

from eval.difficulty import classify, classify_explain


# ── EASY ─────────────────────────────────────────────────────────────────────

EASY_CASES = [
    # bare lookup
    "MATCH (n:Person) RETURN n",
    # single property return, single equality predicate
    "MATCH (n:Person) WHERE n.name = 'Alice' RETURN n.age",
    # 1-hop, 1 predicate, plain property return
    "MATCH (a:Person)-[:KNOWS]->(b:Person) WHERE a.name = 'Alice' RETURN b.name",
    # CypherBench dominant idiom — naturally scores 0 (WITH ignored, 1 pred = Filter 0)
    "MATCH (n:Player) WITH DISTINCT n WHERE n.team = 'CHI' RETURN n.name",
]


# ── MEDIUM ───────────────────────────────────────────────────────────────────

MEDIUM_CASES = [
    # single agg → Op=1 → score 1
    ("MATCH (n:Person) RETURN COUNT(n)", "Op=1 single agg"),
    # 2-hop → Reach=1 → score 1
    ("MATCH (a)-[:R]->(b)-[:S]->(c) RETURN c.name", "Reach=1 2-hop"),
    # sort+limit (not argmax — LIMIT > 1) → Op=1
    ("MATCH (n:Person) RETURN n.name ORDER BY n.age DESC LIMIT 10", "Op=1 sort"),
    # OPTIONAL MATCH → Op=1
    ("MATCH (a:Person) OPTIONAL MATCH (a)-[:KNOWS]->(b) RETURN a.name, b.name",
     "Op=1 OPTIONAL MATCH"),
    # two predicates → Filter=1 → score 1
    ("MATCH (n:Person) WHERE n.name = 'Alice' AND n.age > 30 RETURN n",
     "Filter=1 two predicates"),
    # group-by + 1-hop, no extra filter → Op=2 only → score 2 → medium
    ("MATCH (n:Person)-[:WORKS_AT]->(c:Company) RETURN c.name, COUNT(n) "
     "ORDER BY c.name", "Op=2 group-by alone"),
    # 4-hop alone (no agg, no filter) → Reach=2 → score 2 → medium
    ("MATCH (a)-[:R1]->(b)-[:R2]->(c)-[:R3]->(d)-[:R4]->(e) RETURN e",
     "Reach=2 4-hop alone"),
]


# ── HARD ─────────────────────────────────────────────────────────────────────

HARD_CASES = [
    # group-by + 2-hop → Op=2 + Reach=1 = 3
    ("MATCH (a:Person)-[:WORKS_AT]->(c)-[:LOCATED_IN]->(city) "
     "RETURN city.name, COUNT(a) ORDER BY city.name",
     "Op=2 group-by + Reach=1"),
    # argmax + 2-pred WHERE → Op=2 + Filter=1 = 3
    ("MATCH (p:Person)-[:AUTHORED]->(:Paper) WHERE p.active = true AND p.age > 30 "
     "WITH p, COUNT(*) AS n ORDER BY n DESC LIMIT 1 RETURN p.name",
     "Op=2 argmax + Filter=1"),
    # 4-hop + count → Reach=2 + Op=1 = 3
    ("MATCH (a)-[:R1]->(b)-[:R2]->(c)-[:R3]->(d)-[:R4]->(e) RETURN count(e)",
     "Reach=2 4-hop + Op=1 agg"),
    # 3 preds + count → Filter=2 + Op=1 = 3
    ("MATCH (a:Person)-[:KNOWS]->(b) WHERE a.age > 30 AND a.city = 'NYC' "
     "AND b.active = true RETURN count(b)",
     "Filter=2 + Op=1 agg"),
    # CASE WHEN + 2-hop → Op=2 + Reach=1 = 3
    ("MATCH (a)-[:R]->(b)-[:S]->(c) RETURN CASE WHEN c.age > 30 THEN 'old' "
     "ELSE 'young' END", "Op=2 CASE WHEN + Reach=1"),
    # nested subquery — hard-override (depth ≥ 2)
    ("MATCH (n:Person) WHERE EXISTS { MATCH (n)-[:OWNS]->(c:Car) "
     "WHERE EXISTS { MATCH (c)-[:MADE_BY]->(:Brand) } } RETURN n",
     "hard-override: nested subquery"),
    # set-op + multi-hop → hard-override
    ("MATCH (a)-[:R]->(b)-[:S]->(c) RETURN c "
     "UNION MATCH (a)-[:T]->(b)-[:U]->(c) RETURN c",
     "hard-override: UNION + multi-hop"),
    # variable-length path → Reach=2; plus group-by (Op=2) and 2 preds (Filter=1)
    # → score = 2+2+1 = 5 → hard (would have been extra in 4-tier system)
    ("MATCH (a)-[r*1..3]->(b) WHERE a.x > 5 AND b.y < 10 "
     "RETURN a.name, COUNT(b)", "score=5: var-length + group-by + Filter"),
]


# ── parametrized assertions ──────────────────────────────────────────────────


def _explain(case):
    cypher, label = case if isinstance(case, tuple) else (case, "")
    return cypher, label


@pytest.mark.parametrize("case", EASY_CASES)
def test_easy(case):
    cypher, label = _explain(case)
    got, reason = classify_explain(cypher)
    assert got == "easy", f"expected easy ({label}); got {got!r} — {reason}\n{cypher}"


@pytest.mark.parametrize("case", MEDIUM_CASES)
def test_medium(case):
    cypher, label = _explain(case)
    got, reason = classify_explain(cypher)
    assert got == "medium", f"expected medium ({label}); got {got!r} — {reason}\n{cypher}"


@pytest.mark.parametrize("case", HARD_CASES)
def test_hard(case):
    cypher, label = _explain(case)
    got, reason = classify_explain(cypher)
    assert got == "hard", f"expected hard ({label}); got {got!r} — {reason}\n{cypher}"


# ── none / sanity ────────────────────────────────────────────────────────────


def test_none_for_empty():
    assert classify(None) is None
    assert classify("") is None
    assert classify("   ") is None


def test_with_distinct_idiom_not_hard():
    """The CypherBench dominant idiom must NOT auto-promote to hard
    just because it contains WITH/DISTINCT — this is the bug fix."""
    cypher = ("MATCH (n:Movie) WITH DISTINCT n WHERE n.year > 2000 "
              "RETURN n.title")
    got, reason = classify_explain(cypher)
    assert got in ("easy", "medium"), \
        f"WITH DISTINCT idiom must NOT be hard; got {got!r} — {reason}"


def test_bare_count_is_medium_not_hard():
    """A lone count() is the most common query (`how many…`), not hard."""
    assert classify("MATCH (n:Person) RETURN COUNT(n)") == "medium"
    assert classify("MATCH (n:Person) WHERE n.age > 30 RETURN COUNT(n)") == "medium"
