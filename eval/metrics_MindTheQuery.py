#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metrics_MindTheQuery.py
=======================
Evaluate the text-to-Cypher agent against the **Mind-the-Query** test set.

Reference
---------
Repo  : https://github.com/endeavorXx/Mind-the-Query    (Apache-2.0)
Paper : "Mind-the-Query: NL-Cypher Dataset Generation and Validation
        Framework", EMNLP 2025 (Industry Track).

Dataset layout (native release format)
--------------------------------------
Mind-the-Query ships its examples as **JSON arrays** (not JSONL) under a
directory tree::

    Train_Test_Splits/
      Manual/
        {bloom,covid,er,healthcare,wwc}/
          {train,test}/
            <Category>_{train,test}.json     # JSON array of examples
      Automated/
        {bloom50,covid,er,gdsc,healthcare,legis_graph,osm,pole,
         star_wars,twitter_trolls,wwc}/...

Each example is a JSON object with at least these fields::

    {
      "id":            42,
      "unique_id":     "...",
      "NL Question":   "How many ...",
      "Cypher":        "MATCH (...) RETURN ...",   # gold Cypher (always present)
      "result [0/1]":  1,
      "logical [0/1]": 1,
      "source_dataset": "bloom50",
      ...
    }

So the dataset *does* ship a gold Cypher, which means EM and PSJS are
applicable for every example.  EA is computed by executing both the
predicted and gold Cypher against the live Neo4j database — see
``CYPHERBENCH_PATH`` requirements.

Path semantics
--------------
``MINDTHEQUERY_PATH`` in ``eval_config.py`` may point at:

    * a single ``*.json`` file containing a JSON array of examples
    * a directory — in that case we walk it recursively and concatenate
      every ``*_test.json`` file we find (this matches the natural way to
      run the full Manual or Automated test split)

Use the latter form to evaluate a whole graph's test split, e.g.::

    MINDTHEQUERY_PATH = "/path/to/Mind-the-Query/Train_Test_Splits/Manual/bloom/test"

Neo4j graph requirement
-----------------------
Each Mind-the-Query example targets a specific underlying graph
(``source_dataset``: ``bloom50``, ``covid``, ``healthcare``, ...).  The
corresponding Neo4j ``.dump`` files are vendored in the repo under
``Datasets/`` and must be loaded into the live Neo4j instance pointed at
by ``.env`` *before* running the evaluation.  Mind-the-Query examples
mix multiple graphs, so a single Neo4j database can only score the
subset whose graph is currently loaded — gold-Cypher execution will
fail for the rest, and those examples will surface as ``error`` records.

Loading instructions (from upstream repo)::

    neo4j-admin database load --from-path=/path/to/Datasets <name>.dump

