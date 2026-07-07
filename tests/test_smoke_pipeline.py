#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_smoke_pipeline.py
============================
Pre-flight smoke test for the per-graph eval harness.

What this exercises
-------------------
* Building a temporary ``eval_config.py`` and pointing the harness at it.
* Spawning ``eval_run.py`` which subprocess-launches ``eval._worker``
  per (dataset, graph) pair.
* Each worker runs ``evaluate_dataset`` with ``graph_filter`` set, which
  exercises the per-example graph-routing change in all three metrics
  modules.
* ``ner_agent_auto.ask_auto`` and ``agent.agent_helper.neo4j_graph`` are
  installed in :data:`sys.modules` by a generated ``sitecustomize.py``
  loaded via ``PYTHONPATH``.  ``ask_auto`` is a fixed stub; the
  ``neo4j_graph`` is a real ``langchain_neo4j.Neo4jGraph`` pointed at
  the local Neo4j given via the ``TEST_NEO4J_*`` env vars, so EA / PSJS
  exercise the full Neo4j round-trip with no LLM calls.
* ``eval_aggregate.py`` is then run against the same ``OUT_DIR`` and
  asserted to print a coherent table.

Test-config injection mechanism
-------------------------------
The harness imports ``eval_config`` as a regular top-level module.  When
Python launches ``eval_run.py`` as a script, it inserts the script's
directory (the repo root) at ``sys.path[0]`` — ahead of ``PYTHONPATH``.
That means PYTHONPATH-shadowing alone cannot redirect ``import
eval_config`` to a temp module: the production ``eval_config.py`` at
the repo root always wins.

The actual injection therefore happens in two layers:

1.  **Primary mechanism — pre-populating ``sys.modules``.**  We write a
    temp ``eval_config.py`` to ``cfg_dir`` and pass its path via the
    ``SMOKE_TEST_EVAL_CONFIG`` environment variable.  The generated
    ``sitecustomize.py`` (loaded by Python's ``site`` machinery before
    any user code) reads that env var, executes the temp module via
    ``importlib.util.spec_from_file_location`` + ``exec_module``, and
    installs the result as ``sys.modules["eval_config"]`` *before*
    ``eval_run.py`` ever runs its ``import eval_config`` line.  The
    subsequent ``import`` is a cache hit and never touches ``sys.path``.

2.  **Defense-in-depth — PYTHONPATH ordering.**  ``cfg_dir`` is also
    prepended to ``PYTHONPATH`` (``cfg_dir : rig_dir : REPO_ROOT``).
    This is not relied on for correctness — it only serves as a
    fallback if ``sitecustomize`` ever fails to load (e.g. interpreter
    started with ``-S``).

Both mechanisms were chosen over in-process ``unittest.mock.patch``
because subprocesses don't inherit in-process patches, and the
``sys.modules`` approach is more transparent than monkey-patching
``importlib`` machinery from inside the test.

Required env vars
-----------------
``TEST_NEO4J_URI`` / ``TEST_NEO4J_USER`` / ``TEST_NEO4J_PASSWORD``
(``TEST_NEO4J_DATABASE`` optional, default ``"neo4j"``).  If any
required var is unset the tests skip with a message telling the user
how to point the test at their local Neo4j.

The smoke test never falls back to ``eval_config.GRAPH_CONNS`` — it
must be safe to run on a clean checkout with no production setup.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


# ──────────────────────────────────────────────────────────────────────────────
# 1. Local-Neo4j env-var fixture (skip the suite cleanly if missing)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def local_neo4j() -> Dict[str, str]:
    """
    Read the ``TEST_NEO4J_*`` env vars; skip the entire module if any of
    URI / user / password is missing.
    """
    uri      = os.environ.get("TEST_NEO4J_URI")
    user     = os.environ.get("TEST_NEO4J_USER")
    password = os.environ.get("TEST_NEO4J_PASSWORD")
    database = os.environ.get("TEST_NEO4J_DATABASE", "neo4j")
    if not (uri and user and password):
        pytest.skip(
            "Smoke test requires a local Neo4j. Set TEST_NEO4J_URI, "
            "TEST_NEO4J_USER, TEST_NEO4J_PASSWORD (and optionally "
            "TEST_NEO4J_DATABASE) and re-run.  Example:\n"
            "    export TEST_NEO4J_URI=bolt://localhost:7687\n"
            "    export TEST_NEO4J_USER=neo4j\n"
            "    export TEST_NEO4J_PASSWORD=...\n"
            "    pytest tests/test_smoke_pipeline.py"
        )
    return {"uri": uri, "user": user, "password": password, "database": database}


