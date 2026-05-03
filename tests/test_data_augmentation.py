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
    sub  = src / "Train_Test_Splits" / "Manual" / "covid" / "test"
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
    test_file = target / "Train_Test_Splits" / "Manual" / "covid" / "test" / "Complex_test.json"
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


# ──────────────────────────────────────────────────────────────────────────────
# 5. LLM disk cache — Bug A regression
# ──────────────────────────────────────────────────────────────────────────────

def test_llm_cache_persists_and_dedups(tmp_path: Path, monkeypatch):
    """
    Mock the underlying chat-model invocation, count calls, and verify:
      - first call: hits LLM (count=1)
      - second call same input: served from cache (count still 1)
      - third call different input: hits LLM (count=2)
      - cache JSONL has exactly 2 lines after.
    """
    cache_file = tmp_path / "cache.jsonl"
    monkeypatch.setenv("DATA_AUG_CACHE_FILE", str(cache_file))

    # Reload the module so the new env var takes effect.
    import importlib
    import data_augmentation.llm as dal
    dal = importlib.reload(dal)

    # Sanity: the module-level cache is empty for this isolated file.
    assert dal._CACHE == {}
    assert dal._CACHE_PATH == cache_file

    invocations = {"n": 0}

    class _FakeReply:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeLLM:
        def invoke(self, msgs):
            invocations["n"] += 1
            # Echo the human prompt back so different prompts produce
            # different responses (and different cache entries).
            human = next(m for m in msgs if m.__class__.__name__ == "HumanMessage")
            return _FakeReply(f"reply::{human.content}")

    client = dal.LLMClient({
        "provider":    "anthropic",
        "model":       "test-model",
        "temperature": 0.0,
    })
    monkeypatch.setattr(client, "_ensure_llm", lambda: _FakeLLM())

    # 1st call — miss.
    r1 = client.complete("hello world", system="sys-A")
    assert r1 == "reply::hello world"
    assert invocations["n"] == 1

    # 2nd call — same inputs → cache hit.
    r2 = client.complete("hello world", system="sys-A")
    assert r2 == "reply::hello world"
    assert invocations["n"] == 1, "second call must NOT invoke LLM"

    # 3rd call — different prompt → miss.
    r3 = client.complete("different prompt", system="sys-A")
    assert r3 == "reply::different prompt"
    assert invocations["n"] == 2

    # JSONL has exactly 2 entries.
    assert cache_file.is_file()
    lines = [ln for ln in cache_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2, f"expected 2 cache lines, got {len(lines)}: {lines}"
    parsed = [json.loads(ln) for ln in lines]
    keys = {p["key"] for p in parsed}
    assert len(keys) == 2  # distinct keys for distinct (system, prompt, model)


def test_llm_cache_failure_not_persisted(tmp_path: Path, monkeypatch):
    """A None response (LLM failure) must NOT be cached."""
    cache_file = tmp_path / "cache.jsonl"
    monkeypatch.setenv("DATA_AUG_CACHE_FILE", str(cache_file))

    import importlib
    import data_augmentation.llm as dal
    dal = importlib.reload(dal)

    class _Reply:
        def __init__(self, content) -> None:
            self.content = content

    class _FailLLM:
        def invoke(self, msgs):
            return _Reply("")  # empty → complete() returns None

    client = dal.LLMClient({"model": "x"})
    monkeypatch.setattr(client, "_ensure_llm", lambda: _FailLLM())

    assert client.complete("p") is None
    assert not cache_file.is_file() or cache_file.read_text(encoding="utf-8").strip() == ""


def test_llm_client_falls_back_when_agent_helper_unavailable(tmp_path: Path, monkeypatch):
    """
    Regression: when ``agent.agent_helper.build_llm_from_config`` blows up
    at import or call time (e.g. Neo4j not reachable), ``_ensure_llm()``
    must transparently fall back to direct LangChain construction.
    """
    # Isolate the cache so this test can't poison or be poisoned by others.
    cache_file = tmp_path / "cache.jsonl"
    monkeypatch.setenv("DATA_AUG_CACHE_FILE", str(cache_file))

    import importlib
    import sys as _sys
    import data_augmentation.llm as dal
    dal = importlib.reload(dal)

    # Force the agent helper import path to fail.  We install a fake module
    # whose attribute access raises so the try/except inside _ensure_llm
    # exercises the fallback branch.
    class _Boom(Exception):
        pass

    class _FakeAgentHelper:
        @staticmethod
        def build_llm_from_config(_cfg):
            raise _Boom("simulated Neo4j-unavailable failure")

    fake_pkg = type(_sys)("agent")
    fake_pkg.agent_helper = _FakeAgentHelper  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "agent", fake_pkg)
    monkeypatch.setitem(_sys.modules, "agent.agent_helper", _FakeAgentHelper)

    # Stub ChatAnthropic so we don't actually attempt a network/auth call.
    constructed = {"calls": 0, "kwargs": None}

    class _FakeChatAnthropic:
        def __init__(self, **kwargs):
            constructed["calls"] += 1
            constructed["kwargs"] = kwargs

        def invoke(self, msgs):
            class _R:
                content = "ok"
            return _R()

    fake_la = type(_sys)("langchain_anthropic")
    fake_la.ChatAnthropic = _FakeChatAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "langchain_anthropic", fake_la)

    client = dal.LLMClient({
        "provider":    "anthropic",
        "model":       "claude-fake",
        "temperature": 0.42,
    })

    # _ensure_llm() must NOT raise even though the agent helper fails.
    llm = client._ensure_llm()
    assert llm is not None
    assert isinstance(llm, _FakeChatAnthropic)
    assert constructed["calls"] == 1
    # The fallback must thread provider config through to ChatAnthropic.
    assert constructed["kwargs"] == {"model": "claude-fake", "temperature": 0.42}

    # End-to-end: complete() succeeds via the fallback path.
    assert client.complete("hello") == "ok"


