#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metrics_CypherBench.py
======================
Evaluate the text-to-Cypher agent against the **CypherBench** test set.

This module assumes:

1. The CypherBench graph has already been loaded into the live Neo4j database
   pointed at by ``.env`` (``NEO4J_URI`` / ``NEO4J_DATABASE`` / …).
2. The setup pipeline (``setup_project.py``) has been run so the agent's tools,
   FAISS index, and config are ready.

For each example in the CypherBench test set we

    1. Run :func:`ask_auto` from ``ner_agent_auto`` to get the agent's
       predicted Cypher + the rows Neo4j returned for that prediction.
    2. Execute the **gold** Cypher directly via ``neo4j_graph.query`` to get
       the gold rows.
    3. Compare predicted rows against gold rows after normalisation and
       compute two metrics:

         * **Execution Accuracy (EA)** — multiset (order-insensitive) match.
         * **Execution Match  (EM)** — exact ordered list match.

The module exposes a CLI for batch evaluation::

    python metrics_CypherBench.py \
        --dataset path/to/cypherbench_test.jsonl \
        --out     results.jsonl \
        --limit   100 \
        --verbose

and a Python API (:func:`evaluate_dataset`, :func:`evaluate_one`) for
programmatic use.

Notes on metric semantics
-------------------------
The CypherBench paper defines Execution Accuracy as the agreement between
the executed result of the predicted query and the gold query, after a
canonical normalisation (sort, lowercase strings, strip whitespace, coerce
numeric types).  We follow the same recipe here:

* Each row returned by ``Neo4jGraph.query`` is a ``dict``.  Column **names**
  often differ between predicted and gold queries (e.g. ``count(m)`` vs
  ``cnt``), so we drop the keys and compare a sorted tuple of the row's
  values.
* Scalar values are normalised: strings → ``str.strip().lower()``,
  numerics → ``float`` (so ``1`` and ``1.0`` agree), ``None`` → ``None``,
  lists / dicts → recursively normalised.
* EA = multiset of normalised rows matches.
* EM = ordered list of normalised rows matches exactly.

A predicted query that fails to execute (syntax error, timeout, etc.)
counts as a miss for both metrics.

Result-set normalisation
------------------------
Comparison is delegated to :mod:`cypher_eval_normalize.normalize_result_set`,
which structurally expands ``Node`` / ``Relationship`` / ``Path`` cells
(label-set + property-set, never ``element_id``), rounds floats to a
configurable epsilon, and sorts ``collect()``-style list cells unless the
gold query has a top-level ``ORDER BY``.  Pass ``--strict-cypherbench-mode``
on the CLI (or ``strict_cypherbench=True`` programmatically) to reproduce
upstream CypherBench's exact published numbers.  EA stays multiset and EM
stays ordered in both modes — the ORDER BY heuristic only governs
``sort_collections`` inside ``collect()`` cells; it does NOT auto-promote
EA to ordered comparison, because the EA−EM gap is a useful signal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger

from agent.agent_helper import neo4j_graph
from ner_agent_auto import ask_auto
from config import DEFAULT_TOP_K, resolve_spec
from .cypher_eval_normalize import (
    normalize_result_set,
    column_counts_match,
    strict_cypherbench_kwargs,
)
from .exact_match import exact_match as _literal_exact_match
from .psjs import compute_psjs as _compute_psjs
from .difficulty import (
    classify as _classify_difficulty,
    aggregate_by_difficulty,
    aggregate_by_strategy,
    strategy_of,
)
from neo4j_lib.safe_query import safe_cypher_run, TransactionTimedOutError