# ──────────────────────────────────────────────────────────────────────────────
# 2. Generated test-rig files  (sitecustomize.py + tiny fixtures)
# ──────────────────────────────────────────────────────────────────────────────

# ``sitecustomize.py`` is loaded by Python's ``site`` machinery very early
# in interpreter startup — before any user-code import — when its
# directory is on ``sys.path``.  We use it to install stub modules in
# ``sys.modules`` so the metrics modules' ``from ner_agent_auto import
# ask_auto`` and ``from agent.agent_helper import neo4j_graph`` resolve
# against our test stubs instead of the heavy production modules.
_SITECUSTOMIZE_TEMPLATE = textwrap.dedent("""\
    # Auto-generated by tests/test_smoke_pipeline.py — do not edit.
    import os
    import sys
    import types

    # ── 0. Pre-load the temp `eval_config` from SMOKE_TEST_EVAL_CONFIG so
    #      that `import eval_config` from eval_run.py / eval_aggregate.py
    #      finds our temp module instead of the production one at the repo
    #      root.  Python inserts the script's dir at sys.path[0] when
    #      launched as a script, ahead of PYTHONPATH, so PYTHONPATH alone
    #      isn't enough — we have to populate sys.modules directly. ──────
    import importlib.util
    _cfg_path = os.environ.get("SMOKE_TEST_EVAL_CONFIG")
    if _cfg_path:
        _spec = importlib.util.spec_from_file_location("eval_config", _cfg_path)
        _mod = importlib.util.module_from_spec(_spec)
        # Register in sys.modules *before* exec_module so decorators that
        # introspect sys.modules during class creation (e.g. @dataclass,
        # which calls sys.modules[cls.__module__].__dict__ to resolve
        # forward refs) see the partially-initialised module.
        sys.modules["eval_config"] = _mod
        _spec.loader.exec_module(_mod)

    # ── 1. Stub `ner_agent_auto` so the metrics modules don't pull in
    #      LangChain / FAISS / the real agent.  Returns a fixed Cypher
    #      that runs against any non-empty Neo4j database. ──────────────
    _stub_nm = types.ModuleType("ner_agent_auto")

    def ask_auto(prompt, top_k=None, verbose=False, mode=None):
        return {
            "cypher": "MATCH (n) RETURN count(n) AS c",
            "context": [{"c": 1}],
            "entities": "",
            "mode": "no_ner",
        }

    _stub_nm.ask_auto = ask_auto
    sys.modules["ner_agent_auto"] = _stub_nm

    # ── 2. Stub `agent` and `agent.agent_helper` so the metrics modules'
    #      `from agent.agent_helper import neo4j_graph` finds our real
    #      Neo4jGraph pointed at the local test instance, without
    #      triggering agent_helper.py's heavy LLM-client construction. ──
    _stub_agent_pkg = types.ModuleType("agent")
    _stub_agent_pkg.__path__ = []   # mark as package
    sys.modules.setdefault("agent", _stub_agent_pkg)

    _stub_ah = types.ModuleType("agent.agent_helper")
    try:
        from langchain_neo4j import Neo4jGraph
        _stub_ah.neo4j_graph = Neo4jGraph(
            url=os.environ.get("EVAL_NEO4J_URI") or os.environ["NEO4J_URI"],
            username=os.environ.get("EVAL_NEO4J_USER") or os.environ["NEO4J_USERNAME"],
            password=os.environ.get("EVAL_NEO4J_PASSWORD") or os.environ["NEO4J_PASSWORD"],
            database=(
                os.environ.get("EVAL_NEO4J_DATABASE")
                or os.environ.get("NEO4J_DATABASE", "neo4j")
            ),
        )
    except Exception as exc:    # pragma: no cover — bubble up cleanly
        # Defer the failure: tests will see it when neo4j_graph.query
        # is called.  This way a Neo4j DNS hiccup at sitecustomize time
        # doesn't crash the interpreter before pytest even starts.
        class _BrokenGraph:
            def __init__(self, exc):
                self._exc = exc
            def query(self, *_a, **_kw):
                raise RuntimeError(f"test Neo4j unavailable: {self._exc!r}")
        _stub_ah.neo4j_graph = _BrokenGraph(exc)

    sys.modules["agent.agent_helper"] = _stub_ah
""")


def _write_sitecustomize(rig_dir: Path) -> None:
    rig_dir.mkdir(parents=True, exist_ok=True)
    (rig_dir / "sitecustomize.py").write_text(_SITECUSTOMIZE_TEMPLATE, encoding="utf-8")


# ── Fixture writers ───────────────────────────────────────────────────────────

