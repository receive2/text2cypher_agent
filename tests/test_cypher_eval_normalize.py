#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_cypher_eval_normalize.py
=============================
Unit tests for ``cypher_eval_normalize.normalize_result_set``.

These tests deliberately mock Neo4j driver objects rather than spinning up
a live database — every test is offline.  The mocks satisfy the duck-type
predicates used in :mod:`cypher_eval_normalize`:

    * ``FakeNode``         — has ``labels`` + ``items()``, no ``type``, no ``nodes``.
    * ``FakeRelationship`` — has ``type``  + ``items()``, no ``labels``.
    * ``FakePath``         — has ``nodes`` + ``relationships``.

Run directly:  ``python test_cypher_eval_normalize.py``
Or with pytest: ``pytest test_cypher_eval_normalize.py``
"""

from __future__ import annotations

import unittest
from collections import Counter
from typing import Any, Iterable

from eval.cypher_eval_normalize import (
    normalize_result_set,
    column_counts_match,
    has_order_by,
    strict_cypherbench_kwargs,
)


# ──────────────────────────────────────────────────────────────────────────────
# Driver-object mocks (duck-typed to match _is_neo4j_node / _Relationship / _Path)
# ──────────────────────────────────────────────────────────────────────────────

class FakeNode:
    """Quacks like ``neo4j.graph.Node`` for the normaliser's duck-type check."""
    def __init__(self, labels, props, element_id="elem-rand"):
        self.labels = frozenset(labels)
        self._props = dict(props)
        # Real driver Nodes carry a transient element_id; we include one to
        # prove that two FakeNodes with different element_ids and identical
        # labels+props still compare equal under expand_nodes=True.
        self.element_id = element_id

    def items(self):
        return self._props.items()

    def __repr__(self):  # noqa: D401 — keep id in repr to stress-test fallbacks
        return (
            f"<FakeNode labels={sorted(self.labels)} props={self._props} "
            f"element_id={self.element_id!r}>"
        )


class FakeRelationship:
    def __init__(self, rtype, props, element_id="rel-rand"):
        self.type = rtype
        self._props = dict(props)
        self.element_id = element_id

    def items(self):
        return self._props.items()

    def __repr__(self):
        return (
            f"<FakeRel type={self.type!r} props={self._props} "
            f"element_id={self.element_id!r}>"
        )


class FakePath:
    def __init__(self, nodes, relationships):
        self.nodes = list(nodes)
        self.relationships = list(relationships)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def multiset_equal(rows_a: Iterable[Any], rows_b: Iterable[Any]) -> bool:
    return Counter(rows_a) == Counter(rows_b)


# A faithful re-implementation of upstream CypherBench's ``to_hashable``
# (megagonlabs/cypherbench@main : cypherbench/metrics/execution_accuracy.py
# lines 16-51) for the regression test.  This is the byte-identical
# baseline that strict mode must match on literal-only fixtures.
def _upstream_to_hashable(obj, unorder_list=True):
    if isinstance(obj, (tuple, int, float, str, bool, type(None))):
        return obj
    if isinstance(obj, (list, tuple)):
        if unorder_list:
            return tuple(sorted(_upstream_to_hashable(x) for x in obj))
        return tuple(_upstream_to_hashable(x) for x in obj)
    if isinstance(obj, set):
        return tuple(sorted(_upstream_to_hashable(x) for x in obj))
    if isinstance(obj, dict):
        return tuple(sorted(
            (_upstream_to_hashable(k), _upstream_to_hashable(v))
            for k, v in obj.items()
        ))
    raise TypeError(f"Unhashable type: {type(obj)}")


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestLiteralOnly(unittest.TestCase):
    """Cases that match CypherBench's original literal-only assumption."""

    def test_identical_literal_rows_equal(self):
        gold = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        pred = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        self.assertTrue(multiset_equal(
            normalize_result_set(gold),
            normalize_result_set(pred),
        ))

    def test_different_column_counts_fast_path(self):
        gold = [{"a": 1, "b": 2}]
        pred = [{"a": 1}]
        self.assertFalse(column_counts_match(pred, gold))

    def test_alias_difference_equal_under_default(self):
        # gold: RETURN p.name AS x ; pred: RETURN p.name AS y — same values
        gold = [{"x": "alice"}, {"x": "bob"}]
        pred = [{"y": "alice"}, {"y": "bob"}]
        self.assertTrue(multiset_equal(
            normalize_result_set(gold),
            normalize_result_set(pred),
        ))

    def test_alias_difference_not_equal_under_compare_keys(self):
        gold = [{"x": "alice"}, {"x": "bob"}]
        pred = [{"y": "alice"}, {"y": "bob"}]
        self.assertNotEqual(
            normalize_result_set(gold, compare_keys=True),
            normalize_result_set(pred, compare_keys=True),
        )


