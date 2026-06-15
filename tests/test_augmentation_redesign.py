"""
tests.test_augmentation_redesign
================================
Offline unit tests for the redesigned augmentation pipeline
(docs/AUGMENTATION_REDESIGN.md).  No live Neo4j and no LLM: the DB-grounded
checks use InMemoryValueProvider; LLM-only paths are exercised via the
attested-source / decline branches.
"""

from __future__ import annotations

import os
import random
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data_augmentation import validity as V
from data_augmentation.validity import InMemoryValueProvider
from data_augmentation.augmenters import (
    AugContext, CasingAugmenter, TypoAugmenter, PartialNameAugmenter, AliasAugmenter,
)
from data_augmentation.llm import LLMClient
from data_augmentation.entity_extractor import classify_entity, extract_entities
from data_augmentation.kb_aliases import AliasProvider
from data_augmentation.pipeline import QuotaSampler, augment_nl, row_rng


def _ctx(nl="x", values=None, aliases=None, label=None, prop=None,
         synthetic=False, start=None, end=None, seed=0):
    return AugContext(nl=nl, rng=random.Random(seed), llm=LLMClient(None),
                      span_start=start, span_end=end, label=label, prop=prop,
                      values=values, aliases=aliases, synthetic_domain=synthetic)


# ── Damerau ───────────────────────────────────────────────────────────────────

def test_damerau_transposition_is_one():
    # The bug that drove typo to 0%: plain Levenshtein scores a swap as 2.
    assert V.damerau_distance("Greece", "Gerece") == 1
    assert V.damerau_distance("Barletta", "Balretta") == 1
    assert V.damerau_le("Greece", "Gerece", 1)


def test_damerau_basic_ops():
    assert V.damerau_distance("abc", "abc") == 0
    assert V.damerau_distance("abc", "abd") == 1       # sub
    assert V.damerau_distance("abc", "ab") == 1        # delete
    assert V.damerau_distance("abc", "abcc") == 1      # insert
    assert V.damerau_distance("abc", "xyz") == 3
    assert not V.damerau_le("abc", "xyz", 1)


# ── Splice grammar guard ────────────────────────────────────────────────────────

def test_splice_dedups_article():
    nl = "members of the Avengers"
    s = nl.index("Avengers")
    out = V.splice(nl, s, s + len("Avengers"), "the Avengers team")
    assert out is not None
    assert "the the" not in out.lower()
    assert out == "members of the Avengers team"


def test_splice_a_an_agreement():
    nl = "a Lakers fan"
    out = V.splice(nl, 2, 8, "Anaheim club")  # 'a' before vowel-start -> 'an'
    assert out is not None and out.startswith("an Anaheim")


def test_splice_rejects_unrecoverable_doubling():
    # A new surface with internal word-doubling can't be cleaned -> None.
    out = V.splice("I like apples", 2, 6, "apples apples")
    assert out is None


# ── Validity checks ─────────────────────────────────────────────────────────────

def _vp():
    return InMemoryValueProvider({
        ("Person", "surname"): {"Hanson", "Hansen", "Moore"},
        ("Team", "name"): {"Los Angeles Lakers", "Los Angeles Clippers", "Boston Celtics"},
        ("Postcode", "code"): {"WN5", "NW5"},      # exact-collision pair
        ("Code", "v"): {"WN5", "NW6"},             # near (Damerau-1) but not equal
    })


def test_collision_rejected():
    ok, reason = V.check_validity("casing", "Hansen", "Hanson", "Person", "surname", _vp())
    assert not ok and reason == V.COLLISION


def test_typo_exact_collision_rejected():
    # WN5 -> NW5 transposition lands exactly on ANOTHER real value (the shipped bug).
    ok, reason = V.check_validity("typo", "NW5", "WN5", "Postcode", "code", _vp())
    assert not ok and reason == V.COLLISION


def test_typo_margin_rejects_near_other_value():
    # NW5 isn't itself a value of (Code, v), but NW6 sits within Damerau-1 of it.
    ok, reason = V.check_validity("typo", "NW5", "WN5", "Code", "v", _vp())
    assert not ok and reason == V.MARGIN