def _write_cypherbench_fixture(path: Path, graph: str) -> None:
    """Write 3 examples in the schema consumed by metrics_CypherBench.load_dataset."""
    examples = [
        {
            "qid":         f"cb_smoke_{i}",
            "nl_question": f"smoke question {i}",
            "gold_cypher": "MATCH (n) RETURN count(n) AS c",
            "graph":       graph,
        }
        for i in range(3)
    ]
    with path.open("w", encoding="utf-8") as fh:
        for ex in examples:
            fh.write(json.dumps(ex) + "\n")


def _write_mindthequery_fixture(path: Path, graph: str) -> None:
    """
    Write a 3-example JSON array in Mind-the-Query's native schema (with
    spaces / capitalisation preserved as the upstream loader expects).
    """
    examples = [
        {
            "id":             i,
            "unique_id":      f"mtq_smoke_{i}",
            "NL Question":    f"smoke question {i}",
            "Cypher":         "MATCH (n) RETURN count(n) AS c",
            "result [0/1]":   1,
            "logical [0/1]":  1,
            "source_dataset": graph,
        }
        for i in range(3)
    ]
    path.write_text(json.dumps(examples), encoding="utf-8")


def _write_zograscope_fixture(path: Path) -> None:
    """Write a 3-row CSV in ZOGRASCOPE's native format."""
    cols = ["id", "nl", "mr"]
    rows = [
        [f"zg_smoke_{i}", f"smoke question {i}", "MATCH (n) RETURN count(n) AS c"]
        for i in range(3)
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Eval-config writer
# ──────────────────────────────────────────────────────────────────────────────

def _write_test_eval_config(
    cfg_dir: Path,
    *,
    pairs:           List[tuple[str, str]],
    cypherbench:     Path,
    mindthequery:    Path,
    zograscope:      Path,
    out_dir:         Path,
    setup_artifacts: Path,
    neo4j:           Dict[str, str],
) -> None:
    """
    Render a temporary ``eval_config.py`` whose layout matches the real
    one but pre-populates GRAPH_CONNS / EVAL_PAIRS for the test pairs
    and points each dataset path at the in-tmp fixture.
    """
    # Render conns/pairs as already-correctly-indented lines to drop into
    # the `GRAPH_CONNS = {{ ... }}` / `EVAL_PAIRS = [ ... ]` literals.
    # We deliberately do *not* use textwrap.dedent here: dedent strips
    # the minimum common leading whitespace, and join separators with a
    # different indent than the surrounding template caused dedent to
    # produce a syntactically broken module.
    conn_lines = ",\n    ".join(
        f"{p!r}: GraphConn(uri={neo4j['uri']!r}, user={neo4j['user']!r}, "
        f"password={neo4j['password']!r}, database={neo4j['database']!r})"
        for p in pairs
    )
    pair_lines = ",\n    ".join(repr(p) for p in pairs)

    body = (
        f"# Auto-generated by tests/test_smoke_pipeline.py — do not edit.\n"
        f"from __future__ import annotations\n"
        f"from dataclasses import dataclass\n"
        f"\n"
        f"@dataclass\n"
        f"class GraphConn:\n"
        f"    uri: str\n"
        f"    user: str\n"
        f"    password: str\n"
        f'    database: str = "neo4j"\n'
        f"\n"
        f"GRAPH_CONNS = {{\n"
        f"    {conn_lines}\n"
        f"}}\n"
        f"\n"
        f"EVAL_PAIRS = [\n"
        f"    {pair_lines}\n"
        f"]\n"
        f"\n"
        f"CYPHERBENCH_PATH  = {str(cypherbench)!r}\n"
        f"MINDTHEQUERY_PATH = {str(mindthequery)!r}\n"
        f"ZOGRASCOPE_PATH   = {str(zograscope)!r}\n"
        f"\n"
        f"OUT_DIR              = {str(out_dir)!r}\n"
        f"SETUP_ARTIFACTS_ROOT = {str(setup_artifacts)!r}\n"
        f"\n"
        f"LIMIT   = None\n"
        f"VERBOSE = False\n"
        f"\n"
        f"def conn_for(dataset, graph):\n"
        f"    try:\n"
        f"        return GRAPH_CONNS[(dataset, graph)]\n"
        f"    except KeyError as exc:\n"
        f"        raise KeyError(\n"
        f'            f"No GraphConn for ({{dataset!r}}, {{graph!r}}); "\n'
        f'            f\"available={{sorted(GRAPH_CONNS.keys())}}\"\n'
        f"        ) from exc\n"
    )
    (cfg_dir / "eval_config.py").write_text(body, encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# 4. Subprocess runners
# ──────────────────────────────────────────────────────────────────────────────

def _make_subprocess_env(rig_dir: Path, cfg_dir: Path) -> dict[str, str]:
    """
    Build the env dict for invoking ``eval_run.py`` / ``eval_aggregate.py``:

    * ``EVAL_SKIP_SWAP=1`` so artifact_swap.swap_in is a no-op.
    * ``PYTHONPATH = cfg_dir : rig_dir : REPO_ROOT : <existing>`` so
      ``import eval_config`` resolves to the temp config and
      ``sitecustomize`` from rig_dir is auto-loaded.
    """
    env = dict(os.environ)
    env["EVAL_SKIP_SWAP"] = "1"
    env["SMOKE_TEST_EVAL_CONFIG"] = str(cfg_dir / "eval_config.py")

    extra = os.pathsep.join([str(cfg_dir), str(rig_dir), str(REPO_ROOT)])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (extra + os.pathsep + existing) if existing else extra
    return env


def _run_eval(rig_dir: Path, cfg_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "eval_run.py")],
        env=_make_subprocess_env(rig_dir, cfg_dir),
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_aggregate(rig_dir: Path, cfg_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "eval_aggregate.py")],
        env=_make_subprocess_env(rig_dir, cfg_dir),
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 5. Assertions
# ──────────────────────────────────────────────────────────────────────────────