class TestFloats(unittest.TestCase):
    def test_floats_within_eps_equal(self):
        gold = [{"avg": 0.3333333}]
        pred = [{"avg": 0.3333334}]
        self.assertTrue(multiset_equal(
            normalize_result_set(gold),
            normalize_result_set(pred),
        ))

    def test_floats_with_zero_eps_strict(self):
        gold = [{"avg": 0.3333333}]
        pred = [{"avg": 0.3333334}]
        self.assertNotEqual(
            normalize_result_set(gold, float_eps=0.0),
            normalize_result_set(pred, float_eps=0.0),
        )


class TestCollections(unittest.TestCase):
    def test_collect_unordered_equal_no_order_by(self):
        # collect() returns lists; without ORDER BY, [1,2,3] ≡ [3,2,1].
        gold = [{"items": [1, 2, 3]}]
        pred = [{"items": [3, 2, 1]}]
        self.assertTrue(multiset_equal(
            normalize_result_set(gold, gold_cypher="MATCH (n) RETURN collect(n.x) AS items"),
            normalize_result_set(pred, gold_cypher="MATCH (n) RETURN collect(n.x) AS items"),
        ))

    def test_collect_ordered_not_equal_with_order_by(self):
        gold_cypher = "MATCH (n) RETURN collect(n.x) AS items ORDER BY n.rank"
        gold = [{"items": [1, 2, 3]}]
        pred = [{"items": [3, 2, 1]}]
        self.assertNotEqual(
            normalize_result_set(gold, gold_cypher=gold_cypher),
            normalize_result_set(pred, gold_cypher=gold_cypher),
        )

    def test_has_order_by_ignores_subquery_block(self):
        sql = "MATCH (n) CALL { WITH n RETURN n ORDER BY n.x } RETURN n"
        # Best-effort: the ORDER BY is inside a CALL { ... } block.
        self.assertFalse(has_order_by(sql))

    def test_has_order_by_finds_top_level(self):
        self.assertTrue(has_order_by("MATCH (n) RETURN n ORDER BY n.x"))


class TestNodes(unittest.TestCase):
    def test_same_node_two_executions_equal(self):
        # Same logical node returned from two query executions — different
        # element_ids, identical labels + properties.  Must compare equal
        # under expand_nodes=True (the new behaviour).
        gold = [{"p": FakeNode(["Person"], {"name": "Alice", "born": 1970}, element_id="exec1-42")}]
        pred = [{"p": FakeNode(["Person"], {"name": "Alice", "born": 1970}, element_id="exec2-99")}]
        self.assertTrue(multiset_equal(
            normalize_result_set(gold),
            normalize_result_set(pred),
        ))

    def test_node_vs_literal_name_not_equal(self):
        # gold returned a string; pred returned a node with that name as a
        # property.  This is a real semantic mismatch — must NOT match.
        gold = [{"name": "Alice"}]
        pred = [{"p": FakeNode(["Person"], {"name": "Alice", "born": 1970})}]
        self.assertNotEqual(
            normalize_result_set(gold),
            normalize_result_set(pred),
        )

    def test_different_labels_not_equal(self):
        gold = [{"p": FakeNode(["Person"], {"name": "Alice"})}]
        pred = [{"p": FakeNode(["Person", "Actor"], {"name": "Alice"})}]
        self.assertNotEqual(
            normalize_result_set(gold),
            normalize_result_set(pred),
        )

    def test_column_swap_equal_under_default(self):
        # gold RETURN p, m ; pred RETURN m, p — column-order ignored by default.
        p_node = FakeNode(["Person"], {"name": "Alice"})
        m_node = FakeNode(["Movie"], {"title": "Matrix"})
        gold = [{"p": p_node, "m": m_node}]
        pred = [{"m": m_node, "p": p_node}]
        self.assertTrue(multiset_equal(
            normalize_result_set(gold),
            normalize_result_set(pred),
        ))


class TestRelationships(unittest.TestCase):
    def test_same_rel_two_executions_equal(self):
        gold = [{"r": FakeRelationship("ACTED_IN", {"role": "Neo"}, element_id="rel-x")}]
        pred = [{"r": FakeRelationship("ACTED_IN", {"role": "Neo"}, element_id="rel-y")}]
        self.assertTrue(multiset_equal(
            normalize_result_set(gold),
            normalize_result_set(pred),
        ))

    def test_different_rel_types_not_equal(self):
        gold = [{"r": FakeRelationship("ACTED_IN", {})}]
        pred = [{"r": FakeRelationship("DIRECTED",  {})}]
        self.assertNotEqual(
            normalize_result_set(gold),
            normalize_result_set(pred),
        )