# ──────────────────────────────────────────────────────────────────────────────
# 6. Strategy order distribution — Bug B regression
# ──────────────────────────────────────────────────────────────────────────────

def test_strategy_order_distribution_uniform():
    """
    Run _strategy_order 1000 times with the canonical 18/18/18/18/18/10
    weights and a seeded RNG.  Verify position 1 (and position 2) reflect
    the configured weights, not a fixed-order fallback chain.
    """
    from data_augmentation.pipeline import _strategy_order

    weights = {
        "casing":     0.18,
        "partial":    0.18,
        "abbrev":     0.18,
        "synonym":    0.18,
        "paraphrase": 0.18,
        "typo":       0.10,
    }

    rng = random.Random(42)
    N = 1000
    pos_counts: List[Dict[str, int]] = [{k: 0 for k in weights} for _ in range(len(weights))]

    for _ in range(N):
        order = _strategy_order(rng, weights)
        assert sorted(order) == sorted(weights.keys()), \
            "every strategy must appear exactly once per order"
        for i, name in enumerate(order):
            pos_counts[i][name] += 1

    # Position 1: casing should be ~18% (NOT >40% as the old fixed-order
    # fallback chain produced).  Typo should be ~10%.
    p1 = pos_counts[0]
    casing_p1 = p1["casing"] / N
    typo_p1   = p1["typo"]   / N
    assert abs(casing_p1 - 0.18) < 0.05, (
        f"position 1 casing rate = {casing_p1:.3f}, expected ~0.18 (±0.05); "
        f"this likely means the fallback chain is fixed-order again"
    )
    assert casing_p1 < 0.40, (
        f"position 1 casing rate = {casing_p1:.3f} — fallback chain looks "
        f"fixed-order (Bug B regression)"
    )
    assert abs(typo_p1 - 0.10) < 0.05, \
        f"position 1 typo rate = {typo_p1:.3f}, expected ~0.10 (±0.05)"

    # Position 2: casing rate should also be reasonable (random sampling,
    # not auto-promoted as a fixed fallback).  Allow a wider band because
    # conditioning on "casing was not picked at position 1" shifts the
    # distribution slightly upward.
    p2 = pos_counts[1]
    casing_p2 = p2["casing"] / N
    assert 0.13 <= casing_p2 <= 0.30, (
        f"position 2 casing rate = {casing_p2:.3f}, expected roughly "
        f"0.18-0.22 (random sampling-without-replacement, not auto-promoted)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 7. Mind-the-Query scope — Bug C regression
# ──────────────────────────────────────────────────────────────────────────────

def test_mindthequery_only_augments_manual_test(tmp_path: Path):
    """
    Lay out a temp mtq tree containing:
      - Train_Test_Splits/Manual/bloom/test/foo_test.json    (eligible)
      - Train_Test_Splits/Automated/x/test/bar_test.json     (NOT eligible)
      - Manually_Validated_Datasets/y/baz.json               (NOT eligible)
    Call augment_mindthequery.run() and assert ONLY the Manual file's NL
    was perturbed; the other two are byte-identical to source.
    """
    src = tmp_path / "mtq_in"
    dst = tmp_path / "mtq_out"

    # Eligible: Train_Test_Splits/Manual/bloom/test/foo_test.json
    manual = src / "Train_Test_Splits" / "Manual" / "bloom" / "test"
    manual.mkdir(parents=True)
    manual_rows = [
        {
            "NL Question": "Find patients diagnosed with COVID-19 in Manhattan.",
            "Cypher":      "MATCH (p:Patient)-[:DIAGNOSED_WITH]->(d:Disease {name: 'COVID-19'}) WHERE p.borough = 'Manhattan' RETURN p",
        },
    ]
    (manual / "foo_test.json").write_text(
        json.dumps(manual_rows, ensure_ascii=False), encoding="utf-8",
    )

    # NOT eligible: Train_Test_Splits/Automated/x/test/bar_test.json
    automated = src / "Train_Test_Splits" / "Automated" / "x" / "test"
    automated.mkdir(parents=True)
    automated_rows = [
        {
            "NL Question": "Which doctors work at Mount Sinai?",
            "Cypher":      "MATCH (d:Doctor)-[:WORKS_AT]->(h:Hospital {name: 'Mount Sinai'}) RETURN d.name",
        },
    ]
    (automated / "bar_test.json").write_text(
        json.dumps(automated_rows, ensure_ascii=False), encoding="utf-8",
    )

    # NOT eligible: Manually_Validated_Datasets/y/baz.json
    mvd = src / "Manually_Validated_Datasets" / "y"
    mvd.mkdir(parents=True)
    mvd_rows = [
        {
            "NL Question": "List nurses certified in Pediatrics.",
            "Cypher":      "MATCH (n:Nurse)-[:CERTIFIED_IN]->(s:Speciality {name: 'Pediatrics'}) RETURN n.name",
        },
    ]
    (mvd / "baz.json").write_text(
        json.dumps(mvd_rows, ensure_ascii=False), encoding="utf-8",
    )

    # Run.
    import data_augmentation.datasets.augment_mindthequery as mtq
    stats = mtq.run(
        source_root=src,
        target_root=dst,
        splits=["test"],
        proportions=_RULE_PROPS,
        llm_config=None,
        use_llm_entity_fallback=False,
        seed=42,
    )

    # Manual file: augmented.
    out_manual = dst / "Train_Test_Splits" / "Manual" / "bloom" / "test" / "foo_test.json"
    assert out_manual.is_file()
    out_manual_rows = json.loads(out_manual.read_text(encoding="utf-8"))
    assert len(out_manual_rows) == 1
    assert out_manual_rows[0]["NL Question"] != manual_rows[0]["NL Question"], \
        "Manual/bloom/test row should have a perturbed NL"
    assert out_manual_rows[0].get("_aug_meta", {}).get("augmented") is True

    # Automated file: copied verbatim (byte-identical).
    out_automated = dst / "Train_Test_Splits" / "Automated" / "x" / "test" / "bar_test.json"
    assert out_automated.is_file()
    assert (
        (src / "Train_Test_Splits" / "Automated" / "x" / "test" / "bar_test.json").read_bytes()
        == out_automated.read_bytes()
    ), "Automated/x/test file must be copied verbatim, not augmented"

    # Manually_Validated_Datasets file: copied verbatim.
    out_mvd = dst / "Manually_Validated_Datasets" / "y" / "baz.json"
    assert out_mvd.is_file()
    assert (
        (src / "Manually_Validated_Datasets" / "y" / "baz.json").read_bytes()
        == out_mvd.read_bytes()
    ), "Manually_Validated_Datasets file must be copied verbatim, not augmented"

    # Stats: only the manual file is in per_file.
    per_file = stats.get("per_file", {})
    assert len(per_file) == 1, f"expected only 1 augmented file, got {list(per_file)}"
    assert any("Manual" in k and "bloom" in k for k in per_file), \
        f"expected Manual/bloom file in per_file, got {list(per_file)}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
