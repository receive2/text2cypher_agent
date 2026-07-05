#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_graphrag.py
================
Offline unit tests for the Multi-Agent GraphRAG baseline (``graphrag.py`` +
``config.py`` graphrag wiring).

No Neo4j, no LLM, no FAISS. ``graphrag`` imports ``agent.agent_helper`` (which
opens a live Neo4j connection at import) and ``agent.prompts`` (auto-generated),
so both are stubbed in ``sys.modules`` BEFORE the first import. DB-/LLM-touching
functions are monkeypatched per-test.

Run directly:  ``python tests/test_graphrag.py``
Or with pytest: ``pytest tests/test_graphrag.py``
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path

# Make the repo root importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Stub side-effecting deps BEFORE importing graphrag ────────────────────────
if "agent.agent_helper" not in sys.modules:
    _ah = types.ModuleType("agent.agent_helper")

    class _StubGraph:
        schema = "(:Movie)-[:directedBy]->(:Person)"
        def query(self, *a, **kw):
            return []

    _ah.neo4j_graph = _StubGraph()
    _ah.cypher_llm = object()
    _ah.qa_llm = object()
    _ah.ner_llm = object()
    sys.modules["agent.agent_helper"] = _ah

if "agent.prompts" not in sys.modules:
    _pr = types.ModuleType("agent.prompts")
    _pr.TEXT2CYPHER_SP = (
        "Schema:\n{schema}\n\nEntities:\n{relevant_entities}\n\n"
        "Question: {question}\nAnswer:"
    )
    sys.modules["agent.prompts"] = _pr

import config  # noqa: E402
import graphrag  # noqa: E402


class TestNormalizedLevenshtein(unittest.TestCase):
    def test_identical_is_one(self):
        self.assertEqual(graphrag.normalized_levenshtein("Matrix", "Matrix"), 1.0)

    def test_case_insensitive(self):
        self.assertEqual(graphrag.normalized_levenshtein("the matrix", "The Matrix"), 1.0)

    def test_perturbed_high(self):
        # "the matriks" vs canonical — must score high enough to rank near top.
        sim = graphrag.normalized_levenshtein("the matriks", "The Matrix")
        self.assertGreater(sim, 0.8)

    def test_unrelated_low(self):
        self.assertLess(graphrag.normalized_levenshtein("the matriks", "Then She Arrived"), 0.6)

    def test_empty(self):
        self.assertEqual(graphrag.normalized_levenshtein("", ""), 1.0)
        self.assertEqual(graphrag.normalized_levenshtein("abc", ""), 0.0)


class TestCleanCypher(unittest.TestCase):
    def test_strips_fence(self):
        out = graphrag._clean_cypher("```cypher\nMATCH (n) RETURN n\n```")
        self.assertEqual(out, "MATCH (n) RETURN n")

    def test_strips_label_prefix(self):
        self.assertEqual(graphrag._clean_cypher("cypher: MATCH (n) RETURN n"), "MATCH (n) RETURN n")

    def test_plain_passthrough(self):
        self.assertEqual(graphrag._clean_cypher("  MATCH (n) RETURN n  "), "MATCH (n) RETURN n")


class TestParseJson(unittest.TestCase):
    def test_extracts_object(self):
        self.assertEqual(graphrag._parse_json_obj('noise {"a": 1} tail'), {"a": 1})

    def test_none_on_garbage(self):
        self.assertIsNone(graphrag._parse_json_obj("no json here"))


class TestExtractComponents(unittest.TestCase):
    def test_simple_equality(self):
        comp = graphrag._extract_components(
            'MATCH (m:Movie)-[:directedBy]->(p:Person) WHERE m.name = "The Matrix" RETURN p.name'
        )
        self.assertIn("Movie", comp["labels"])
        self.assertIn("Person", comp["labels"])
        self.assertIn("directedBy", comp["rel_types"])
        self.assertIn(("Movie", "name", "The Matrix"), comp["props"])

    def test_tolower_wrapped(self):
        # The form that previously slipped through extraction entirely.
        comp = graphrag._extract_components(
            'MATCH (m:Movie) WHERE toLower(m.name) = toLower("the matriks") RETURN m'
        )
        self.assertIn(("Movie", "name", "the matriks"), comp["props"])

    def test_inline_map(self):
        comp = graphrag._extract_components(
            'MATCH (m:Movie {name: "The Matrix"})-[:directedBy]->(p:Person) RETURN p.name'
        )
        self.assertIn(("Movie", "name", "The Matrix"), comp["props"])

    def test_ignores_inequality(self):
        comp = graphrag._extract_components(
            'MATCH (m:Movie) WHERE m.year >= "2000" RETURN m'
        )
        self.assertNotIn(("Movie", "year", "2000"), comp["props"])