class TestPath(unittest.TestCase):
    def test_path_normalised_structurally(self):
        n1 = FakeNode(["Person"], {"name": "Alice"}, element_id="n1-a")
        n2 = FakeNode(["Movie"],  {"title": "Matrix"}, element_id="n2-a")
        r  = FakeRelationship("ACTED_IN", {"role": "Neo"}, element_id="r-a")
        path_a = FakePath([n1, n2], [r])

        # Same structural path, different element_ids on every component.
        n1b = FakeNode(["Person"], {"name": "Alice"}, element_id="n1-b")
        n2b = FakeNode(["Movie"],  {"title": "Matrix"}, element_id="n2-b")
        rb  = FakeRelationship("ACTED_IN", {"role": "Neo"}, element_id="r-b")
        path_b = FakePath([n1b, n2b], [rb])

        self.assertEqual(
            normalize_result_set([{"path": path_a}]),
            normalize_result_set([{"path": path_b}]),
        )


class TestStrictCypherBenchRegression(unittest.TestCase):
    """expand_nodes=False, expand_relationships=False on a literal-only
    fixture must be byte-identical to upstream CypherBench's ``to_hashable``
    behaviour (sorted lists, exact float equality, no string folding,
    Node/Rel raise — we never feed those in this regression test)."""

    def test_strict_matches_upstream_to_hashable(self):
        fixture = [
            {"name": "Alice", "scores": [3, 1, 2], "avg": 0.3333333},
            {"name": "Bob",   "scores": [9, 8, 7], "avg": 0.5},
        ]

        # Our strict-mode normalisation, row by row.
        ours = normalize_result_set(fixture, **strict_cypherbench_kwargs())

        # Upstream's normalisation, row by row.  Upstream applies
        # to_hashable to the **dict** of each row directly, then drops
        # column-key associativity by sorting (key, value) pairs.  Our
        # default-row layout (compare_keys=False, compare_column_order=False)
        # drops keys and sorts values; to compare apples-to-apples, we
        # mirror our layout for the upstream baseline.
        expected = []
        for row in fixture:
            sigs = [_upstream_to_hashable(v) for v in row.values()]
            if len(sigs) == 1:
                expected.append((sigs[0],))
            else:
                expected.append(tuple(sorted(sigs, key=repr)))

        self.assertEqual(ours, expected)

    def test_strict_floats_use_exact_equality(self):
        gold = [{"avg": 0.3333333}]
        pred = [{"avg": 0.3333334}]
        kw = strict_cypherbench_kwargs()
        # In strict mode, float drift must NOT be tolerated.
        self.assertNotEqual(
            normalize_result_set(gold, **kw),
            normalize_result_set(pred, **kw),
        )

    def test_strict_strings_no_case_folding(self):
        gold = [{"name": "Alice"}]
        pred = [{"name": "alice"}]
        kw = strict_cypherbench_kwargs()
        self.assertNotEqual(
            normalize_result_set(gold, **kw),
            normalize_result_set(pred, **kw),
        )

    def test_strict_does_not_expand_nodes(self):
        # Under strict mode, a Node falls through to repr() (legacy fallback).
        # Two nodes with different element_ids therefore do NOT compare equal,
        # mirroring upstream's "Node is unhashable" behaviour as closely as
        # we can without raising.
        kw = strict_cypherbench_kwargs()
        a = [{"p": FakeNode(["Person"], {"name": "Alice"}, element_id="x")}]
        b = [{"p": FakeNode(["Person"], {"name": "Alice"}, element_id="y")}]
        self.assertNotEqual(
            normalize_result_set(a, **kw),
            normalize_result_set(b, **kw),
        )


class TestFastPaths(unittest.TestCase):
    def test_empty_rows_equal(self):
        self.assertTrue(multiset_equal(
            normalize_result_set([]),
            normalize_result_set([]),
        ))

    def test_none_treated_as_empty(self):
        self.assertEqual(normalize_result_set(None), [])

    def test_column_counts_match_empty_sides(self):
        self.assertTrue(column_counts_match([], [{"a": 1}]))
        self.assertTrue(column_counts_match([{"a": 1}], []))

    def test_column_counts_match_mismatch(self):
        self.assertFalse(column_counts_match(
            [{"a": 1}],
            [{"a": 1, "b": 2}],
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