The unified harness API exposed here (``evaluate_one``,
``evaluate_dataset``) matches the schema of
:mod:`eval.metrics_CypherBench` and :mod:`eval.metrics_ZOGRASCOPE`.
"""

from __future__ import annotations

import json
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


# ──────────────────────────────────────────────────────────────────────────────
# 1. Field-name handling — Mind-the-Query uses spaces / brackets in keys
# ──────────────────────────────────────────────────────────────────────────────

_QUESTION_KEYS = (
    "NL Question", "nl_question", "question", "natural_language_question", "nl",
)
_CYPHER_KEYS   = (
    "Cypher", "cypher", "gold_cypher", "ground_truth_cypher", "target_cypher",
)
_ID_KEYS       = ("unique_id", "id", "qid", "question_id", "original_index")
_GRAPH_KEYS    = ("source_dataset", "graph", "dataset")


def _first_present(d: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[Any]:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 2. Loader — supports both single JSON file and directory walks
# ──────────────────────────────────────────────────────────────────────────────

def _load_json_array(p: Path) -> List[Dict[str, Any]]:
    """Load a JSON file expected to contain a list of examples."""
    with p.open("r", encoding="utf-8") as fh:
        obj = json.load(fh)
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, dict) and "data" in obj and isinstance(obj["data"], list):
        return [r for r in obj["data"] if isinstance(r, dict)]
    raise ValueError(
        f"Unexpected JSON layout in {p}: expected list or "
        f"{{'data': [...]}} but got {type(obj).__name__}"
    )


def load_dataset(path: str) -> List[Dict[str, Any]]:
    """
    Load a Mind-the-Query test set from *path*.

    Accepts:

    * a single ``*.json`` file (JSON array of examples)
    * a single ``*.jsonl`` file (one example per line — supported for
      convenience even though upstream uses .json)
    * a directory — walked recursively, every ``*_test.json`` file is
      concatenated.  This matches running e.g. all Complex_* test files
      under ``Train_Test_Splits/Manual/bloom/test/``.

    Returns a list of normalised example dicts with at least
    ``qid`` / ``question`` / ``cypher``.  Examples missing either
    ``NL Question`` or ``Cypher`` are skipped with a warning.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Mind-the-Query dataset not found: {path}\n"
            "Download the repo from https://github.com/endeavorXx/Mind-the-Query "
            "and point eval_config.MINDTHEQUERY_PATH at one of:\n"
            "    Train_Test_Splits/Manual/<graph>/test/\n"
            "    Train_Test_Splits/Manual/<graph>/test/<Category>_test.json\n"
            "    Train_Test_Splits/Automated/<graph>/test/"
        )

    raw: List[Dict[str, Any]] = []
    if p.is_dir():
        files = sorted(p.rglob("*_test.json"))
        if not files:
            # Fallback — accept any *.json under the directory.
            files = sorted(p.rglob("*.json"))
        if not files:
            raise FileNotFoundError(
                f"No *.json test files found under directory {path}.\n"
                "Mind-the-Query test files are named '<Category>_test.json' — "
                "did you point at a 'test/' directory?"
            )
        for f in files:
            try:
                raw.extend(_load_json_array(f))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Skipping malformed Mind-the-Query file {f}: {exc}")
    elif p.suffix.lower() == ".jsonl":
        with p.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        raw.append(obj)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        f"Skipping malformed JSONL line {line_no} in {p}: {exc}"
                    )
    else:
        raw = _load_json_array(p)

    examples: List[Dict[str, Any]] = []
    for i, row in enumerate(raw):
        question = _first_present(row, _QUESTION_KEYS)
        cypher   = _first_present(row, _CYPHER_KEYS)
        if not question or not cypher:
            logger.warning(
                f"Mind-the-Query example #{i} missing question/cypher — "
                f"skipping. Keys present: {list(row.keys())}"
            )
            continue
        examples.append({
            "qid":      str(_first_present(row, _ID_KEYS) or f"mtq_{i}"),
            "question": str(question),
            "cypher":   str(cypher),
            "graph":    _first_present(row, _GRAPH_KEYS),
            "raw":      row,
        })

    logger.info(f"Loaded {len(examples)} Mind-the-Query examples from {path}")
    return examples


# ──────────────────────────────────────────────────────────────────────────────
# 3. Gold-Cypher execution + EA helper (mirrors metrics_CypherBench)
# ──────────────────────────────────────────────────────────────────────────────

