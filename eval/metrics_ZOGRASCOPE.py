#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metrics_ZOGRASCOPE.py
=====================
Evaluate the text-to-Cypher agent against the **ZOGRASCOPE** test set.

Reference
---------
Repo  : https://github.com/interact-erc/ZOGRASCOPE     (CC BY 4.0)
Paper : "ZOGRASCOPE: A New Benchmark for Semantic Parsing over Property
        Graphs", arXiv:2503.05268.

Dataset layout (native release format)
--------------------------------------
ZOGRASCOPE ships its examples as **CSV files** (not JSONL/JSON).  The
relevant files in the upstream repo's ``data/`` directory are::

    data/zograscope_train_v1.csv
    data/zograscope_test_v1.csv          ← default eval target
    data/zograscope_length_train_v1.csv
    data/zograscope_length_test_v1.csv
    data/ids_iid_test.txt                ← partition: iid examples
    data/ids_compositional_test.txt      ← partition: compositional examples

Each CSV row contains (at least) the following columns::

    id              — example id (also referenced by the partition .txt files)
    nl              — natural-language question
    mr              — gold Cypher query (the "meaning representation")
    nl_gold_linked  — NL with grounded entities
    nl_bracketed    — NL with entity text replaced by brackets
    entities        — extracted entity list
    num_nodes       — node count in the gold Cypher
    template_id     — anonymised query template
    type            — query classification
    return_count    — number of return values

Path semantics
--------------
``ZOGRASCOPE_PATH`` in ``eval_config.py`` may point at:

    * a single ``*.csv`` file (e.g. ``data/zograscope_test_v1.csv``)
    * a directory containing ``zograscope_test_v1.csv`` (we'll find it
      automatically)

The default test split mixes the iid and compositional partitions; if
you want to score only one, slice the CSV upstream or filter the
returned ``records`` list by partition file membership after the run.

Neo4j graph requirement
-----------------------
ZOGRASCOPE targets a single graph — the **POLE** crime-investigation
property graph (61 521 nodes, 105 840 edges, 11 entity classes,
32 properties, 17 relations).  Multiple Neo4j-version dumps are bundled
in the repo's ``graph/`` directory::

    graph/pole-35.dump   — Neo4j 3.5
    graph/pole-40.dump   — Neo4j 4.0
    graph/pole-43.dump   — Neo4j 4.3
    graph/pole-50.dump   — Neo4j 5.x       ← recommended (matches t2c stack)
    graph/pole-data-importer.zip
    graph/pole.zip

Restore the matching dump into the live Neo4j instance pointed at by
``.env`` *before* running the harness, e.g.::

    neo4j-admin database load --from-path=/path/to/ZOGRASCOPE/graph pole-50.dump

If the graph isn't loaded, gold-Cypher execution will fail and every
example will surface as an ``error`` record.

