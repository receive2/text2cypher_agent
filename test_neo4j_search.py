"""
Test script for neo4j_search.py — verifies that full-text search returns
deduplicated property values with the highest score per unique value.

Prerequisites:
  - A running Neo4j instance with the movies sample dataset loaded.
  - Environment variables set (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD).
    These can live in a .env file in the project root.

Usage:
  python test_neo4j_search.py
"""

import sys
from dotenv import load_dotenv

load_dotenv()

from neo4j_search import (
    top_similar_values,
    top_similar_rel_values,
    search_tool,
    search_rel_tool,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check_no_duplicates(results, label):
    """Assert every value appears exactly once."""
    values = [r["value"] for r in results]
    dupes = [v for v in values if values.count(v) > 1]
    assert len(set(values)) == len(values), (
        f"[FAIL] {label}: duplicate values found → {set(dupes)}"
    )
    print(f"  [PASS] No duplicate values  ({len(values)} results)")


def _check_descending_scores(results, label):
    """Assert scores are in non-increasing order."""
    scores = [r["score"] for r in results]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"[FAIL] {label}: scores not descending at index {i} "
            f"({scores[i]} < {scores[i + 1]})"
        )
    print(f"  [PASS] Scores in descending order")


def _check_no_none_values(results, label):
    """Assert no None values snuck through."""
    nones = [r for r in results if r["value"] is None]
    assert len(nones) == 0, f"[FAIL] {label}: found {len(nones)} None value(s)"
    print(f"  [PASS] No None values")


def _check_k_limit(results, k, label):
    """Assert result count is at most k."""
    assert len(results) <= k, (
        f"[FAIL] {label}: got {len(results)} results, expected <= {k}"
    )
    print(f"  [PASS] Result count ({len(results)}) <= k ({k})")


def _check_search_tool_strings(values, label):
    """Assert search_tool / search_rel_tool returns a flat list of strings."""
    assert isinstance(values, list), f"[FAIL] {label}: expected list, got {type(values)}"
    for v in values:
        assert isinstance(v, str), (
            f"[FAIL] {label}: expected str, got {type(v)} → {v!r}"
        )
    print(f"  [PASS] All values are strings")


# ── Test cases ───────────────────────────────────────────────────────────────

def test_node_search():
    """Test top_similar_values with Movie.title (node property)."""
    print("\n─── Test: top_similar_values (Movie.title) ───")

    k = 10
    results = top_similar_values(
        phrase="The Matrix",
        node_label="Movie",
        property_name="title",
        k=k,
        fuzziness=1,
    )
    print(f"  Query: 'The Matrix' | Label: Movie | Property: title | k={k}")
    for i, r in enumerate(results, 1):
        print(f"    {i:2d}. {r['value']}  (score={r['score']:.4f})")

    _check_no_duplicates(results, "Movie.title")
    _check_descending_scores(results, "Movie.title")
    _check_no_none_values(results, "Movie.title")
    _check_k_limit(results, k, "Movie.title")


def test_node_search_person():
    """Test top_similar_values with Person.name (node property)."""
    print("\n─── Test: top_similar_values (Person.name) ───")

    k = 5
    results = top_similar_values(
        phrase="Tom Hanks",
        node_label="Person",
        property_name="name",
        k=k,
        fuzziness=1,
    )
    print(f"  Query: 'Tom Hanks' | Label: Person | Property: name | k={k}")
    for i, r in enumerate(results, 1):
        print(f"    {i:2d}. {r['value']}  (score={r['score']:.4f})")

    _check_no_duplicates(results, "Person.name")
    _check_descending_scores(results, "Person.name")
    _check_no_none_values(results, "Person.name")
    _check_k_limit(results, k, "Person.name")


def test_search_tool():
    """Test search_tool returns flat list of unique strings."""
    print("\n─── Test: search_tool (Movie.title) ───")

    k = 10
    values = search_tool(
        phrase="The Matrix",
        node_label="Movie",
        property_name="title",
        k=k,
        verbose=True,
    )
    _check_search_tool_strings(values, "search_tool")
    assert len(set(values)) == len(values), (
        f"[FAIL] search_tool: duplicate values → {values}"
    )
    print(f"  [PASS] No duplicates in search_tool output")


def test_rel_search():
    """Test top_similar_rel_values with ACTED_IN.roles (relationship property)."""
    print("\n─── Test: top_similar_rel_values (ACTED_IN.roles) ───")

    k = 10
    results = top_similar_rel_values(
        phrase="Neo",
        rel_type="ACTED_IN",
        property_name="roles",
        k=k,
        fuzziness=1,
    )
    print(f"  Query: 'Neo' | RelType: ACTED_IN | Property: roles | k={k}")
    for i, r in enumerate(results, 1):
        print(f"    {i:2d}. {r['value']}  (score={r['score']:.4f})")

    _check_no_duplicates(results, "ACTED_IN.roles")
    _check_descending_scores(results, "ACTED_IN.roles")
    _check_no_none_values(results, "ACTED_IN.roles")
    _check_k_limit(results, k, "ACTED_IN.roles")


def test_search_rel_tool():
    """Test search_rel_tool returns flat list of unique strings."""
    print("\n─── Test: search_rel_tool (REVIEWED.summary) ───")

    k = 10
    values = search_rel_tool(
        phrase="excellent",
        rel_type="REVIEWED",
        property_name="summary",
        k=k,
        verbose=True,
    )
    _check_search_tool_strings(values, "search_rel_tool")
    assert len(set(values)) == len(values), (
        f"[FAIL] search_rel_tool: duplicate values → {values}"
    )
    print(f"  [PASS] No duplicates in search_rel_tool output")


# ── Runner ───────────────────────────────────────────────────────────────────

def main():
    passed = 0
    failed = 0
    tests = [
        test_node_search,
        test_node_search_person,
        test_search_tool,
        test_rel_search,
        test_search_rel_tool,
    ]

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"\n  {e}")
            failed += 1
        except Exception as e:
            print(f"\n  [ERROR] {test_fn.__name__}: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 50)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