# Default normalize_result_set kwargs — same intent as
# metrics_CypherBench._DEFAULT_NORMALIZE_KW but kept local so this module
# is independently usable.
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
    """Run *cypher* against the live Neo4j graph; return ``(rows, error)``."""
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
    """Multiset (order-insensitive) match between two normalised result sets."""
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
    Evaluate the agent on a single Mind-the-Query example.

    Mind-the-Query always ships a gold Cypher, so EM and PSJS are always
    applicable.  Returns ``None`` for any metric that could not be
    computed (e.g. agent error → EA = None).

    Returns
    -------
    dict
        ``{"qid", "question", "ea", "em", "psjs", "pred_cypher",
           "gold_cypher", "graph", "error"}``.
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
        # EM is purely string-based and still computable.
        record["em"] = _literal_exact_match("", gold_cypher)
        return record

    # EM is always computable (literal string).
    record["em"] = _literal_exact_match(pred_cypher, gold_cypher)

    # ── Step 2: gold execution (for EA) ──────────────────────────────────────
    gold_rows, gold_err = _execute_cypher(gold_cypher) if gold_cypher else (None, "no gold cypher")
    if gold_err is not None:
        # The most likely cause is "graph not loaded" — surface a clear message.
        record["error"] = (
            f"gold: {gold_err}  (Mind-the-Query example targets graph "
            f"'{graph_name}'; ensure that .dump is loaded into the Neo4j "
            f"database referenced by .env — see "
            f"https://github.com/endeavorXx/Mind-the-Query Datasets/)"
        )
        return record

    # ── Step 3: EA + PSJS ────────────────────────────────────────────────────
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
    """Best-effort coercion of Neo4j result types into JSON primitives."""
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
    path:    str,
    limit:   Optional[int] = None,
    out:     Optional[str] = None,
    verbose: bool          = False,
) -> Dict[str, Any]:
    """
    Run :func:`evaluate_one` over the Mind-the-Query examples at *path*.

    See module docstring for accepted ``path`` shapes (single JSON file
    or directory).

    Returns
    -------
    dict
        ``{
            "dataset":     "mindthequery",
            "n":           int,
            "n_scored":    {"ea": int, "em": int, "psjs": int},
            "n_errors":    int,
            "ea":          float,
            "em":          float,
            "psjs":        float,
            "elapsed_sec": float,
            "records":     [evaluate_one(...), ...],
        }``
    """
    examples = load_dataset(path)
    if limit is not None:
        examples = examples[:limit]

    records: List[Dict[str, Any]] = []
    n_errors = 0
    n_scored = {"ea": 0, "em": 0, "psjs": 0}
    sums     = {"ea": 0.0, "em": 0.0, "psjs": 0.0}

    out_fh = None
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        out_fh = open(out, "w", encoding="utf-8")

    t0 = time.time()
    try:
        for i, ex in enumerate(examples, 1):
            try:
                rec = evaluate_one(ex)
            except Exception as exc:  # noqa: BLE001
                rec = {
                    "qid":         ex.get("qid", f"mtq_{i}"),
                    "question":    ex.get("question", ""),
                    "ea":          None,
                    "em":          None,
                    "psjs":        None,
                    "pred_cypher": "",
                    "gold_cypher": ex.get("cypher"),
                    "graph":       ex.get("graph"),
                    "error":       f"harness: {type(exc).__name__}: {exc}",
                }
                if verbose:
                    logger.error(traceback.format_exc())

            records.append(rec)
            if rec.get("error"):
                n_errors += 1
            for key in ("ea", "em", "psjs"):
                v = rec.get(key)
                if v is None:
                    continue
                n_scored[key] += 1
                sums[key] += float(v)

            if verbose:
                logger.info(
                    f"[{i:>4}/{len(examples)}] {rec['qid']} "
                    f"EA={rec['ea']} EM={rec['em']} PSJS={rec['psjs']}"
                    + (f"  err={rec['error']}" if rec.get('error') else "")
                )

            if out_fh:
                out_fh.write(json.dumps(_jsonable(rec), ensure_ascii=False) + "\n")
                out_fh.flush()
    finally:
        if out_fh:
            out_fh.close()

    means = {
        k: (sums[k] / n_scored[k]) if n_scored[k] else 0.0
        for k in ("ea", "em", "psjs")
    }
    return {
        "dataset":     "mindthequery",
        "n":           len(examples),
        "n_scored":    n_scored,
        "n_errors":    n_errors,
        "ea":          means["ea"],
        "em":          means["em"],
        "psjs":        means["psjs"],
        "elapsed_sec": round(time.time() - t0, 2),
        "records":     records,
    }