# Default server-side per-transaction timeout used by ``execute_cypher`` for
# the gold-cypher and ad-hoc cypher executions in this module.  Overridable
# via the ``EVAL_NEO4J_QUERY_TIMEOUT`` env var (seconds, float).  30 s is a
# conservative cap — well-formed CypherBench gold queries on the 1k–50k-node
# eval graphs typically finish in milliseconds; anything past 30 s is almost
# certainly a pathological query plan (cross product, missing LIMIT, etc.).
_DEFAULT_CYPHER_TIMEOUT_SEC = float(
    os.environ.get("EVAL_NEO4J_QUERY_TIMEOUT", "30")
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Dataset loading
# ──────────────────────────────────────────────────────────────────────────────

# CypherBench releases the test set as JSON / JSONL.  Different snapshots
# have used slightly different field names — we accept the common variants.
_QUESTION_KEYS = ("nl_question", "question", "natural_language_question", "nl")
_CYPHER_KEYS   = ("gold_cypher", "cypher", "target_cypher", "ground_truth_cypher")
_ANSWER_KEYS   = ("answer", "gold_answer", "expected_answer", "result")
_ID_KEYS       = ("qid", "id", "question_id", "gid")
# CypherBench tags each example with the underlying property graph it
# targets (``graph`` in the public release; legacy snapshots used
# ``schema``).  Surfaced on the per-example record so the per-graph
# eval driver can filter per pair.
_GRAPH_KEYS    = ("graph", "schema", "source_dataset", "dataset")


def _first_present(d: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[Any]:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def load_dataset(path: str) -> List[Dict[str, Any]]:
    """
    Load a CypherBench-style test set from *path*.

    Supports:
        * ``*.jsonl`` — one example per line
        * ``*.json``  — a single JSON list of examples

    Returns
    -------
    list[dict]
        Each example contains at minimum ``question`` and ``cypher``;
        ``answer`` and ``qid`` are populated when present in the source file.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    raw: List[Dict[str, Any]] = []
    if p.suffix.lower() == ".jsonl":
        with p.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping malformed JSONL line {line_no}: {e}")
    else:
        with p.open("r", encoding="utf-8") as fh:
            obj = json.load(fh)
        if isinstance(obj, list):
            raw = obj
        elif isinstance(obj, dict) and "data" in obj:
            raw = obj["data"]
        else:
            raise ValueError(
                f"Unexpected JSON layout in {path}: expected list or "
                f"{{'data': [...]}} but got {type(obj).__name__}"
            )

    examples: List[Dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        question = _first_present(row, _QUESTION_KEYS)
        cypher   = _first_present(row, _CYPHER_KEYS)
        if not question or not cypher:
            logger.warning(
                f"Example #{i} missing question/cypher fields — skipping. "
                f"Keys present: {list(row.keys())}"
            )
            continue
        examples.append({
            "qid":      _first_present(row, _ID_KEYS) or f"ex_{i}",
            "question": str(question),
            "cypher":   str(cypher),
            "answer":   _first_present(row, _ANSWER_KEYS),
            "graph":    _first_present(row, _GRAPH_KEYS),
            "raw":      row,
        })

    logger.info(f"Loaded {len(examples)} examples from {path}")
    return examples


# ──────────────────────────────────────────────────────────────────────────────
# 2. Gold-Cypher execution
# ──────────────────────────────────────────────────────────────────────────────

def execute_cypher(
    cypher: str,
    *,
    timeout: Optional[float] = None,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Run *cypher* against the live Neo4j database via ``agent_helper.neo4j_graph``.

    Parameters
    ----------
    cypher
        The Cypher statement to execute. Empty / whitespace-only is rejected.
    timeout
        Per-transaction server-side timeout in seconds. Defaults to
        :data:`_DEFAULT_CYPHER_TIMEOUT_SEC` (30 s, overridable via the
        ``EVAL_NEO4J_QUERY_TIMEOUT`` env var). When the driver of the bound
        ``neo4j_graph`` is reachable (``_driver`` attribute), the query is
        executed via :func:`neo4j_lib.safe_query.safe_cypher_run` which
        enforces the timeout server-side. If we can't reach the driver
        (custom wrapper), we fall through to the historic no-timeout
        ``neo4j_graph.query(...)`` path with a logged warning.

    Returns
    -------
    (rows, error)
        On success ``rows`` is a list of dicts (LangChain Neo4jGraph output)
        and ``error`` is ``None``.  On failure ``rows`` is ``None`` and
        ``error`` carries the exception's string form. Transaction-timeout
        failures surface as ``error="transaction timeout: …"`` so callers
        can grep / classify them distinctly from real syntax errors.
    """
    if not cypher or not cypher.strip():
        return None, "empty cypher"

    eff_timeout = float(timeout) if timeout is not None else _DEFAULT_CYPHER_TIMEOUT_SEC

    driver   = getattr(neo4j_graph, "_driver",   None)
    database = getattr(neo4j_graph, "_database", None)

    try:
        if driver is not None:
            rows = safe_cypher_run(
                driver,
                cypher,
                params=None,
                timeout=eff_timeout,
                database=database,
            )
        else:
            # Fallback only triggers on a non-LangChain Neo4jGraph wrapper.
            logger.warning(
                "execute_cypher: neo4j_graph has no _driver attribute; "
                "falling back to neo4j_graph.query() with NO client-side "
                "timeout enforcement."
            )
            rows = neo4j_graph.query(cypher)
        if rows is None:
            return [], None
        return list(rows), None
    except TransactionTimedOutError as exc:  # type: ignore[misc]
        return None, f"transaction timeout: {type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 — we want to surface every failure
        return None, f"{type(exc).__name__}: {exc}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Result normalisation
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_scalar(v: Any) -> Any:
    """Canonicalise a scalar so ``1`` == ``1.0``, ``"  Foo "`` == ``"foo"`` etc."""
    if v is None:
        return None
    if isinstance(v, bool):
        # Bools are also ints — keep them distinct from numerics.
        return ("__bool__", v)
    if isinstance(v, (int, float)):
        # Coerce to float for cross-type equality (e.g. count returning int vs
        # toFloat returning float).
        try:
            return float(v)
        except Exception:  # pragma: no cover
            return v
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, (list, tuple)):
        return tuple(_normalise_scalar(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted(
            (str(k), _normalise_scalar(val)) for k, val in v.items()
        ))
    # Fallback — repr keeps Neo4j Node / Relationship objects comparable.
    return repr(v)


def _row_signature(row: Any) -> Tuple[Any, ...]:
    """
    Convert a single Neo4j result row into a hashable, normalised tuple
    of *values*.  Column names are intentionally dropped because the
    predicted and gold queries often label columns differently
    (e.g. ``count(m)`` vs ``num_movies``).
    """
    if isinstance(row, dict):
        # Sort by value-signature so column ordering doesn't matter either.
        sigs = [_normalise_scalar(v) for v in row.values()]
        # Single-column result → unwrap so ``[{"x": 1}]`` matches ``[1]``.
        if len(sigs) == 1:
            return (sigs[0],)
        return tuple(sorted(sigs, key=lambda x: repr(x)))
    if isinstance(row, (list, tuple)):
        return tuple(_normalise_scalar(v) for v in row)
    return (_normalise_scalar(row),)


def normalise_rows(rows: Optional[Iterable[Any]]) -> List[Tuple[Any, ...]]:
    """Map a raw result-set into a list of normalised row signatures."""
    if rows is None:
        return []
    return [_row_signature(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# 4. Metric computation
# ──────────────────────────────────────────────────────────────────────────────

# ── Default kwargs for the new normalize_result_set comparator ──────────────
#
# These reproduce the legacy intent of ``_normalise_scalar`` /
# ``_row_signature`` (case-insensitive strings, single-column unwrap, key /
# column-order agnostic) while *additionally* giving correct behaviour for
# Node / Relationship / Path cells and float drift.  Strict-CypherBench mode
# overrides these via ``strict_cypherbench_kwargs()``.
_DEFAULT_NORMALIZE_KW: Dict[str, Any] = {
    "float_eps":                1e-6,
    "sort_collections":         True,
    "expand_nodes":             True,
    "expand_relationships":     True,
    "case_insensitive_strings": True,
    "compare_keys":             False,
    "compare_column_order":     False,
}


def execution_accuracy(
    pred_rows: List[Any],
    gold_rows: List[Any],
    *,
    gold_cypher: Optional[str] = None,
    strict_cypherbench: bool = False,
    normalize_kwargs: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Multiset (order-insensitive) match between two normalised result sets.

    Returns ``True`` iff each side has the same rows with the same
    multiplicity.  Empty == Empty.

    Parameters
    ----------
    gold_cypher
        Forwarded to :func:`normalize_result_set` so the ``ORDER BY``
        heuristic can disable ``sort_collections`` for ordered ``collect()``
        cells.  This does **not** auto-promote EA to ordered comparison —
        see ``cypher_eval_normalize`` module docstring "Scoping note".
    strict_cypherbench
        When True, normalise both sides with upstream CypherBench's exact
        rules so published numbers can be reproduced as a sanity check.
    normalize_kwargs
        Optional explicit override of the kwargs forwarded to
        :func:`normalize_result_set`.  Wins over ``strict_cypherbench``.
    """
    kw = (
        dict(normalize_kwargs)
        if normalize_kwargs is not None
        else (strict_cypherbench_kwargs() if strict_cypherbench else dict(_DEFAULT_NORMALIZE_KW))
    )
    # Fast path: differing column counts can never match.
    if not column_counts_match(pred_rows, gold_rows):
        return False
    p = normalize_result_set(pred_rows, gold_cypher=gold_cypher, **kw)
    g = normalize_result_set(gold_rows, gold_cypher=gold_cypher, **kw)
    return Counter(p) == Counter(g)


def execution_match(
    pred_rows: List[Any],
    gold_rows: List[Any],
    *,
    gold_cypher: Optional[str] = None,
    strict_cypherbench: bool = False,
    normalize_kwargs: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Strict ordered match between two normalised result sets.

    Returns ``True`` iff the rows occur in the same order.  This is the
    appropriate metric when the gold query uses ``ORDER BY`` and ranking
    matters.  See :func:`execution_accuracy` for parameter docs.
    """
    kw = (
        dict(normalize_kwargs)
        if normalize_kwargs is not None
        else (strict_cypherbench_kwargs() if strict_cypherbench else dict(_DEFAULT_NORMALIZE_KW))
    )
    if not column_counts_match(pred_rows, gold_rows):
        return False
    p = normalize_result_set(pred_rows, gold_cypher=gold_cypher, **kw)
    g = normalize_result_set(gold_rows, gold_cypher=gold_cypher, **kw)
    return p == g


# ──────────────────────────────────────────────────────────────────────────────
# 5. Per-example evaluation
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_one_legacy(
    question:    str,
    gold_cypher: str,
    qid:         str  = "",
    top_k:       int  = DEFAULT_TOP_K,
    verbose:     bool = False,
    mode:        Optional[str] = None,
    strict_cypherbench: bool = False,
) -> Dict[str, Any]:
    """
    Evaluate the agent on a single CypherBench example (legacy CLI path).

    .. note::
        This is the original positional-argument entry point used by the
        ``__main__`` CLI of this module.  New harness code should use
        :func:`evaluate_one`, which takes a single ``example`` dict and
        returns the unified ``{"ea", "em", "psjs", ...}`` schema shared by
        all three dataset modules (CypherBench, Mind-the-Query, ZOGRASCOPE).

    Steps
    -----
    1. Run ``ask_auto`` to get the agent's predicted Cypher + executed rows.
       (``ask_auto`` already executes the predicted Cypher inside
       ``GraphCypherQAChain`` and returns the raw rows in ``out["context"]``.)
    2. Execute *gold_cypher* directly to get the gold rows.
    3. Compare via :func:`execution_accuracy` and :func:`execution_match`.

    Returns a dict suitable for JSONL logging — see the schema near the
    bottom of this function.
    """
    record: Dict[str, Any] = {
        "qid":              qid,
        "question":         question,
        "gold_cypher":      gold_cypher,
        "predicted_cypher": "",
        "pred_rows":        None,
        "gold_rows":        None,
        "pred_error":       None,
        "gold_error":       None,
        "execution_accuracy": False,
        "execution_match":    False,
        "ner_mode":         resolve_spec(mode).canonical,
        "elapsed_sec":      0.0,
    }

    t0 = time.time()

    # ── Step 1: agent prediction (NER → Cypher → execute) ────────────────────
    # ``mode`` is forwarded to ``ask_auto`` so the CLI / API caller can
    # ablate the NER stage without editing config.py.
    try:
        out = ask_auto(prompt=question, top_k=top_k, verbose=verbose, mode=mode)
        record["predicted_cypher"] = out.get("cypher", "") or ""
        record["pred_rows"]        = out.get("context", []) or []
        record["entities"]         = out.get("entities", "")
        # ``ask_auto`` returns the resolved mode it actually used — capture
        # it so the per-example log isn't ambiguous when ``mode is None``.
        record["ner_mode"]         = out.get("mode", record["ner_mode"])
    except Exception as exc:  # noqa: BLE001
        record["pred_error"] = f"{type(exc).__name__}: {exc}"
        if verbose:
            logger.error(
                f"[{qid}] agent failed: {record['pred_error']}\n"
                f"{traceback.format_exc()}"
            )

    # ── Step 2: gold execution ───────────────────────────────────────────────
    gold_rows, gold_err = execute_cypher(gold_cypher)
    record["gold_rows"]  = gold_rows
    record["gold_error"] = gold_err

    # ── Step 3: metrics (only when both sides ran) ───────────────────────────
    if record["pred_error"] is None and record["gold_error"] is None:
        record["execution_accuracy"] = execution_accuracy(
            record["pred_rows"], record["gold_rows"],
            gold_cypher=gold_cypher,
            strict_cypherbench=strict_cypherbench,
        )
        record["execution_match"] = execution_match(
            record["pred_rows"], record["gold_rows"],
            gold_cypher=gold_cypher,
            strict_cypherbench=strict_cypherbench,
        )

    record["elapsed_sec"] = round(time.time() - t0, 3)
    return record


# ──────────────────────────────────────────────────────────────────────────────
# 6. Batch evaluation
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_dataset_legacy(
    examples:      List[Dict[str, Any]],
    out_path:      Optional[str] = None,
    top_k:         int  = DEFAULT_TOP_K,
    limit:         Optional[int] = None,
    skip_failures: bool = False,
    verbose:       bool = False,
    mode:          Optional[str] = None,
    strict_cypherbench: bool = False,
) -> Dict[str, Any]:
    """
    Legacy CLI entry-point — operates on a pre-loaded list of examples and
    reports the original CypherBench-only metrics (Execution Accuracy +
    Execution Match, where the latter is *ordered* result-set match, NOT the
    literal-string EM defined by :mod:`eval.exact_match`).

    .. note::
        New harness code should use :func:`evaluate_dataset`, which accepts
        a *path*, returns the unified ``{"ea", "em", "psjs", ...}`` schema,
        and is shared with the Mind-the-Query and ZOGRASCOPE modules.

    Parameters
    ----------
    examples      : Output of :func:`load_dataset`.
    out_path      : Optional JSONL path to stream per-example records to.
    top_k         : ``ask_auto`` tool-selection ``top_k``.
    limit         : Evaluate only the first *limit* examples (debug runs).
    skip_failures : When *True*, exclude examples where either side errored
                    from the denominator.  Default *False* (CypherBench-style
                    — agent failures count as misses).
    verbose       : Stream agent traces and per-example logs.
    mode          : Optional NER pipeline mode override —
                    ``"full"`` / ``"node_only"`` / ``"no_ner"``.
                    Defaults to the value-linking config axes.

    Returns
    -------
    dict
        ``{
            "total":              N,
            "evaluated":          M,         # N minus errored if skip_failures
            "execution_accuracy": float,     # in [0, 1]
            "execution_match":    float,     # in [0, 1]
            "agent_errors":       int,
            "gold_errors":        int,
            "elapsed_sec":        float,
        }``
    """
    # mode is validated by config.resolve_spec() downstream; a bad canonical
    # name raises there.

    if limit is not None:
        examples = examples[:limit]

    total       = len(examples)
    n_ea        = 0
    n_em        = 0
    agent_errs  = 0
    gold_errs   = 0
    counted     = 0

    out_fh = None
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        out_fh = open(out_path, "w", encoding="utf-8")

    t0 = time.time()
    try:
        for i, ex in enumerate(examples, 1):
            rec = evaluate_one_legacy(
                question    = ex["question"],
                gold_cypher = ex["cypher"],
                qid         = str(ex.get("qid", f"ex_{i}")),
                top_k       = top_k,
                verbose     = verbose,
                mode        = mode,
                strict_cypherbench = strict_cypherbench,
            )

            if rec["pred_error"]: agent_errs += 1
            if rec["gold_error"]: gold_errs  += 1

            errored = bool(rec["pred_error"] or rec["gold_error"])
            if errored and skip_failures:
                pass  # not counted in denominator
            else:
                counted += 1
                if rec["execution_accuracy"]: n_ea += 1
                if rec["execution_match"]:    n_em += 1

            print(
                f"[{i:>4}/{total}] {rec['qid']:<12} "
                f"EA={'✓' if rec['execution_accuracy'] else '✗'} "
                f"EM={'✓' if rec['execution_match']    else '✗'} "
                f"({rec['elapsed_sec']}s)"
                + (f"  pred_err={rec['pred_error']}" if rec['pred_error'] else "")
                + (f"  gold_err={rec['gold_error']}" if rec['gold_error'] else "")
            )

            if out_fh:
                out_fh.write(json.dumps(_jsonable(rec), ensure_ascii=False) + "\n")
                out_fh.flush()
    finally:
        if out_fh:
            out_fh.close()

    elapsed = round(time.time() - t0, 2)
    summary = {
        "total":               total,
        "evaluated":           counted,
        "execution_accuracy":  (n_ea / counted) if counted else 0.0,
        "execution_match":     (n_em / counted) if counted else 0.0,
        "ea_correct":          n_ea,
        "em_correct":          n_em,
        "agent_errors":        agent_errs,
        "gold_errors":         gold_errs,
        "ner_mode":            resolve_spec(mode).canonical,
        "strict_cypherbench":  strict_cypherbench,
        "elapsed_sec":         elapsed,
    }
    return summary


# ──────────────────────────────────────────────────────────────────────────────
# 6b. Unified harness API — shared schema with metrics_MindTheQuery /
#     metrics_ZOGRASCOPE.  Computes EA + literal-string EM + PSJS.
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_one(example: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate a single CypherBench example under the unified harness schema.

    Parameters
    ----------
    example : dict
        Loaded by :func:`load_dataset` — must contain ``question`` and
        ``cypher`` (gold).  ``qid`` is optional.

    Returns
    -------
    dict
        ``{
            "qid":         str,
            "question":    str,
            "ea":          bool | None,
            "em":          bool | None,    # literal-string EM (eval.exact_match)
            "psjs":        float | None,
            "pred_cypher": str,
            "gold_cypher": str | None,
            "graph":       str | None,     # per-example target graph (None
                                           # if the source row didn't tag one)
            "difficulty":  "easy"|"medium"|"hard"|None,
            "error":       Optional[str],
        }``

        ``ea``/``em``/``psjs`` are ``None`` only when not applicable
        (CypherBench always ships gold Cypher, so they are never ``None``
        under normal operation — they may be ``None`` only on agent failure
        for EA, or PSJS-rewrite-no-EA edge cases).  ``error`` is ``None`` on
        success.
    """
    qid         = str(example.get("qid", ""))
    question    = str(example.get("question", ""))
    gold_cypher = example.get("cypher")
    graph_name  = example.get("graph")

    record: Dict[str, Any] = {
        "qid":         qid,
        "question":    question,
        "ea":          None,
        "em":          None,
        "psjs":        None,
        "pred_cypher": "",
        "gold_cypher": gold_cypher,
        "graph":       graph_name,
        "difficulty":  _classify_difficulty(gold_cypher),
        "error":       None,
        # ── Per-stage timing (seconds). All four fields are always present so
        #    downstream grep / pandas filtering never needs `.get()` guards. ──
        "elapsed_agent_sec": 0.0,   # ask_auto end-to-end (NER + cypher gen + pred-exec + QA)
        "elapsed_gold_sec":  0.0,   # execute_cypher(gold_cypher)
        "elapsed_psjs_sec":  0.0,   # _compute_psjs(...)
        "elapsed_total_sec": 0.0,   # sum, for quick "this example took N seconds" filtering
    }

    t_total_start = time.perf_counter()

    # ── Step 1: agent prediction ────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        out = ask_auto(prompt=question)
        pred_cypher = out.get("cypher", "") or ""
        pred_rows   = out.get("context", []) or []
        record["pred_cypher"] = pred_cypher
    except Exception as exc:  # noqa: BLE001
        record["elapsed_agent_sec"] = round(time.perf_counter() - t0, 3)
        record["elapsed_total_sec"] = round(time.perf_counter() - t_total_start, 3)
        record["error"] = f"agent: {type(exc).__name__}: {exc}"
        return record
    record["elapsed_agent_sec"] = round(time.perf_counter() - t0, 3)

    # ── Step 2: gold execution ───────────────────────────────────────────────
    t0 = time.perf_counter()
    gold_rows, gold_err = execute_cypher(gold_cypher) if gold_cypher else (None, "no gold cypher")
    record["elapsed_gold_sec"] = round(time.perf_counter() - t0, 3)
    if gold_err is not None:
        record["error"] = f"gold: {gold_err}"
        # We can still compute EM since it is purely string-based.
        record["em"] = _literal_exact_match(pred_cypher, gold_cypher)
        record["elapsed_total_sec"] = round(time.perf_counter() - t_total_start, 3)
        return record

    # ── Step 3: metrics ──────────────────────────────────────────────────────
    try:
        record["ea"] = execution_accuracy(pred_rows, gold_rows, gold_cypher=gold_cypher)
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"ea: {type(exc).__name__}: {exc}"

    record["em"] = _literal_exact_match(pred_cypher, gold_cypher)

    t0 = time.perf_counter()
    try:
        record["psjs"] = _compute_psjs(
            pred_cypher, gold_cypher,
            neo4j_graph=neo4j_graph,
            ea_value=record["ea"],
        )
    except Exception as exc:  # noqa: BLE001
        # Don't blank out EA/EM if PSJS itself blew up — just log it on
        # the record's error field if there isn't already one.
        if record["error"] is None:
            record["error"] = f"psjs: {type(exc).__name__}: {exc}"
    record["elapsed_psjs_sec"]  = round(time.perf_counter() - t0, 3)
    record["elapsed_total_sec"] = round(time.perf_counter() - t_total_start, 3)

    return record


# ──────────────────────────────────────────────────────────────────────────────
# 6c. Per-example hard timeout (watchdog)
#
# A single Cypher example should finish in ~10–30 s end-to-end on the eval
# graphs.  Anything past ~60 s is almost always one of:
#   • an LLM call stuck in its httpx retry chain,
#   • the NER ReAct agent spinning in a tool-call loop,
#   • a malformed predicted Cypher hanging the Neo4j server,
#   • the gold-Cypher execution hanging (slow plan, locked DB).
#
# Strategy
# --------
# We use a **two-layer** watchdog:
#
# 1. ``signal.SIGALRM`` (cooperative): raises :class:`_ExampleTimeoutError`
#    in the main thread when the cap is exceeded.  This is fast and clean
#    when nothing intercepts the exception.
#
# 2. ``threading.Thread`` (hard): if the SIGALRM-raised exception is
#    *swallowed* by a broad ``except Exception:`` block — which LangGraph's
#    :class:`ToolNode` does by default (see ``langgraph/prebuilt/tool_node.py``
#    where it catches every ``Exception`` and converts it to a
#    ``ToolMessage`` so the ReAct loop can continue) — the example would
#    otherwise hang forever, because ``signal.alarm()`` is one-shot.
#    The hard backstop fires after ``2 × timeout_sec`` and forcibly raises
#    :class:`_ExampleTimeoutError` again from the watcher thread via
#    :func:`_PyThreadState_SetAsyncExc` (when available) and, as a final
#    resort after ``3 × timeout_sec``, calls :func:`os._exit` so the
#    parent driver moves on to the next pair.
#
# We also make :class:`_ExampleTimeoutError` a subclass of
# :class:`BaseException`, NOT :class:`Exception`, so the standard
# ``except Exception:`` blocks scattered across LangChain / LangGraph /
# httpx do *not* catch it.  This was the root cause of the
# 2026-05-25 ``cypherbench_augmented/movie`` run wedging at example #17
# for 107 minutes before the parent's outer timeout fired.
#
# On Windows ``SIGALRM`` is unavailable; we still install the threading
# backstop so the watchdog continues to work in degraded form.
# ──────────────────────────────────────────────────────────────────────────────

# Default per-example wall-clock cap.  Overridable via the
# ``EVAL_PER_EXAMPLE_TIMEOUT`` env var (seconds, int).  Set to 0 to disable
# the watchdog entirely (NOT recommended — that's how a single hung example
# wedges a 100-question run for 5 min+ before the subprocess timeout fires).
_DEFAULT_PER_EXAMPLE_TIMEOUT_SEC = int(
    os.environ.get("EVAL_PER_EXAMPLE_TIMEOUT", "60")
)

try:
    import signal as _signal
    _HAVE_SIGALRM = hasattr(_signal, "SIGALRM")
except Exception:  # pragma: no cover
    _signal       = None  # type: ignore[assignment]
    _HAVE_SIGALRM = False


class _ExampleTimeoutError(BaseException):
    """
    Raised by the watchdog (SIGALRM handler or backstop thread) when an
    example exceeds its budget.

    Inherits from :class:`BaseException` rather than :class:`Exception`
    on purpose: LangGraph's ``ToolNode``, LangChain runnables, and the
    Neo4j driver all use bare ``except Exception:`` blocks internally.
    A normal ``Exception`` subclass would be swallowed by those handlers
    (the timeout would silently turn into an error ToolMessage and the
    agent loop would keep spinning), which is exactly the bug that
    wedged the 2026-05-25 cypherbench_augmented/movie run on example #17
    for 107 minutes.
    """


def _alarm_handler(signum, frame):  # noqa: ARG001 — signal handler signature
    raise _ExampleTimeoutError()


def _async_raise_in_thread(tid: int, exc_type: type) -> bool:
    """
    Raise *exc_type* asynchronously in the Python thread with id *tid*.

    Uses :func:`ctypes.pythonapi.PyThreadState_SetAsyncExc`.  Returns
    ``True`` on success.  This is the documented mechanism for hard-
    cancelling a thread that has gone unresponsive; in our case the
    "thread" is the main thread, and we call it from a daemon watcher
    when SIGALRM was swallowed by a ``except Exception:`` block deep
    inside LangGraph / LangChain / the Neo4j driver.

    Caveat: this only takes effect at the next bytecode boundary in the
    target thread.  If the main thread is parked in a C extension that
    never releases the GIL, the exception is queued but not delivered.
    That's why we still escalate to ``os._exit`` as a final resort.
    """
    try:
        import ctypes
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(tid), ctypes.py_object(exc_type),
        )
        if res > 1:
            # We hit more than one thread — undo by passing NULL.
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
            return False
        return res == 1
    except Exception:  # pragma: no cover — defensive
        return False


def _evaluate_one_with_watchdog(
    example:     Dict[str, Any],
    timeout_sec: int,
) -> Dict[str, Any]:
    """
    Run :func:`evaluate_one` with a hard wall-clock cap.

    See the module-level commentary above for the two-layer design
    (SIGALRM cooperative + thread-based hard backstop).

    When the cap is exceeded, return a record with all metrics ``None``,
    ``error="example timeout: exceeded Ns"``, and ``elapsed_total_sec``
    set to the elapsed time.  This means the example will count as
    ``n_errors`` in the aggregate, NOT silently as a miss — making slow
    examples easy to spot via ``grep "example timeout"`` on the records
    JSONL.

    When ``timeout_sec <= 0`` falls through to a bare
    ``evaluate_one(example)`` call.
    """
    if timeout_sec <= 0:
        return evaluate_one(example)

    import threading

    t0 = time.perf_counter()

    # ── Layer 1: cooperative SIGALRM (UNIX only) ────────────────────────────
    old_handler = None
    if _HAVE_SIGALRM:
        old_handler = _signal.signal(_signal.SIGALRM, _alarm_handler)  # type: ignore[union-attr]
        _signal.alarm(timeout_sec)                                     # type: ignore[union-attr]

    # ── Layer 2: hard backstop on a daemon thread ───────────────────────────
    # Fires at 2× the cap if SIGALRM gets swallowed by a broad except
    # block in LangGraph / LangChain / the driver.  Escalates to
    # ``os._exit`` at 3× the cap when the main thread is parked in a
    # GIL-holding C extension and PyThreadState_SetAsyncExc cannot get
    # an exception delivered.
    main_tid = threading.get_ident()
    stop_evt = threading.Event()

    def _backstop() -> None:
        # First escalation: async-raise in the main thread.
        if not stop_evt.wait(timeout_sec * 2):
            logger.warning(
                "watchdog backstop: SIGALRM appears to have been swallowed; "
                "async-raising _ExampleTimeoutError in main thread after "
                "%.1fs.",
                timeout_sec * 2,
            )
            _async_raise_in_thread(main_tid, _ExampleTimeoutError)
        else:
            return
        # Second escalation: hard exit if main thread is in a
        # GIL-holding C extension and the async-raise didn't land.
        if not stop_evt.wait(timeout_sec):
            logger.error(
                "watchdog backstop: example still running %.1fs past cap "
                "(async-raise did not land — likely GIL-holding C extension). "
                "Hard-exiting worker via os._exit(3) so the parent driver "
                "moves on to the next pair.",
                timeout_sec * 3,
            )
            os._exit(3)

    watcher = threading.Thread(target=_backstop, name="t2c-watchdog", daemon=True)
    watcher.start()

    try:
        return evaluate_one(example)
    except _ExampleTimeoutError:
        gold_cypher = example.get("cypher")
        elapsed = round(time.perf_counter() - t0, 3)
        return {
            "qid":         str(example.get("qid", "")),
            "question":    str(example.get("question", "")),
            "ea":          None,
            "em":          None,
            "psjs":        None,
            "pred_cypher": "",
            "gold_cypher": gold_cypher,
            "graph":       example.get("graph"),
            "difficulty":  _classify_difficulty(gold_cypher),
            "error":       f"example timeout: exceeded {timeout_sec}s",
            "elapsed_agent_sec": elapsed,
            "elapsed_gold_sec":  0.0,
            "elapsed_psjs_sec":  0.0,
            "elapsed_total_sec": elapsed,
        }
    finally:
        # Stop the backstop thread first so it doesn't fire mid-cleanup.
        stop_evt.set()
        # Always cancel the pending alarm and restore the prior handler,
        # even if evaluate_one raised some unrelated exception.
        if _HAVE_SIGALRM:
            _signal.alarm(0)                                  # type: ignore[union-attr]
            _signal.signal(_signal.SIGALRM, old_handler)      # type: ignore[union-attr]


# ──────────────────────────────────────────────────────────────────────────────
# Progress heartbeat
# ──────────────────────────────────────────────────────────────────────────────
#
# Long evaluations (hundreds of examples) need to surface live progress so an
# operator can tell at a glance whether the run is healthy, stalled, or about
# to overrun a meeting.  We print one line BEFORE each example (so a hang
# leaves a "started at HH:MM:SS, record N" pin in the log) and one line AFTER
# (with score, running mean EA, and an ETA based on completed records).
#
# The output goes to BOTH stdout (so it shows up in tee'd logs) and is
# flushed immediately — a hung pipe is the exact failure mode this guards
# against, so buffered prints would defeat the purpose.
#
# Honors ``EVAL_HEARTBEAT_EVERY`` (default 1) — set to e.g. 10 to print only
# every 10th record, but the first start and last done always print.

def _fmt_hms(seconds: float) -> str:
    """Format a duration in seconds as ``HhMMmSSs`` (compact, no zero pad
    on the leading unit). Used for both elapsed and ETA columns."""
    if seconds is None or seconds < 0:
        return "--"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _heartbeat(
    i: int,
    total: int,
    t0: float,
    *,
    kind: str,
    qid: Any = None,
    question: Optional[str] = None,
    ea: Any = None,
    em: Any = None,
    psjs: Any = None,
    err: Any = None,
    elapsed: Any = None,
    records_so_far: Optional[List[Dict[str, Any]]] = None,
    every: int = 1,
) -> None:
    """Print a single timestamped progress line for record *i* of *total*.

    Always prints the first start (``i==1``) and the last done (``i==total``)
    regardless of *every* — so the operator gets bookend markers even when
    sampling.

    *kind* ∈ {``"start"``, ``"done"``}. ``start`` prints the question so it's
    visible WHICH example is in flight when a hang happens. ``done`` prints
    the per-record metrics plus the running mean EA and an ETA estimated
    from completed wall-clock time.
    """
    # Sampling: skip middle records when ``every > 1`` but always show
    # boundaries (first/last) and any error so the log doesn't go silent.
    is_boundary = (i == 1) or (i == total)
    is_error = err is not None and err != ""
    if not is_boundary and not is_error and (i % max(1, every)) != 0:
        return

    ts = time.strftime("%H:%M:%S", time.localtime())
    prefix = f"[{ts}] [{i:>4}/{total}]"
    qid_str = f"qid={qid}" if qid is not None else ""

    if kind == "start":
        q = (question or "").replace("\n", " ").strip()
        if len(q) > 120:
            q = q[:117] + "..."
        msg = f"{prefix} ▶ start  {qid_str}  q={q!r}"
    else:
        # Compute running mean EA across all completed records so far so the
        # operator can see whether the run is trending up or down without
        # waiting for the final summary.
        running_ea_str = "--"
        if records_so_far:
            ea_vals = [r.get("ea") for r in records_so_far if r.get("ea") is not None]
            if ea_vals:
                running_ea_str = f"{(sum(1 for v in ea_vals if v) / len(ea_vals)):.3f}"

        # ETA: extrapolate remaining wall time from average per-record cost.
        wall = time.time() - t0
        eta_str = "--"
        if i > 0 and i < total:
            per = wall / i
            eta_str = _fmt_hms(per * (total - i))
        elapsed_str = (
            f"t={float(elapsed):.1f}s"
            if isinstance(elapsed, (int, float))
            else "t=?"
        )
        err_str = f"  err={str(err)[:80]}" if is_error else ""
        msg = (
            f"{prefix} ✔ done   {qid_str}  "
            f"ea={ea} em={em} psjs={psjs}  {elapsed_str}  "
            f"runEA={running_ea_str}  wall={_fmt_hms(wall)}  ETA={eta_str}"
            f"{err_str}"
        )

    # Flush both stdout AND stderr so the line survives any buffering layer
    # (tee, nohup, container log driver). Eat any I/O error — a heartbeat
    # MUST NOT take down the eval.
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def evaluate_dataset(
    path:                  str,
    limit:                 Optional[int] = None,
    out:                   Optional[str] = None,
    verbose:               bool          = False,
    graph_filter:          Optional[str] = None,
    dataset_name:          Optional[str] = None,
    per_example_timeout:   Optional[int] = None,
    shard:                 int           = 0,
    shards:                int           = 1,
) -> Dict[str, Any]:
    """
    Run :func:`evaluate_one` over the CypherBench test set at *path* and
    return the unified summary dict shared with the Mind-the-Query and
    ZOGRASCOPE harnesses.

    Parameters
    ----------
    path
        Path to a CypherBench JSON or JSONL file.  See
        :func:`load_dataset` for the accepted layout.
    limit
        Cap on examples to evaluate (``None`` = all).
    out
        Optional JSONL path to stream per-example records to.
    verbose
        Per-example log lines.
    graph_filter
        When set, examples whose ``graph`` field doesn't equal this value
        are skipped before any agent invocation.  Examples with a
        ``None`` graph (source row didn't tag one) are also skipped, with
        a count logged.  Used by the per-graph eval driver to restrict a
        worker subprocess to a single underlying property graph.

    Returns
    -------
    dict
        ``{
            "dataset":    "cypherbench",
            "n":          int,                 # examples attempted
            "n_scored":   {"ea": int, "em": int, "psjs": int},
            "n_errors":   int,
            "ea":         float,               # mean EA over scored
            "em":         float,               # mean EM over scored
            "psjs":       float,               # mean PSJS over scored
            "by_difficulty": dict,             # bucketed sub-summaries
            "elapsed_sec": float,
            "records":    [evaluate_one(...), ...],
        }``
    """
    examples = load_dataset(path)

    if graph_filter is not None:
        before = len(examples)
        examples = [ex for ex in examples if ex.get("graph") == graph_filter]
        skipped = before - len(examples)
        logger.info(
            f"CypherBench graph_filter={graph_filter!r}: kept "
            f"{len(examples)}/{before} examples (skipped {skipped})."
        )

    if limit is not None:
        examples = examples[:limit]

    # Intra-graph sharding: this worker runs only its stride of the examples.
    # shards=1 (default) is a no-op; the strides partition the set exactly
    # (disjoint, complete), so merging K shards reproduces full coverage.
    if shards > 1:
        examples = examples[shard::shards]
        logger.info(f"shard {shard}/{shards}: running {len(examples)} examples.")

    # Resolve the per-example hard timeout. Priority:
    #   1. explicit ``per_example_timeout`` arg (None → env default)
    #   2. ``EVAL_PER_EXAMPLE_TIMEOUT`` env var (read at import time)
    #   3. built-in default (60 s)
    eff_timeout = (
        per_example_timeout
        if per_example_timeout is not None
        else _DEFAULT_PER_EXAMPLE_TIMEOUT_SEC
    )
    if eff_timeout > 0 and not _HAVE_SIGALRM:
        logger.warning(
            "evaluate_dataset: per-example watchdog requested "
            f"(timeout={eff_timeout}s) but SIGALRM is unavailable on this "
            "platform — running with no per-example timeout."
        )
    elif eff_timeout > 0:
        logger.info(
            f"evaluate_dataset: per-example wall-clock cap = {eff_timeout}s "
            f"(override via EVAL_PER_EXAMPLE_TIMEOUT env var or "
            f"per_example_timeout= arg)."
        )

    records: List[Dict[str, Any]] = []

    out_fh = None
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        out_fh = open(out, "w", encoding="utf-8")

    # Print the NER-agent feature-flag banner once at startup so the operator
    # can confirm which fixes are active before a long evaluation begins.
    try:
        from ner_agent_auto import print_feature_flags
        print_feature_flags()
    except Exception:
        pass  # banner is informational; never fail eval over it

    t0 = time.time()
    total = len(examples)
    _heartbeat_every = max(1, int(os.getenv("EVAL_HEARTBEAT_EVERY", "1")))
    try:
        for i, ex in enumerate(examples, 1):
            # PRE-record heartbeat: print BEFORE the watchdog call so a hang
            # leaves a "started at HH:MM:SS, record N" line in the log
            # instead of going dark.
            _heartbeat(
                i, total, t0,
                kind="start",
                qid=ex.get("qid"),
                question=ex.get("question") or ex.get("nl_question") or "",
                every=_heartbeat_every,
            )
            rec = _evaluate_one_with_watchdog(ex, timeout_sec=eff_timeout)
            rec["strategy"] = strategy_of(ex)  # perturbation tier (augmented sets)
            records.append(rec)
            # POST-record heartbeat with score + running mean EA + ETA.
            _heartbeat(
                i, total, t0,
                kind="done",
                qid=rec.get("qid"),
                ea=rec.get("ea"),
                em=rec.get("em"),
                psjs=rec.get("psjs"),
                err=rec.get("error"),
                elapsed=rec.get("elapsed_total_sec"),
                records_so_far=records,
                every=_heartbeat_every,
            )

            if verbose:
                logger.info(
                    f"[{i:>4}/{total}] {rec['qid']} "
                    f"diff={rec.get('difficulty')} "
                    f"t={rec.get('elapsed_total_sec', 0)}s "
                    f"EA={rec['ea']} EM={rec['em']} PSJS={rec['psjs']}"
                    + (f"  err={rec['error']}" if rec.get('error') else "")
                )

            if out_fh:
                out_fh.write(json.dumps(_jsonable(rec), ensure_ascii=False) + "\n")
                out_fh.flush()
    finally:
        if out_fh:
            out_fh.close()

    by_difficulty = aggregate_by_difficulty(records)
    all_cell      = by_difficulty["all"]

    return {
        # ── Top-level fields kept for backward compatibility — they
        #    mirror by_difficulty["all"] exactly. ──────────────────────────
        # ``dataset_name`` (when supplied by the eval harness) overrides
        # the hardcoded base label so augmented variants like
        # ``cypherbench_augmented`` show up as a distinct dataset in the
        # aggregated report.
        "dataset":     dataset_name or "cypherbench",
        "n":           all_cell["n"],
        "n_scored":    all_cell["n_scored"],
        "n_errors":    all_cell["n_errors"],
        "ea":          all_cell["ea"]   if all_cell["ea"]   is not None else 0.0,
        "em":          all_cell["em"]   if all_cell["em"]   is not None else 0.0,
        "psjs":        all_cell["psjs"] if all_cell["psjs"] is not None else 0.0,
        "by_difficulty": by_difficulty,
        "elapsed_sec": round(time.time() - t0, 2),
        "records":     records,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 7. JSON-safe serialisation for Neo4j rows
# ──────────────────────────────────────────────────────────────────────────────

def _jsonable(obj: Any) -> Any:
    """Best-effort conversion of arbitrary Neo4j result rows into JSON-safe
    primitives (Node / Relationship / DateTime types fall back to ``repr``).
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    try:
        # Most LangChain Neo4j rows are already plain dicts/lists — but
        # py2neo / neo4j driver objects need a fallback.
        return json.loads(json.dumps(obj))
    except Exception:
        return repr(obj)


# ──────────────────────────────────────────────────────────────────────────────
# 8. CLI
# ──────────────────────────────────────────────────────────────────────────────

def _format_summary(summary: Dict[str, Any]) -> str:
    return (
        "\n══════════════════════ CypherBench Evaluation ══════════════════════\n"
        f"  NER mode             : {summary.get('ner_mode', 'full')}\n"
        f"  Strict-CypherBench   : {summary.get('strict_cypherbench', False)}\n"
        f"  Total examples       : {summary['total']}\n"
        f"  Evaluated            : {summary['evaluated']}\n"
        f"  Execution Accuracy   : {summary['execution_accuracy']:.4f}  "
        f"({summary['ea_correct']} / {summary['evaluated']})\n"
        f"  Execution Match      : {summary['execution_match']:.4f}  "
        f"({summary['em_correct']} / {summary['evaluated']})\n"
        f"  Agent errors         : {summary['agent_errors']}\n"
        f"  Gold-cypher errors   : {summary['gold_errors']}\n"
        f"  Total elapsed (s)    : {summary['elapsed_sec']}\n"
        "════════════════════════════════════════════════════════════════════\n"
    )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Evaluate the t2c agent on CypherBench (Execution Accuracy / Match).",
    )
    ap.add_argument("--dataset", required=True,
                    help="Path to CypherBench test set (.json or .jsonl).")
    ap.add_argument("--out", default=None,
                    help="Optional JSONL file to stream per-example results to.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Evaluate only the first N examples.")
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K,
                    help=f"Tool-selection top-k for ask_auto (default {DEFAULT_TOP_K}).")
    ap.add_argument("--ner-mode", "--mode", dest="mode", default=None,
                    help="Canonical grounding mode (e.g. plan_exec_node_rel). "
                         "Defaults to the VAL_LINK_MODE/AGENT_TYPE/RETRIEVAL_TYPE/"
                         "TOOL_TYPE config axes.")
    ap.add_argument("--skip-failures", action="store_true",
                    help="Exclude errored examples from the denominator "
                         "(default counts them as misses).")
    ap.add_argument("--strict-cypherbench-mode", "--strict-cypherbench",
                    dest="strict_cypherbench", action="store_true",
                    help="Reproduce upstream CypherBench's exact "
                         "execution-accuracy normalisation: no Node/Rel "
                         "structural expansion, no float epsilon, no string "
                         "case-folding, lists sorted as upstream does. "
                         "Use this to reproduce CypherBench's published "
                         "numbers as a sanity check.")
    ap.add_argument("--verbose", action="store_true",
                    help="Stream agent traces and per-example logs.")
    ap.add_argument("--summary-out", default=None,
                    help="Optional path to write the aggregate summary JSON.")
    args = ap.parse_args(argv)

    examples = load_dataset(args.dataset)
    if not examples:
        print("No examples loaded — nothing to evaluate.", file=sys.stderr)
        return 1

    summary = evaluate_dataset_legacy(
        examples      = examples,
        out_path      = args.out,
        top_k         = args.top_k,
        limit         = args.limit,
        skip_failures = args.skip_failures,
        verbose       = args.verbose,
        mode          = args.mode,
        strict_cypherbench = args.strict_cypherbench,
    )

    print(_format_summary(summary))

    if args.summary_out:
        Path(args.summary_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.summary_out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print(f"Summary written to {args.summary_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