def test_partial_uniqueness():
    ok, _ = V.check_validity("partial", "Lakers", "Los Angeles Lakers", "Team", "name", _vp())
    assert ok
    # "Los Angeles" is contained in TWO values -> not unique
    ok2, reason2 = V.check_validity("partial", "Los Angeles", "Los Angeles Lakers",
                                    "Team", "name", _vp())
    assert not ok2 and reason2 == V.NOT_UNIQUE


def test_unchecked_without_provider():
    ok, reason = V.check_validity("typo", "Xyz", "Abc", None, None, None)
    assert ok and reason == V.UNCHECKED


# ── Augmenters ──────────────────────────────────────────────────────────────────

def test_casing_no_title_artifact():
    aug = CasingAugmenter()
    for seed in range(20):
        p = aug.apply("Night's Watch", _ctx(seed=seed))
        assert p is not None
        assert p.surface in ("night's watch", "NIGHT'S WATCH")
        assert "'S" not in p.surface or p.surface.isupper()


def test_typo_one_edit_first_char_preserved():
    aug = TypoAugmenter()
    seen_change = False
    for seed in range(50):
        p = aug.apply("Sacramento", _ctx(seed=seed))
        if p is None:
            continue
        seen_change = True
        assert p.surface != "Sacramento"
        assert p.surface[0] == "S"                       # word-initial preserved
        assert V.damerau_le("Sacramento", p.surface, 1)  # exactly one typo
    assert seen_change


def test_partial_keeps_distinctive_token():
    vp = _vp()
    ctx = _ctx(values=vp, label="Team", prop="name", seed=1)
    p = PartialNameAugmenter().apply("Los Angeles Lakers", ctx)
    assert p is not None and p.surface == "Lakers"


def test_alias_declines_on_synthetic_domain():
    # synthetic domain + no attested alias + no LLM -> decline (no hallucinated
    # "Wagner -> the Wagner Group")
    p = AliasAugmenter().apply("Wagner", _ctx(synthetic=True))
    assert p is None


class _FakeLLM:
    enabled = True
    def complete(self, prompt, *, system=None):
        return "Some Made-Up Name"


def test_alias_llm_declines_on_closed_set():
    # A small enumerable category (6 divisions) → LLM must NOT be asked to alias
    # it (it would swap siblings / hallucinate).
    vp = InMemoryValueProvider({("Division", "name"): {
        "Central Division", "Atlantic Division", "Pacific Division",
        "Southwest Division", "Northwest Division", "Southeast Division"}})
    ctx = AugContext(nl="x", rng=random.Random(0), llm=_FakeLLM(),
                     label="Division", prop="name", values=vp,
                     aliases=AliasProvider(graph=None))
    assert AliasAugmenter().apply("Central Division", ctx) is None


def test_alias_llm_fires_on_open_set():
    # A large open set (many players) → LLM alias fallback is allowed.
    vp = InMemoryValueProvider({("Player", "name"): frozenset(f"Player {i}" for i in range(100))})
    ctx = AugContext(nl="x", rng=random.Random(0), llm=_FakeLLM(),
                     label="Player", prop="name", values=vp,
                     aliases=AliasProvider(graph=None))
    p = AliasAugmenter().apply("Player 7", ctx)
    assert p is not None and p.source == "llm" and p.needs_verification


def test_alias_attested_is_replacement_not_scaffold():
    ap = AliasProvider(graph=None)  # curated only
    p = AliasAugmenter().apply("United Kingdom", _ctx(aliases=ap))
    assert p is not None
    assert "united kingdom" not in p.surface.lower()    # replacement, not scaffold
    assert p.needs_verification is False                # attested source


# ── Entity typing / extraction ──────────────────────────────────────────────────

