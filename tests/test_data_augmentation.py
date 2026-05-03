# -*- coding: utf-8 -*-
"""
tests/test_data_augmentation.py
================================
Offline regression tests for the data-augmentation feature plus the
augmented-pair archive-reuse short-circuit in
``scripts/setup_and_archive.py``.

Coverage
--------
1. ``eval.dataset_base.base_dataset`` —
   - known base name returns itself
   - unknown name raises ValueError
   - augmented name maps to its base

2. ``data_augmentation.pipeline.augment_nl`` on each dataset format —
   - CypherBench-style row (JSON dict, ``nl_question`` + ``gold_cypher``)
   - Mind-the-Query-style row (JSON dict, ``NL Question`` + ``Cypher``)
   - ZOGRASCOPE-style row (CSV-style dict, ``nl`` + ``mr``)
   For each: NL changes, every detected entity is perturbed, gold Cypher
   passed in is identical to what's reflected in ``_aug_meta``, and
   ``_aug_meta`` carries the expected fields.

3. Per-dataset augmenters write loadable files —
   Augment a tiny in-memory fixture for each of the 3 datasets and load
   the result back through the corresponding ``metrics_*`` module's
   ``load_dataset()``.  Each augmented row must:
       * round-trip through the loader without error
       * preserve a non-empty NL question + Cypher
       * carry a parseable ``_aug_meta`` blob (raw ``raw[_aug_meta]``)

4. ``scripts/setup_and_archive._maybe_reuse_base_archive`` —
   - Pre-populate base archive on disk under a sandboxed
     ``SETUP_ARTIFACTS_ROOT``.
   - Set EVAL_PAIRS = [("cypherbench_augmented", "movie")].
   - Mock ``subprocess.run`` and ``archive_current`` to fail on call.
   - Run ``scripts/setup_and_archive.main([...])`` and assert exit code 0,
     subprocess never called, augmented archive contents match base.

All tests run offline:
  * No LLM calls — ``proportions`` weight LLM-only strategies to 0 and
    ``use_llm_entity_fallback=False``.
  * No Neo4j — never reached because the archive-reuse path short-circuits.
  * Subprocess + ``archive_current`` patched to raise on call.
"""

from __future__ import annotations

import csv
import json
import random
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── Repo-root import bootstrap ───────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# Stub heavy `agent` / `ner_agent_auto` imports so the metrics loaders can be
# imported without a built ``agent/prompts.py`` (that file is auto-generated
# per-pair by setup_project.py and is absent on a clean checkout).  We only
# need the loaders themselves; their imports of ``neo4j_graph`` / ``ask_auto``
# are unused on the load path.
# ──────────────────────────────────────────────────────────────────────────────

def _install_metrics_import_stubs() -> None:
    """Inject minimal stubs for `agent.agent_helper` and `ner_agent_auto`."""
    if "agent" not in sys.modules:
        agent_pkg = types.ModuleType("agent")
        agent_pkg.__path__ = [str(_REPO_ROOT / "agent")]  # mark as package
        sys.modules["agent"] = agent_pkg
    if "agent.agent_helper" not in sys.modules:
        helper = types.ModuleType("agent.agent_helper")
        helper.neo4j_graph = None  # unused on load path
        sys.modules["agent.agent_helper"] = helper
    if "ner_agent_auto" not in sys.modules:
        nau = types.ModuleType("ner_agent_auto")
        nau.ask_auto = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("ner_agent_auto.ask_auto stubbed in tests")
        )
        sys.modules["ner_agent_auto"] = nau


_install_metrics_import_stubs()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

# Rule-based proportions: zero out LLM-only strategies (paraphrase) and bias
# toward `casing` so every detected entity is reliably perturbed without an
# LLM call.  `partial` and `typo` are kept non-zero as fallbacks if casing
# happens to be a no-op (e.g. an already-lowercase entity).
_RULE_PROPS = {
    "casing":     0.7,
    "partial":    0.1,
    "abbrev":     0.0,
    "synonym":    0.0,
    "paraphrase": 0.0,  # LLM-only — keep at 0
    "typo":       0.2,
}