_REQUIRED_SUMMARY_KEYS = {
    "dataset", "n", "n_scored", "n_errors",
    "ea", "em", "psjs", "by_difficulty", "elapsed_sec",
}


def _assert_per_pair_outputs(
    out_dir: Path,
    dataset: str,
    graph:   str,
) -> List[Dict[str, Any]]:
    """Validate the pair's (timestamped) run dir exists and its
    ``records.jsonl`` + ``summary.json`` parse.

    Resolves the NEWEST run dir for the pair via ``eval_paths`` regardless of
    the method segment (the rig leaves METHOD at eval_run's default), so the
    assertion tracks the canonical layout instead of hardcoding it."""
    sys.path.insert(0, str(REPO_ROOT))
    import eval_paths

    cands = []
    for d in out_dir.iterdir():
        parsed = eval_paths.parse_run_dir_stamped(d)
        if parsed and parsed[0] == dataset and parsed[1] == graph and d.is_dir():
            cands.append((parsed[3], d))
    assert cands, f"no run dir for {dataset}__{graph} under {out_dir}"
    run_dir = max(cands)[1]
    records_path = run_dir / "records.jsonl"
    summary_path = run_dir / "summary.json"
    assert records_path.is_file(), f"missing records file: {records_path}"
    assert summary_path.is_file(), f"missing summary file: {summary_path}"

    records: List[Dict[str, Any]] = []
    with records_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    assert len(records) == 3, (
        f"{dataset}__{graph}: expected 3 records, got {len(records)}"
    )
    for r in records:
        for k in ("difficulty", "graph"):
            assert k in r, f"{dataset}__{graph}: record missing {k!r}: {r}"

    with summary_path.open(encoding="utf-8") as fh:
        summary = json.load(fh)
    missing = _REQUIRED_SUMMARY_KEYS - set(summary)
    assert not missing, f"{dataset}__{graph}: summary missing keys {missing}"
    assert "records" not in summary, (
        f"{dataset}__{graph}: summary should not include 'records' "
        "(worker is supposed to strip it before writing)."
    )
    return records