class TestSelectReplacements(unittest.TestCase):
    def test_fallback_to_top_candidate_when_llm_fails(self):
        class _BoomLLM:
            def invoke(self, *_a, **_k):
                raise RuntimeError("no llm")
        bad = [{"label": "Movie", "prop": "name", "value": "the matriks",
                "candidates": ["The Matrix", "The Patriot"]}]
        out = graphrag._select_replacements(bad, _BoomLLM())
        self.assertEqual(out["the matriks"], "The Matrix")

    def test_honours_llm_pick_in_candidates(self):
        class _LLM:
            def invoke(self, *_a, **_k):
                return types.SimpleNamespace(content='{"the matriks": "The Matrix"}')
        bad = [{"label": "Movie", "prop": "name", "value": "the matriks",
                "candidates": ["The Patriot", "The Matrix"]}]
        out = graphrag._select_replacements(bad, _LLM())
        self.assertEqual(out["the matriks"], "The Matrix")

    def test_rejects_llm_pick_not_in_candidates(self):
        class _LLM:
            def invoke(self, *_a, **_k):
                return types.SimpleNamespace(content='{"the matriks": "Hallucinated"}')
        bad = [{"label": "Movie", "prop": "name", "value": "the matriks",
                "candidates": ["The Matrix"]}]
        out = graphrag._select_replacements(bad, _LLM())
        self.assertEqual(out["the matriks"], "The Matrix")   # falls back to top


class TestStructuralFeedback(unittest.TestCase):
    def test_mentions_replacement(self):
        validation = {
            "bad_labels": [], "bad_rels": ["actedIn"],
            "valid_labels": ["Movie", "Person"], "valid_rels": ["directedBy"],
            "bad_values": [{"label": "Movie", "prop": "name", "value": "the matriks",
                            "candidates": ["The Matrix"]}],
        }
        fb = graphrag._build_structural_feedback(
            "MATCH ...", None, validation, {"the matriks": "The Matrix"})
        self.assertIn("actedIn", fb)
        self.assertIn('Use "The Matrix"', fb)


class TestRunGraphragLoop(unittest.TestCase):
    """Drive the loop with the DB-/LLM-touching helpers monkeypatched."""

    def setUp(self):
        self._orig = {n: getattr(graphrag, n) for n in
                      ("_generate_cypher", "_execute", "_evaluate_semantics",
                       "_validate", "_select_replacements", "_format_answer")}
        graphrag._format_answer = lambda q, rows, llm: "ANSWER"
        graphrag._validate = lambda comp: {
            "bad_labels": [], "bad_rels": [],
            "valid_labels": [], "valid_rels": [],
            "bad_values": [{"label": "Movie", "prop": "name",
                            "value": "the matriks", "candidates": ["The Matrix"]}],
        }
        graphrag._select_replacements = lambda bad, llm: {"the matriks": "The Matrix"}

    def tearDown(self):
        for n, fn in self._orig.items():
            setattr(graphrag, n, fn)

    def test_accept_round_1(self):
        graphrag._generate_cypher = lambda *a, **k: "MATCH (m:Movie {name:'Inception'}) RETURN m"
        graphrag._execute = lambda c: ([{"x": 1}], None)
        graphrag._evaluate_semantics = lambda *a, **k: ("accept", "")
        out = graphrag.run_graphrag("q")
        self.assertTrue(out["graphrag_accepted"])
        self.assertEqual(len(out["graphrag_trace"]), 1)
        self.assertEqual(out["mode"], "graphrag")

    def test_empty_then_repair_to_accept(self):
        seq = iter([
            "MATCH (m:Movie) WHERE toLower(m.name)=toLower('the matriks') RETURN m",  # r1 → empty
            "MATCH (m:Movie {name:'The Matrix'}) RETURN m",                            # r2 → rows
        ])
        graphrag._generate_cypher = lambda *a, **k: next(seq)
        calls = {"n": 0}
        def _exec(c):
            calls["n"] += 1
            return ([], None) if calls["n"] == 1 else ([{"x": 1}], None)
        graphrag._execute = _exec
        graphrag._evaluate_semantics = lambda *a, **k: ("accept", "")
        out = graphrag.run_graphrag("q")
        self.assertTrue(out["graphrag_accepted"])
        self.assertEqual(len(out["graphrag_trace"]), 2)
        self.assertIn("The Matrix", out["cypher"])

    def test_exhausts_returns_last_attempt(self):
        # Faithful to the paper: no "keep best non-empty" safety net — after
        # exhausting the round budget the LAST attempt is returned as-is.
        outs = iter(["C1_ROWS", "C2_EMPTY", "C3_ROWS", "C4_EMPTY"])
        graphrag._generate_cypher = lambda *a, **k: next(outs)
        def _exec(c):
            return ([{"r": c}], None) if c.endswith("ROWS") else ([], None)
        graphrag._execute = _exec
        graphrag._evaluate_semantics = lambda *a, **k: ("incorrect", "nope")
        out = graphrag.run_graphrag("q")
        self.assertFalse(out["graphrag_accepted"])
        self.assertEqual(len(out["graphrag_trace"]), config.GRAPHRAG_MAX_ITER)
        # Returns the final attempt verbatim (here the empty C4), NOT a rescued
        # earlier non-empty one.
        self.assertEqual(out["cypher"], "C4_EMPTY")
        self.assertEqual(out["context"], [])


