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
from config import DEFAULT_TOP_K, NER_MODE, NER_MODES
from .cypher_eval_normalize import (
    normalize_result_set,
    column_counts_match,
    strict_cypherbench_kwargs,
)
from .exact_match import exact_match as _literal_exact_match
from .psjs import compute_psjs as _compute_psjs
from .difficulty import classify as _classify_difficulty, aggregate_by_difficulty


# ──────────────────────────────────────────────────────────────────────────────
# 1. Dataset loading
# ──────────────────────────────────────────────────────────────────────────────

# CypherBench releases the test set as JSON / JSONL.  Different snapshots
# have used slightly different field names — we accept the common variants.
_QUESTION_KEYS = ("nl_question", "question", "natural_language_question", "nl")
_CYPHER_KEYS   = ("gold_cypher", "cypher", "target_cypher", "ground_truth_cypher")
_ANSWER_KEYS   = ("answer", "gold_answer", "expected_answer", "result")
_ID_KEYS       = ("qid", "id", "question_id", "gid")


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
            "raw":      row,
        })

    logger.info(f"Loaded {len(examples)} examples from {path}")
    return examples


# ──────────────────────────────────────────────────────────────────────────────
# 2. Gold-Cypher execution
# ──────────────────────────────────────────────────────────────────────────────

def execute_cypher(cypher: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Run *cypher* against the live Neo4j database via ``agent_helper.neo4j_graph``.

    Returns
    -------
    (rows, error)
        On success ``rows`` is a list of dicts (LangChain Neo4jGraph output)
        and ``error`` is ``None``.  On failure ``rows`` is ``None`` and
        ``error`` carries the exception's string form.
    """
    if not cypher or not cypher.strip():
        return None, "empty cypher"
    try:
        rows = neo4j_graph.query(cypher)
        # ``Neo4jGraph.query`` already returns a list of dicts; normalise to that.
        if rows is None:
            return [], None
        return list(rows), None
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
        "ner_mode":         mode or NER_MODE,
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
                    Defaults to :data:`config.NER_MODE`.

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
    if mode is not None and mode not in NER_MODES:
        raise ValueError(
            f"Unknown NER mode {mode!r}. Expected one of {NER_MODES}."
        )

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
        "ner_mode":            mode or NER_MODE,
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

    record: Dict[str, Any] = {
        "qid":         qid,
        "question":    question,
        "ea":          None,
        "em":          None,
        "psjs":        None,
        "pred_cypher": "",
        "gold_cypher": gold_cypher,
        "difficulty":  _classify_difficulty(gold_cypher),
        "error":       None,
    }

    # ── Step 1: agent prediction ────────────────────────────────────────────
    try:
        out = ask_auto(prompt=question)
        pred_cypher = out.get("cypher", "") or ""
        pred_rows   = out.get("context", []) or []
        record["pred_cypher"] = pred_cypher
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"agent: {type(exc).__name__}: {exc}"
        return record

    # ── Step 2: gold execution ───────────────────────────────────────────────
    gold_rows, gold_err = execute_cypher(gold_cypher) if gold_cypher else (None, "no gold cypher")
    if gold_err is not None:
        record["error"] = f"gold: {gold_err}"
        # We can still compute EM since it is purely string-based.
        record["em"] = _literal_exact_match(pred_cypher, gold_cypher)
        return record

    # ── Step 3: metrics ──────────────────────────────────────────────────────
    try:
        record["ea"] = execution_accuracy(pred_rows, gold_rows, gold_cypher=gold_cypher)
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"ea: {type(exc).__name__}: {exc}"

    record["em"] = _literal_exact_match(pred_cypher, gold_cypher)

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

    return record


def evaluate_dataset(
    path:    str,
    limit:   Optional[int] = None,
    out:     Optional[str] = None,
    verbose: bool          = False,
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
            "elapsed_sec": float,
            "records":    [evaluate_one(...), ...],
        }``
    """
    examples = load_dataset(path)
    if limit is not None:
        examples = examples[:limit]

    records: List[Dict[str, Any]] = []

    out_fh = None
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        out_fh = open(out, "w", encoding="utf-8")

    t0 = time.time()
    try:
        for i, ex in enumerate(examples, 1):
            rec = evaluate_one(ex)
            records.append(rec)

            if verbose:
                logger.info(
                    f"[{i:>4}/{len(examples)}] {rec['qid']} "
                    f"diff={rec.get('difficulty')} "
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
        "dataset":     "cypherbench",
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
    ap.add_argument("--ner-mode", "--mode", dest="mode",
                    choices=NER_MODES, default=None,
                    help=f"NER pipeline mode (overrides config.NER_MODE={NER_MODE!r}). "
                         f"One of {NER_MODES}.  "
                         "'full' uses all tools, 'node_only' drops relation "
                         "tools, 'no_ner' bypasses the agent entirely.")
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