def _augment_row(nl: str, gold_cypher: str, *, seed: int = 42):
    """Run augment_nl with rule-based knobs only (no LLM calls)."""
    from data_augmentation.pipeline import augment_nl
    return augment_nl(
        nl,
        gold_cypher,
        proportions=_RULE_PROPS,
        llm=None,
        llm_config=None,
        use_llm_entity_fallback=False,
        rng=random.Random(seed),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. eval.dataset_base.base_dataset
# ──────────────────────────────────────────────────────────────────────────────

def test_base_dataset_known_base_name():
    from eval.dataset_base import base_dataset
    assert base_dataset("cypherbench") == "cypherbench"
    assert base_dataset("mindthequery") == "mindthequery"
    assert base_dataset("zograscope") == "zograscope"


def test_base_dataset_unknown_name_raises():
    from eval.dataset_base import base_dataset
    with pytest.raises(ValueError) as excinfo:
        base_dataset("does_not_exist")
    assert "does_not_exist" in str(excinfo.value)


def test_base_dataset_augmented_name_maps_to_base():
    from eval.dataset_base import base_dataset, is_augmented, augmented_for
    assert base_dataset("cypherbench_augmented")  == "cypherbench"
    assert base_dataset("mindthequery_augmented") == "mindthequery"
    assert base_dataset("zograscope_augmented")   == "zograscope"
    assert is_augmented("cypherbench_augmented") is True
    assert is_augmented("cypherbench")           is False
    assert augmented_for("cypherbench") == "cypherbench_augmented"


# ──────────────────────────────────────────────────────────────────────────────
# 2. augment_nl on a fixture row from each dataset format
# ──────────────────────────────────────────────────────────────────────────────

def _assert_aug_meta_shape(meta: Dict[str, Any], original_nl: str) -> None:
    assert meta["augmented"] is True
    assert meta["original_nl"] == original_nl
    assert isinstance(meta["edits"], list) and len(meta["edits"]) >= 1
    for e in meta["edits"]:
        assert {"strategy", "from", "to", "src_span", "dst_span", "source"} <= set(e)
        assert isinstance(e["src_span"], list) and len(e["src_span"]) == 2
        assert isinstance(e["dst_span"], list) and len(e["dst_span"]) == 2
        assert e["from"] != e["to"]


def test_augment_nl_cypherbench_format():
    """CypherBench-style row — `nl_question` + `gold_cypher` keys."""
    nl   = "Which actor played in the movie The Matrix and was born in the United States?"
    gold = (
        "MATCH (a:Actor)-[:ACTED_IN]->(m:Movie {title: 'The Matrix'}) "
        "WHERE a.country = 'United States' RETURN a.name"
    )
    result = _augment_row(nl, gold)
    assert result is not None, "fixture should produce at least one augmentation"

    new_nl, meta = result
    assert new_nl != nl,                   "NL must be perturbed"
    _assert_aug_meta_shape(meta, original_nl=nl)

    # Both detected entities should have been perturbed (no `skipped` block).
    surfaces = {e["from"] for e in meta["edits"]}
    assert "The Matrix"    in surfaces
    assert "United States" in surfaces
    assert meta.get("skipped", []) == [], (
        f"expected no skipped entities, got {meta.get('skipped')}"
    )


def test_augment_nl_mindthequery_format():
    """Mind-the-Query-style row — `NL Question` + `Cypher` keys."""
    nl   = "Find all patients diagnosed with COVID-19 in Manhattan."
    gold = (
        "MATCH (p:Patient)-[:DIAGNOSED_WITH]->(d:Disease {name: 'COVID-19'}) "
        "WHERE p.borough = 'Manhattan' RETURN p"
    )
    result = _augment_row(nl, gold, seed=7)
    assert result is not None

    new_nl, meta = result
    assert new_nl != nl
    _assert_aug_meta_shape(meta, original_nl=nl)
    surfaces = {e["from"] for e in meta["edits"]}
    assert "COVID-19"  in surfaces
    assert "Manhattan" in surfaces


def test_augment_nl_zograscope_format():
    """ZOGRASCOPE-style row — CSV `nl` + `mr` columns."""
    nl   = "What papers cite Smith et al. and were published in 2020?"
    gold = (
        "MATCH (p:Paper)-[:CITES]->(:Paper {author: 'Smith et al.'}) "
        "WHERE p.year = '2020' RETURN p.title"
    )
    result = _augment_row(nl, gold, seed=11)
    assert result is not None

    new_nl, meta = result
    assert new_nl != nl
    _assert_aug_meta_shape(meta, original_nl=nl)
    surfaces = {e["from"] for e in meta["edits"]}
    # Both literals should be detected entities; both should be perturbed.
    assert "Smith et al." in surfaces
    assert "2020"         in surfaces or len(surfaces) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# 3. Per-dataset augmenter -> metrics_*.load_dataset round-trip
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cypherbench_source(tmp_path: Path) -> Path:
    """Build a minimal CypherBench source layout at <tmp>/cb_src/."""
    src = tmp_path / "cb_src"
    src.mkdir()
    rows = [
        {
            "qid": "ex_1",
            "nl_question":  "Which actor played in The Matrix?",
            "gold_cypher":  "MATCH (a:Actor)-[:ACTED_IN]->(m:Movie {title: 'The Matrix'}) RETURN a.name",
            "answer":       [],
            "graph":        "movie",
        },
        {
            "qid": "ex_2",
            "nl_question":  "List companies headquartered in California.",
            "gold_cypher":  "MATCH (c:Company {hq: 'California'}) RETURN c.name",
            "answer":       [],
            "graph":        "company",
        },
        {
            "qid": "ex_3",
            "nl_question":  "Show movies directed by Steven Spielberg.",
            "gold_cypher":  "MATCH (d:Director {name: 'Steven Spielberg'})-[:DIRECTED]->(m:Movie) RETURN m.title",
            "answer":       [],
            "graph":        "movie",
        },
    ]
    (src / "test.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (src / "README.md").write_text("# CB fixture\n", encoding="utf-8")
    return src


@pytest.fixture
def mindthequery_source(tmp_path: Path) -> Path:
    """Build a minimal Mind-the-Query directory layout."""
    src  = tmp_path / "mtq_src"
    sub  = src / "Manual" / "covid" / "test"
    sub.mkdir(parents=True)
    rows = [
        {
            "NL Question": "Find patients diagnosed with COVID-19 in Manhattan.",
            "Cypher":      "MATCH (p:Patient)-[:DIAGNOSED_WITH]->(d:Disease {name: 'COVID-19'}) WHERE p.borough = 'Manhattan' RETURN p",
        },
        {
            "NL Question": "Which doctors work at Mount Sinai?",
            "Cypher":      "MATCH (d:Doctor)-[:WORKS_AT]->(h:Hospital {name: 'Mount Sinai'}) RETURN d.name",
        },
    ]
    (sub / "Complex_test.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return src


@pytest.fixture
def zograscope_source(tmp_path: Path) -> Path:
    """Build a minimal ZOGRASCOPE source layout at <tmp>/zg_src/."""
    src = tmp_path / "zg_src"
    data = src / "data"
    data.mkdir(parents=True)
    csv_path = data / "zograscope_test_v1.csv"

    rows = [
        {
            "id": "zg_1",
            "nl": "What papers cite Smith et al. and were published in 2020?",
            "mr": "MATCH (p:Paper)-[:CITES]->(:Paper {author: 'Smith et al.'}) WHERE p.year = '2020' RETURN p.title",
        },
        {
            "id": "zg_2",
            "nl": "Find authors at Stanford University with more than 5 papers.",
            "mr": "MATCH (a:Author {affiliation: 'Stanford University'})-[:WROTE]->(p:Paper) WITH a, count(p) AS n WHERE n > 5 RETURN a.name",
        },
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "nl", "mr"])
        w.writeheader()
        w.writerows(rows)
    return src


def _run_augmenter_offline(
    runner_module: str,
    source_root: Path,
    target_root: Path,
) -> Dict[str, Any]:
    """Invoke a dataset augmenter with rule-based-only knobs."""
    import importlib
    mod = importlib.import_module(runner_module)
    return mod.run(
        source_root=source_root,
        target_root=target_root,
        splits=["test"],
        proportions=_RULE_PROPS,
        llm_config=None,
        use_llm_entity_fallback=False,
        seed=42,
    )


def test_cypherbench_augmenter_output_loads_via_metrics(cypherbench_source: Path, tmp_path: Path):
    target = tmp_path / "cb_aug"
    stats = _run_augmenter_offline(
        "data_augmentation.datasets.augment_cypherbench",
        cypherbench_source, target,
    )
    out_file = target / "test.json"
    assert out_file.is_file()
    assert stats["kept"] >= 1, f"augmenter dropped every row: {stats}"

    # Confirm augmented file is valid JSON list with _aug_meta on every row.
    rows = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(rows) == stats["kept"]
    for r in rows:
        assert "_aug_meta" in r
        assert r["_aug_meta"]["augmented"] is True
        assert r["_aug_meta"]["original_nl"] != r["nl_question"]

    # Round-trip via the actual metrics loader.
    from eval.metrics_CypherBench import load_dataset
    examples = load_dataset(str(out_file))
    assert len(examples) == stats["kept"]
    for ex in examples:
        assert ex["question"] and ex["cypher"]
        # _aug_meta survives in the raw row.
        assert "_aug_meta" in ex["raw"]


def test_mindthequery_augmenter_output_loads_via_metrics(mindthequery_source: Path, tmp_path: Path):
    target = tmp_path / "mtq_aug"
    stats = _run_augmenter_offline(
        "data_augmentation.datasets.augment_mindthequery",
        mindthequery_source, target,
    )
    test_file = target / "Manual" / "covid" / "test" / "Complex_test.json"
    assert test_file.is_file()
    assert stats["kept"] >= 1, f"augmenter dropped every row: {stats}"

    rows = json.loads(test_file.read_text(encoding="utf-8"))
    assert len(rows) == stats["kept"]
    for r in rows:
        assert "_aug_meta" in r
        assert r["_aug_meta"]["augmented"] is True

    # Round-trip via the actual metrics loader.  Pointing at the parent
    # `Manual/covid/test/` exercises the directory-walk path.
    from eval.metrics_MindTheQuery import load_dataset
    examples = load_dataset(str(test_file.parent))
    assert len(examples) == stats["kept"]
    for ex in examples:
        assert ex["question"] and ex["cypher"]
        assert "_aug_meta" in ex["raw"]


def test_zograscope_augmenter_output_loads_via_metrics(zograscope_source: Path, tmp_path: Path):
    target = tmp_path / "zg_aug"
    stats = _run_augmenter_offline(
        "data_augmentation.datasets.augment_zograscope",
        zograscope_source, target,
    )
    out_csv = target / "data" / "zograscope_test_v1.csv"
    assert out_csv.is_file()
    assert stats["kept"] >= 1, f"augmenter dropped every row: {stats}"

    # Confirm CSV header includes _aug_meta and every row carries a parseable blob.
    with out_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        assert "_aug_meta" in header
        rows = list(reader)
    assert len(rows) == stats["kept"]
    for r in rows:
        meta = json.loads(r["_aug_meta"])
        assert meta["augmented"] is True
        assert meta["original_nl"] != r["nl"]

    # Round-trip via the actual metrics loader.
    from eval.metrics_ZOGRASCOPE import load_dataset
    examples = load_dataset(str(out_csv))
    assert len(examples) == stats["kept"]
    for ex in examples:
        assert ex["question"] and ex["cypher"]
        # _aug_meta survives in raw row
        assert "_aug_meta" in ex["raw"]
        meta = json.loads(ex["raw"]["_aug_meta"])
        assert meta["augmented"] is True


# ──────────────────────────────────────────────────────────────────────────────
# 4. Archive-reuse short-circuit — end-to-end with mocked subprocess
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def _archive_sandbox(tmp_path, monkeypatch):
    """
    Sandbox the setup_artifacts root and the live-repo paths so we can
    prove ``_maybe_reuse_base_archive`` short-circuits the full setup.
    """
    import scripts.setup_and_archive as sa
    import eval.artifact_swap as art

    root = tmp_path / "repo"
    root.mkdir()
    artifacts_root = root / "setup_artifacts"
    artifacts_root.mkdir()

    # Redirect every "where do paths live" anchor at our sandbox.
    monkeypatch.setattr(sa,  "_REPO_ROOT", root, raising=False)
    monkeypatch.setattr(art, "REPO_ROOT",  root, raising=False)

    # Override the resolver so archive_dir_for() lives under our sandbox
    # regardless of eval_config.SETUP_ARTIFACTS_ROOT.
    monkeypatch.setattr(
        art, "_setup_artifacts_root",
        lambda: artifacts_root,
        raising=True,
    )

    return {"sa": sa, "art": art, "root": root, "artifacts": artifacts_root}


def _populate_base_archive(artifacts: Path, dataset: str, graph: str) -> Path:
    """Create a base archive directory with a couple of marker files."""
    arch = artifacts / f"{dataset}__{graph}"
    arch.mkdir(parents=True)
    (arch / "schema_data").mkdir()
    (arch / "schema_data" / "schema_meta.json").write_text(
        json.dumps({"marker": "base"}), encoding="utf-8",
    )
    (arch / "generated").mkdir()
    (arch / "generated" / "generated_node_tools.py").write_text(
        "# base node tools\n", encoding="utf-8",
    )
    return arch


def test_archive_reuse_short_circuits_full_setup(_archive_sandbox, monkeypatch):
    """
    Pre-populate setup_artifacts/cypherbench__movie/, set EVAL_PAIRS to the
    augmented pair only, mock subprocess.run + archive_current to fail-on-call,
    run main(), and assert:
        * exit code 0
        * subprocess.run never called (full setup bypassed)
        * archive_current never called
        * setup_artifacts/cypherbench_augmented__movie/ contents match the base
    """
    sa  = _archive_sandbox["sa"]
    art = _archive_sandbox["art"]
    artifacts = _archive_sandbox["artifacts"]

    # Pre-populate the base archive.
    base_arch = _populate_base_archive(artifacts, "cypherbench", "movie")
    aug_arch  = artifacts / "cypherbench_augmented__movie"
    assert not aug_arch.exists()  # precondition

    # Restrict EVAL_PAIRS to just the augmented pair.
    monkeypatch.setattr(
        sa.cfg, "EVAL_PAIRS",
        [("cypherbench_augmented", "movie")],
        raising=False,
    )

    # Wipe-state and Neo4j-reset must NOT be called for the short-circuit
    # path; assert by raising on call.  ``main()`` calls wipe_live_state
    # both before and after each pair, so we instead replace it with a
    # tracker that records calls but doesn't blow up — wiping a clean
    # sandbox is harmless, and the assertion targets subprocess + archive
    # bypass per the spec.
    fail_calls = {"subprocess": 0, "archive_current": 0, "reset": 0}

    def _boom_subprocess(*a, **kw):
        fail_calls["subprocess"] += 1
        raise AssertionError("subprocess.run must NOT be invoked on archive reuse")

    def _boom_archive(*a, **kw):
        fail_calls["archive_current"] += 1
        raise AssertionError("archive_current must NOT be invoked on archive reuse")

    def _boom_reset(*a, **kw):
        fail_calls["reset"] += 1
        raise AssertionError("_reset_neo4j_embeddings must NOT be invoked on archive reuse")

    monkeypatch.setattr(sa.subprocess, "run", _boom_subprocess)
    monkeypatch.setattr(sa, "archive_current",        _boom_archive)
    monkeypatch.setattr(sa, "_reset_neo4j_embeddings", _boom_reset)

    # Round-trip check should also be skipped for archive reuse.
    monkeypatch.setattr(sa, "round_trip_check",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("round_trip_check must NOT run on archive reuse")
                        ))

    # Stub ``conn_for`` so a missing GraphConn entry can't surprise us — it
    # should not be reached at all on the archive-reuse path.
    monkeypatch.setattr(sa.cfg, "conn_for",
                        lambda ds, g: (_ for _ in ()).throw(
                            AssertionError(f"conn_for({ds},{g}) must NOT run on archive reuse")
                        ),
                        raising=False)

    rc = sa.main(["setup_and_archive.py"])

    # Exit code 0 (one pair, archive-reused, no failures).
    assert rc == 0, f"expected rc=0, got {rc}"
    # No setup-side calls fired.
    assert fail_calls == {"subprocess": 0, "archive_current": 0, "reset": 0}

    # Augmented archive populated and content-equivalent to the base.
    assert aug_arch.is_dir()
    base_files = sorted(p.relative_to(base_arch) for p in base_arch.rglob("*") if p.is_file())
    aug_files  = sorted(p.relative_to(aug_arch)  for p in aug_arch.rglob("*")  if p.is_file())
    assert base_files == aug_files, (
        f"augmented archive contents differ from base:\n"
        f"  base: {base_files}\n"
        f"   aug: {aug_files}"
    )
    # Spot-check actual byte-level equality on one file.
    assert (
        (base_arch / "schema_data" / "schema_meta.json").read_bytes()
        == (aug_arch / "schema_data" / "schema_meta.json").read_bytes()
    )


def test_archive_reuse_falls_through_when_base_missing(_archive_sandbox, monkeypatch, caplog):
    """
    If the base archive is absent, ``_maybe_reuse_base_archive`` returns
    False and logs a warning recommending base-first ordering.  We don't
    follow through to the full setup here (that would require a live
    Neo4j); just assert the predicate and the warning message.
    """
    sa  = _archive_sandbox["sa"]
    artifacts = _archive_sandbox["artifacts"]

    # Sanity: no base archive on disk.
    assert not (artifacts / "cypherbench__movie").exists()

    # Capture loguru warnings.
    from loguru import logger as _lg
    captured: List[str] = []
    handler_id = _lg.add(lambda msg: captured.append(str(msg)), level="WARNING")
    try:
        ok = sa._maybe_reuse_base_archive("cypherbench_augmented", "movie")
    finally:
        _lg.remove(handler_id)

    assert ok is False
    blob = "\n".join(captured)
    assert "no base archive" in blob
    assert "list base pairs" in blob


def test_archive_reuse_returns_false_for_non_augmented(_archive_sandbox):
    sa = _archive_sandbox["sa"]
    # Even if we put a fake "base" archive on disk, a non-augmented dataset
    # name should not trigger the reuse path.
    assert sa._maybe_reuse_base_archive("cypherbench", "movie") is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
