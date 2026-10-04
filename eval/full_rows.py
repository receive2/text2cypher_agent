#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/full_rows.py
=================
Execution accuracy on the complete result of a prediction.

The problem
-----------
Every method hands the evaluators the rows its final query returned
(``ask_auto(...)["context"]``), and the evaluators compare them with the rows
of the gold query. ReAct and CyANCHOR (``_generate_execute_cypher_with_retry``)
and MA GraphRAG (``graphrag._execute``) execute that query themselves, through
the evaluation executor, and return every row. The methods that end in
LangChain's ``GraphCypherQAChain`` — No Val Link (``METHOD=no_val_link``),
FCAV (``METHOD=fcav``), and ReAct / CyANCHOR run with
``CYPHER_RETRY_MAX_ROUNDS=0`` — returned the chain's ``context`` instead, which
the chain cuts to its ``top_k`` (10) rows for the answer prompt. A correct
query whose result has more than ten rows was therefore scored wrong. PSJS
re-executes the query itself and was not affected, except where it falls back
on the EA verdict.

The rule (``RULE``)
-------------------
A prediction is scored on every row it returns: ``ask_auto`` executes the query
of the chain once more, uncapped, with the evaluation executor (the same one,
and the same timeout, as the other paths). The evaluators stamp every record
they write with ``rows_rule = RULE``. A scored record of a chain run without
that stamp was judged on at most ten rows (:func:`is_stale`);
``scripts/rejudge_full_rows.py`` scores such records again from their stored
predictions — no model is called and no question is re-run — and stamps them.
``orchestrate_sweep`` marks a cell that holds them ↻ and ``--publish`` refuses
it. Records of the other methods never had the problem and are never stale.

Everything here is pure, so it is importable without a database or the agent.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

RULE = "full-rows-v1"

# Methods whose final step is GraphCypherQAChain (ner_agent_auto.ask_auto).
CHAIN_METHODS = ("no_val_link", "fcav")
# Methods that execute their own query unless CYPHER_RETRY_MAX_ROUNDS < 1.
RETRY_METHODS = ("react", "cyanchor")


def method_of(summary: Optional[Dict[str, Any]], dirname: str = "") -> str:
    """The METHOD of a run: from its ``summary.json`` knobs, else from the run
    directory name (``<dataset>__<graph>__<method>[@<model>]__<stamp>``)."""
    knobs = ((summary or {}).get("run_config") or {}).get("knobs") or {}
    method = str(knobs.get("METHOD") or "").strip().lower()
    if method:
        return method
    parts = dirname.split("__")
    if len(parts) >= 3:
        seg = parts[2].split("@")[0].lower()
        return "cyanchor" if seg.startswith("cyanchor") else seg
    return ""


def uses_chain(summary: Optional[Dict[str, Any]], dirname: str = "") -> bool:
    """Did this run end in GraphCypherQAChain? From the knobs stamped into its
    ``summary.json`` when present, else from the method in its directory name."""
    method = method_of(summary, dirname)
    if method in CHAIN_METHODS:
        return True
    if method in RETRY_METHODS:
        knobs = ((summary or {}).get("run_config") or {}).get("knobs") or {}
        try:
            return int(knobs.get("CYPHER_RETRY_MAX_ROUNDS", 1)) < 1
        except (TypeError, ValueError):
            return False
    return False


def is_stale(record: Dict[str, Any]) -> bool:
    """Was this record of a chain run scored on at most ten rows? True for a
    scored record (``ea`` not None) without the ``rows_rule`` stamp."""
    return record.get("ea") is not None and record.get("rows_rule") != RULE


def stale_count(records: List[Dict[str, Any]], chain: bool) -> int:
    """Records of a run to score again (0 for a run that did not use the chain)."""
    return sum(1 for r in records if is_stale(r)) if chain else 0