@pytest.mark.parametrize("s,expected", [
    ("Tom Hanks", "name"),
    ("The Matrix", "name"),
    ("2020", "id"),
    ("6/08/2017", "date"),
    ("00:52", "time"),
    ("a@b.com", "email"),
    ("770-22-6561", "id"),
    ("WN5", "id"),
    ("BL5 2RN", "id"),
    ("COVID-19", "name"),
])
def test_classify_entity(s, expected):
    assert classify_entity(s) == expected


def test_extractor_filters_non_names_and_resolves_context():
    nl = "crimes on 6/08/2017 involving Hanson with postcode WN5"
    gold = ('MATCH (x:Person WHERE x.surname = "Hanson")-[:INVOLVED_IN]->'
            '(c:Crime {date: "6/08/2017"}) WHERE x.postcode = "WN5" RETURN c')
    spans = extract_entities(nl, gold, use_llm_fallback=False)
    surfaces = {s.surface for s in spans}
    assert "Hanson" in surfaces           # name kept
    assert "6/08/2017" not in surfaces    # date filtered
    assert "WN5" not in surfaces          # id/postcode filtered
    hanson = next(s for s in spans if s.surface == "Hanson")
    assert hanson.label == "Person" and hanson.prop == "surname"


# ── KB aliases (uses local simplekg if available) ───────────────────────────────

def test_kb_curated_abbrev():
    ap = AliasProvider(graph=None)
    forms = {f for f, _ in ap.abbrevs("United States of America")}
    assert "USA" in forms


@pytest.mark.skipif(
    not os.path.exists(os.path.expanduser("~/datasets/cypherbench/graphs/simplekg/nba_simplekg.json")),
    reason="nba simplekg not present",
)
def test_kb_simplekg_aliases_load():
    ap = AliasProvider(graph="nba")
    skg = ap._load_simplekg()
    assert len(skg) > 0   # nba has ~76% alias coverage


# ── Quota sampler convergence ───────────────────────────────────────────────────

def test_quota_sampler_converges_to_targets():
    weights = {"casing": 0.10, "typo": 0.225, "partial": 0.225,
               "abbrev": 0.225, "alias": 0.225}
    s = QuotaSampler(weights)
    rng = random.Random(0)
    elig = list(weights)
    for _ in range(2000):
        chosen = s.order(elig, rng)[0]   # always commit the top-deficit strategy
        s.commit(chosen)
    for k, target in s.weights.items():
        realized = s.counts[k] / s.total
        assert abs(realized - target) < 0.02, (k, realized, target)


# ── End-to-end pipeline (algorithmic only) ──────────────────────────────────────

def test_pipeline_produces_valid_single_edit():
    nl = "Who plays for the Los Angeles Lakers?"
    gold = "MATCH (t:Team {name: 'Los Angeles Lakers'})<-[:playsFor]-(p) RETURN p"
    vp = InMemoryValueProvider({("Team", "name"):
                                {"Los Angeles Lakers", "Boston Celtics"}})
    res = augment_nl(nl, gold, proportions={"casing": 1, "typo": 1, "partial": 1},
                     llm=None, rng=random.Random(3), graph="nba", values=vp)
    assert res is not None
    new_nl, meta = res
    assert len(meta["edits"]) == 1
    assert new_nl != nl
    assert not re.search(r"\b(\w+)\s+\1\b", new_nl, re.IGNORECASE)   # no doubling


def test_pipeline_drops_when_only_non_name_entities():
    nl = "crimes on 6/08/2017 at postcode WN5"
    gold = 'MATCH (c:Crime {date: "6/08/2017"}) WHERE c.postcode = "WN5" RETURN c'
    stats = __import__("collections").Counter()
    res = augment_nl(nl, gold, llm=None, rng=random.Random(1), graph="pole", stats=stats)
    assert res is None
    assert stats["drop:no_entity"] == 1


def test_row_rng_is_stable_and_id_dependent():
    a = row_rng(42, "cypherbench", "row-1").random()
    b = row_rng(42, "cypherbench", "row-1").random()
    c = row_rng(42, "cypherbench", "row-2").random()
    assert a == b and a != c