# ──────────────────────────────────────────────────────────────────────────────
# 6. Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_smoke_three_datasets(tmp_path: Path, local_neo4j: Dict[str, str]) -> None:
    """
    Three-pair smoke test — one (dataset, graph) per dataset.

    Builds tiny in-tmp fixtures, spawns eval_run.py against a temp
    eval_config, then runs eval_aggregate.py and asserts a coherent
    table.
    """
    rig_dir = tmp_path / "rig"
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    out_dir = tmp_path / "logs_eval"
    setup_artifacts = tmp_path / "setup_artifacts"

    _write_sitecustomize(rig_dir)

    # ── Fixtures ────────────────────────────────────────────────────────────
    cb_path  = tmp_path / "cypherbench.jsonl"
    mtq_path = tmp_path / "mindthequery.json"
    zg_path  = tmp_path / "zograscope.csv"
    _write_cypherbench_fixture(cb_path,  graph="smoke")
    _write_mindthequery_fixture(mtq_path, graph="smoke")
    _write_zograscope_fixture(zg_path)

    pairs = [
        ("cypherbench",  "smoke"),
        ("mindthequery", "smoke"),
        ("zograscope",   "pole"),
    ]
    _write_test_eval_config(
        cfg_dir,
        pairs           = pairs,
        cypherbench     = cb_path,
        mindthequery    = mtq_path,
        zograscope      = zg_path,
        out_dir         = out_dir,
        setup_artifacts = setup_artifacts,
        neo4j           = local_neo4j,
    )

    # ── Run eval_run.py ─────────────────────────────────────────────────────
    proc = _run_eval(rig_dir, cfg_dir)
    assert proc.returncode == 0, (
        f"eval_run.py exited {proc.returncode}.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    # ── Per-pair output assertions ─────────────────────────────────────────
    all_records: List[Dict[str, Any]] = []
    for dataset, graph in pairs:
        all_records.extend(_assert_per_pair_outputs(out_dir, dataset, graph))

    # At least one EA value should be a finite float in [0, 1] — proves
    # we actually round-tripped through Neo4j and computed the metric.
    finite_eas = [
        r["ea"] for r in all_records
        if isinstance(r.get("ea"), bool) or (
            isinstance(r.get("ea"), (int, float)) and 0.0 <= float(r["ea"]) <= 1.0
        )
    ]
    assert finite_eas, (
        "No record produced a finite EA value; the Neo4j round-trip "
        "didn't fire.  Check that the local Neo4j is reachable at "
        f"{local_neo4j['uri']}."
    )

    # ── Run eval_aggregate.py ──────────────────────────────────────────────
    agg = _run_aggregate(rig_dir, cfg_dir)
    assert agg.returncode == 0, (
        f"eval_aggregate.py exited {agg.returncode}.\n"
        f"stdout:\n{agg.stdout}\nstderr:\n{agg.stderr}"
    )

    out = agg.stdout
    for dataset, _ in pairs:
        assert dataset in out, (
            f"eval_aggregate.py output missing dataset {dataset!r}.\n"
            f"stdout:\n{out}"
        )
    assert "all" in out, (
        f"eval_aggregate.py output missing 'all' bucket row.\n"
        f"stdout:\n{out}"
    )


def test_smoke_single_graph(tmp_path: Path, local_neo4j: Dict[str, str]) -> None:
    """
    Single-graph smoke test — guards the "validate the harness with one
    graph before setting up the rest" use case.
    """
    rig_dir = tmp_path / "rig"
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    out_dir = tmp_path / "logs_eval"
    setup_artifacts = tmp_path / "setup_artifacts"

    _write_sitecustomize(rig_dir)

    cb_path  = tmp_path / "cypherbench.jsonl"
    mtq_path = tmp_path / "mindthequery.json"
    zg_path  = tmp_path / "zograscope.csv"
    _write_cypherbench_fixture(cb_path,  graph="smoke")
    # Mind-the-Query / ZOGRASCOPE fixtures still need to exist so paths
    # in the temp eval_config resolve, but we never evaluate them.
    _write_mindthequery_fixture(mtq_path, graph="smoke")
    _write_zograscope_fixture(zg_path)

    pairs = [("cypherbench", "smoke")]
    _write_test_eval_config(
        cfg_dir,
        pairs           = pairs,
        cypherbench     = cb_path,
        mindthequery    = mtq_path,
        zograscope      = zg_path,
        out_dir         = out_dir,
        setup_artifacts = setup_artifacts,
        neo4j           = local_neo4j,
    )

    proc = _run_eval(rig_dir, cfg_dir)
    assert proc.returncode == 0, (
        f"eval_run.py exited {proc.returncode}.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    records = _assert_per_pair_outputs(out_dir, "cypherbench", "smoke")
    finite_eas = [
        r["ea"] for r in records
        if isinstance(r.get("ea"), bool) or (
            isinstance(r.get("ea"), (int, float)) and 0.0 <= float(r["ea"]) <= 1.0
        )
    ]
    assert finite_eas, (
        "No record produced a finite EA value; the Neo4j round-trip "
        "didn't fire in the single-graph case."
    )

    agg = _run_aggregate(rig_dir, cfg_dir)
    assert agg.returncode == 0, (
        f"eval_aggregate.py exited {agg.returncode}.\n"
        f"stdout:\n{agg.stdout}\nstderr:\n{agg.stderr}"
    )
    assert "cypherbench" in agg.stdout, (
        f"single-graph aggregate missing dataset header.\n"
        f"stdout:\n{agg.stdout}"
    )
    assert "all" in agg.stdout, (
        f"single-graph aggregate missing 'all' bucket row.\n"
        f"stdout:\n{agg.stdout}"
    )