class TestConfigResolution(unittest.TestCase):
    def test_graphrag_spec_roundtrip(self):
        spec = config.GroundingSpec("graphrag")
        self.assertEqual(spec.method, "graphrag")
        self.assertEqual(spec.canonical, "graphrag")
        self.assertEqual(config.resolve_spec("graphrag").method, "graphrag")

    def test_cyanchor_canonical_roundtrip(self):
        spec = config.GroundingSpec("cyanchor", tool="node_rel", fuzzy=True, vector=False, lev=True)
        self.assertEqual(spec.canonical, "cyanchor_fl_node_rel")
        rt = config._spec_from_canonical("cyanchor_fl_node_rel")
        self.assertEqual((rt.method, rt.tool, rt.fuzzy, rt.vector, rt.lev),
                         ("cyanchor", "node_rel", True, False, True))


class TestEdgePatternValidation(unittest.TestCase):
    """Pairwise edge-pattern validation (faithful to Multi-Agent GraphRAG Alg.1)."""

    def setUp(self):
        self._e = graphrag._EDGE_PATTERNS_CACHE
        self._l = graphrag._LABELS_CACHE
        self._r = graphrag._RELTYPES_CACHE
        graphrag._EDGE_PATTERNS_CACHE = {("Movie", "directedBy", "Person")}
        graphrag._LABELS_CACHE = {"Movie", "Person", "Genre"}
        graphrag._RELTYPES_CACHE = {"directedBy"}

    def tearDown(self):
        graphrag._EDGE_PATTERNS_CACHE = self._e
        graphrag._LABELS_CACHE = self._l
        graphrag._RELTYPES_CACHE = self._r

    def test_valid_edge_not_flagged(self):
        comp = graphrag._extract_components('MATCH (m:Movie)-[:directedBy]->(p:Person) RETURN p')
        self.assertEqual(graphrag._validate(comp)["bad_edges"], [])

    def test_impossible_edge_flagged(self):
        comp = graphrag._extract_components('MATCH (m:Movie)-[:directedBy]->(g:Genre) RETURN g')
        self.assertIn(("Movie", "directedBy", "Genre"), graphrag._validate(comp)["bad_edges"])

    def test_reverse_direction_not_flagged(self):
        # (Person)<-[:directedBy]-(Movie) resolves to (Movie,directedBy,Person) — valid.
        comp = graphrag._extract_components('MATCH (p:Person)<-[:directedBy]-(m:Movie) RETURN p')
        self.assertEqual(graphrag._validate(comp)["bad_edges"], [])

    def test_unknown_schema_skips_validation(self):
        graphrag._EDGE_PATTERNS_CACHE = set()   # unknown → fail-safe, never flag
        comp = graphrag._extract_components('MATCH (m:Movie)-[:directedBy]->(g:Genre) RETURN g')
        self.assertEqual(graphrag._validate(comp)["bad_edges"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