The unified harness API exposed here (``evaluate_one``,
``evaluate_dataset``) matches the schema of
:mod:`eval.metrics_CypherBench` and :mod:`eval.metrics_MindTheQuery`.
"""

from __future__ import annotations

import csv
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from agent.agent_helper import neo4j_graph
from ner_agent_auto import ask_auto

from .cypher_eval_normalize import (
    normalize_result_set,
    column_counts_match,
)
from .exact_match import exact_match as _literal_exact_match
from .psjs import compute_psjs as _compute_psjs
from .difficulty import (
    classify as _classify_difficulty,
    aggregate_by_difficulty,
    aggregate_by_strategy,
    strategy_of,
)
# Reuse the timestamped progress heartbeat from the CypherBench driver so the
# log format is identical across all three eval entry points.
from .metrics_CypherBench import _heartbeat as _heartbeat_cb


# ──────────────────────────────────────────────────────────────────────────────
# 1. Field-name constants
# ──────────────────────────────────────────────────────────────────────────────

_QUESTION_COLS = ("nl", "question", "NL Question", "nl_gold_linked")
_CYPHER_COLS   = ("mr", "cypher", "gold_cypher", "Cypher")
_ID_COLS       = ("id", "qid", "question_id")


def _first_present_col(row: Dict[str, Any], cols: Tuple[str, ...]) -> Optional[Any]:
    for c in cols:
        v = row.get(c)
        if v is not None and v != "":
            return v
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 2. Loader — CSV (with directory-walk convenience)
# ──────────────────────────────────────────────────────────────────────────────

# Increase CSV field-size limit because some Cypher queries in ZOGRASCOPE
# can be very long (multi-clause MATCH chains).
try:
    csv.field_size_limit(2**24)
except OverflowError:  # pragma: no cover
    csv.field_size_limit(2**20)


def _resolve_csv_path(p: Path) -> Path:
    """If *p* is a directory, look for the canonical test CSV inside it."""
    if p.is_file():
        return p
    if p.is_dir():
        for candidate in (
            "zograscope_test_v1.csv",
            "data/zograscope_test_v1.csv",
        ):
            cand_path = p / candidate
            if cand_path.is_file():
                return cand_path
        # Fallback: any *_test*.csv at the top level.
        candidates = sorted(p.glob("*_test*.csv"))
        if candidates:
            return candidates[0]
    raise FileNotFoundError(
        f"ZOGRASCOPE test CSV not found at {p}. Expected either the file "
        "'zograscope_test_v1.csv' directly or a directory containing it. "
        "Get the data from https://github.com/interact-erc/ZOGRASCOPE "
        "(data/zograscope_test_v1.csv)."
    )


def load_dataset(path: str) -> List[Dict[str, Any]]:
    """
    Load a ZOGRASCOPE test set from *path*.

    *path* may point at a CSV file directly, or at a directory containing
    ``zograscope_test_v1.csv`` (or any ``*_test*.csv`` fallback).

    Returns
    -------
    list[dict]
        Each example has at minimum ``qid``, ``question``, ``cypher``,
        plus the original CSV row under ``raw``.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"ZOGRASCOPE dataset path does not exist: {path}\n"
            "Clone https://github.com/interact-erc/ZOGRASCOPE and point "
            "eval_config.ZOGRASCOPE_PATH at data/zograscope_test_v1.csv "
            "(or the parent directory)."
        )

    csv_path = _resolve_csv_path(p)
    examples: List[Dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            question = _first_present_col(row, _QUESTION_COLS)
            cypher   = _first_present_col(row, _CYPHER_COLS)
            if not question or not cypher:
                logger.warning(
                    f"ZOGRASCOPE row #{i} missing nl/mr columns — skipping. "
                    f"Columns present: {list(row.keys())}"
                )
                continue
            examples.append({
                "qid":      str(_first_present_col(row, _ID_COLS) or f"zg_{i}"),
                "question": str(question),
                "cypher":   str(cypher),
                "raw":      row,
            })

    logger.info(f"Loaded {len(examples)} ZOGRASCOPE examples from {csv_path}")
    return examples


# ──────────────────────────────────────────────────────────────────────────────
# 3. Cypher execution + EA helper
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_NORMALIZE_KW: Dict[str, Any] = {
    "float_eps":                1e-6,
    "sort_collections":         True,
    "expand_nodes":             True,
    "expand_relationships":     True,
    "case_insensitive_strings": True,
    "compare_keys":             False,
    "compare_column_order":     False,
}


def _execute_cypher(cypher: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    if not cypher or not cypher.strip():
        return None, "empty cypher"
    try:
        rows = neo4j_graph.query(cypher)
        return list(rows or []), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _execution_accuracy(
    pred_rows: List[Any],
    gold_rows: List[Any],
    *,
    gold_cypher: Optional[str] = None,
) -> bool:
    from collections import Counter
    if not column_counts_match(pred_rows, gold_rows):
        return False
    p = normalize_result_set(pred_rows, gold_cypher=gold_cypher, **_DEFAULT_NORMALIZE_KW)
    g = normalize_result_set(gold_rows, gold_cypher=gold_cypher, **_DEFAULT_NORMALIZE_KW)
    return Counter(p) == Counter(g)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Per-example evaluation
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_one(example: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate the agent on a single ZOGRASCOPE example.

    ZOGRASCOPE always ships a gold Cypher (column ``mr``), so EM and
    PSJS are always applicable.

    Returns
    -------
    dict
        ``{"qid", "question", "ea", "em", "psjs", "pred_cypher",
           "gold_cypher", "graph", "difficulty", "error"}``.

        ``graph`` is hardcoded to ``"pole"`` — ZOGRASCOPE targets the
        single POLE crime-investigation property graph.  The field is
        present so per-graph filtering and downstream aggregation
        round-trip cleanly with the other two datasets.  ``difficulty``
        is one of ``"easy"`` / ``"medium"`` / ``"hard"`` /
        ``None`` and is computed from the gold Cypher by
        :mod:`eval.difficulty`.
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
        "graph":       "pole",
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
        record["em"] = _literal_exact_match("", gold_cypher)
        return record

    record["em"] = _literal_exact_match(pred_cypher, gold_cypher)

    # ── Step 2: gold execution ──────────────────────────────────────────────
    gold_rows, gold_err = _execute_cypher(gold_cypher) if gold_cypher else (None, "no gold cypher")
    if gold_err is not None:
        record["error"] = (
            f"gold: {gold_err}  (ZOGRASCOPE targets the POLE graph; ensure "
            f"graph/pole-50.dump from "
            f"https://github.com/interact-erc/ZOGRASCOPE is loaded into "
            f"the Neo4j database referenced by .env, e.g. "
            f"`neo4j-admin database load --from-path=<repo>/graph pole-50.dump`)"
        )
        return record

    # ── Step 3: EA + PSJS ───────────────────────────────────────────────────
    try:
        record["ea"] = _execution_accuracy(pred_rows, gold_rows, gold_cypher=gold_cypher)
    except Exception as exc:  # noqa: BLE001
        record["error"] = f"ea: {type(exc).__name__}: {exc}"

    try:
        record["psjs"] = _compute_psjs(
            pred_cypher, gold_cypher,
            neo4j_graph=neo4j_graph,
            ea_value=record["ea"],
        )
    except Exception as exc:  # noqa: BLE001
        if record["error"] is None:
            record["error"] = f"psjs: {type(exc).__name__}: {exc}"

    return record


# ──────────────────────────────────────────────────────────────────────────────
# 5. Batch evaluation
# ──────────────────────────────────────────────────────────────────────────────

def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    try:
        return json.loads(json.dumps(obj))
    except Exception:
        return repr(obj)


def evaluate_dataset(
    path:         str,
    limit:        Optional[int] = None,
    out:          Optional[str] = None,
    verbose:      bool          = False,
    graph_filter: Optional[str] = None,
    dataset_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run :func:`evaluate_one` over the ZOGRASCOPE test CSV at *path*.

    Parameters
    ----------
    graph_filter
        When set, only examples whose ``graph`` field equals this value
        are kept.  ZOGRASCOPE has exactly one underlying graph
        (``"pole"``), so the only meaningful values are ``None`` (no
        filter) and ``"pole"``; any other value will skip every
        example.  Accepted for API parity with the other two datasets.

    Returns
    -------
    dict
        ``{
            "dataset":     "zograscope",
            "n":           int,
            "n_scored":    {"ea": int, "em": int, "psjs": int},
            "n_errors":    int,
            "ea":          float,
            "em":          float,
            "psjs":        float,
            "by_difficulty": dict,
            "elapsed_sec": float,
            "records":     [evaluate_one(...), ...],
        }``
    """
    examples = load_dataset(path)

    if graph_filter is not None:
        before = len(examples)
        # Every ZOGRASCOPE example targets the POLE graph; the loader
        # doesn't materialise the field on the example dict, so we apply
        # the filter as a constant predicate.  This keeps non-"pole"
        # filters honest (they correctly skip everything).
        examples = examples if graph_filter == "pole" else []
        skipped = before - len(examples)
        logger.info(
            f"ZOGRASCOPE graph_filter={graph_filter!r}: kept "
            f"{len(examples)}/{before} examples (skipped {skipped})."
        )

    if limit is not None:
        examples = examples[:limit]

    records: List[Dict[str, Any]] = []

    out_fh = None
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        out_fh = open(out, "w", encoding="utf-8")

    # Print the NER-agent feature-flag banner once at startup — wrap in
    # try/except so a banner failure can never take down the eval.
    try:
        from ner_agent_auto import print_feature_flags
        print_feature_flags()
    except Exception:
        pass

    t0 = time.time()
    total = len(examples)
    _heartbeat_every = max(1, int(os.getenv("EVAL_HEARTBEAT_EVERY", "1")))
    try:
        for i, ex in enumerate(examples, 1):
            _heartbeat_cb(
                i, total, t0,
                kind="start",
                qid=ex.get("qid"),
                question=ex.get("question") or "",
                every=_heartbeat_every,
            )
            try:
                rec = evaluate_one(ex)
            except Exception as exc:  # noqa: BLE001
                rec = {
                    "qid":         ex.get("qid", f"zg_{i}"),
                    "question":    ex.get("question", ""),
                    "ea":          None,
                    "em":          None,
                    "psjs":        None,
                    "pred_cypher": "",
                    "gold_cypher": ex.get("cypher"),
                    "difficulty":  _classify_difficulty(ex.get("cypher")),
                    "error":       f"harness: {type(exc).__name__}: {exc}",
                }
                if verbose:
                    logger.error(traceback.format_exc())

            rec["strategy"] = strategy_of(ex)  # perturbation tier (augmented sets)
            records.append(rec)
            _heartbeat_cb(
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
        # ``dataset_name`` (when supplied by the eval harness) overrides
        # the hardcoded base label so augmented variants like
        # ``zograscope_augmented`` show up as a distinct dataset in the
        # aggregated report.
        "dataset":     dataset_name or "zograscope",
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
