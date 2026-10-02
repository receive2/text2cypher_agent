#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/node_set_match.py
======================
Execution accuracy for gold queries that return a whole node.

The problem
-----------
A gold query such as ``MATCH (x0:Crime)-[:OCCURRED_AT]-(x1:Location WHERE ...)
RETURN x0`` answers "which crimes ..." with the Crime nodes themselves. The
systems under test are told to answer such questions with a scalar property
(``RETURN DISTINCT c.id``), and the value comparison of the scorers can never
call a property equal to a node. Every such question was therefore scored
wrong for every method, whatever the query selected: 518 of the 1,283
ZOGRASCOPE (pole) questions and 5 Mind-the-Query (bloom) questions in the
released benchmark; CypherBench has none.

The rule (``RULE``)
-------------------
When the gold query returns one node variable and the value comparison says
"different", the prediction is judged on the **set of nodes it selects**:

* the prediction must return that node, or properties of ONE node variable
  (``v``, ``v.p``, ``v.p AS a``, several ``v.*`` columns);
* it is executed again with its RETURN clause projected onto that variable —
  ``RETURN DISTINCT v``, or, when it limits its result, ``RETURN [DISTINCT] v
  ORDER BY ... [SKIP n] LIMIT n`` with its own ordering;
* it is correct iff the set of nodes it returns equals the set of gold nodes.

Anything else keeps the value verdict: a prediction that returns an
aggregate, an expression, columns of two variables, a UNION, or whose
projected query fails. The rule can only turn a "wrong" into a "correct"; it
never changes a verdict the value comparison already accepted.

Records carry both verdicts: ``ea`` (final) and ``ea_strict`` (the value
comparison alone). A record of a node-returning gold query whose ``ea`` is
False and that has no ``ea_strict`` was judged before this rule existed — see
:func:`is_stale` and ``scripts/rejudge_node_returns.py``.

Everything here except :func:`node_set_verdict`'s ``execute`` callback is
pure string work, so it is importable without a database or the agent.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cypher_eval_normalize import _is_neo4j_node, normalize_result_set

RULE = "node-set-v1"

# How node property maps are compared — the scorers' own defaults (metrics_ZOGRASCOPE /
# metrics_MindTheQuery ``_DEFAULT_NORMALIZE_KW``).
_NORMALIZE_KW: Dict[str, Any] = {
    "float_eps":                1e-6,
    "sort_collections":         True,
    "expand_nodes":             True,
    "expand_relationships":     True,
    "case_insensitive_strings": True,
    "compare_keys":             False,
    "compare_column_order":     False,
}

_IDENT = r"[A-Za-z_]\w*"
_COLUMN = re.compile(rf"({_IDENT})(?:\s*\.\s*({_IDENT}))?")
_ALIAS = re.compile(rf"^(?P<expr>.+?)\s+AS\s+(?P<alias>{_IDENT}|`[^`]+`)\s*$", re.I | re.S)

Executor = Callable[[str], Tuple[Optional[List[Any]], Optional[str]]]


# ──────────────────────────────────────────────────────────────────────────────
# Query text helpers
# ──────────────────────────────────────────────────────────────────────────────

def _mask(cypher: str) -> Tuple[str, str]:
    """``(clean, masked)`` — two same-length copies of *cypher*: *clean* has its
    comments blanked; *masked* has, in addition, the inside of string literals
    and backtick identifiers replaced by ``_``, so that a keyword search cannot
    hit text inside them."""
    clean, masked = list(cypher), list(cypher)
    i, n = 0, len(cypher)
    while i < n:
        ch = cypher[i]
        if ch in "'\"`":
            j = i + 1
            while j < n:
                if cypher[j] == "\\" and ch != "`" and j + 1 < n:      # backslash escape
                    masked[j] = masked[j + 1] = "_"
                    j += 2
                    continue
                if cypher[j] == ch:
                    if j + 1 < n and cypher[j + 1] == ch:               # doubled quote = escaped quote
                        masked[j] = masked[j + 1] = "_"
                        j += 2
                        continue
                    break
                masked[j] = "_"
                j += 1
            i = j + 1
        elif cypher.startswith("//", i) or cypher.startswith("/*", i):
            if cypher.startswith("//", i):
                j = cypher.find("\n", i)
                j = n if j < 0 else j
            else:
                j = cypher.find("*/", i + 2)
                j = n if j < 0 else j + 2
            for k in range(i, j):
                clean[k] = masked[k] = " "
            i = j
        else:
            i += 1
    return "".join(clean), "".join(masked)


def _depths(masked: str) -> List[int]:
    """Bracket depth in front of every character of a masked query."""
    depth, out = 0, []
    for ch in masked:
        out.append(depth)
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
    return out


def _top_level(pattern: str, masked: str, depths: List[int]) -> List[re.Match]:
    return [m for m in re.finditer(pattern, masked, flags=re.I) if depths[m.start()] == 0]


def _split_columns(text: str, masked: str) -> List[str]:
    depths = _depths(masked)
    cols, start = [], 0
    for i, ch in enumerate(masked):
        if ch == "," and depths[i] == 0:
            cols.append(text[start:i])
            start = i + 1
    cols.append(text[start:])
    return [c.strip() for c in cols]


class _Return:
    """The final RETURN clause of a query, taken apart."""
    __slots__ = ("head", "distinct", "columns", "order", "skip", "limit")

    def __init__(self, head: str, distinct: bool, columns: List[str],
                 order: Optional[str], skip: Optional[str], limit: Optional[str]) -> None:
        self.head, self.distinct, self.columns = head, distinct, columns
        self.order, self.skip, self.limit = order, skip, limit


def _parse_return(cypher: Optional[str]) -> Optional[_Return]:
    """Split *cypher* at its last top-level RETURN. ``None`` when there is none, or
    when the query is a UNION (one RETURN per branch — not handled)."""
    if not cypher or not cypher.strip():
        return None
    text = cypher.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    text, masked = _mask(text)
    depths = _depths(masked)
    if _top_level(r"\bUNION\b", masked, depths):
        return None
    rets = _top_level(r"\bRETURN\b", masked, depths)
    if not rets:
        return None
    cut = rets[-1]
    head, tail, tail_masked = text[:cut.start()], text[cut.end():], masked[cut.end():]
    tail_depths = _depths(tail_masked)

    def first(pattern: str) -> Optional[re.Match]:
        hits = _top_level(pattern, tail_masked, tail_depths)
        return hits[0] if hits else None

    order, skip, limit = first(r"\bORDER\s+BY\b"), first(r"\bSKIP\b"), first(r"\bLIMIT\b")
    marks = sorted((m for m in (order, skip, limit) if m), key=lambda m: m.start())

    def body(m: Optional[re.Match]) -> Optional[str]:
        if m is None:
            return None
        later = [x.start() for x in marks if x.start() > m.start()]
        return tail[m.end():(later[0] if later else len(tail))].strip() or None

    proj_end = marks[0].start() if marks else len(tail)
    proj, proj_masked = tail[:proj_end], tail_masked[:proj_end]
    lead = len(proj) - len(proj.lstrip())
    proj, proj_masked = proj[lead:].rstrip(), proj_masked[lead:].rstrip()
    distinct = re.match(r"DISTINCT\b", proj_masked, flags=re.I)
    if distinct:
        proj, proj_masked = proj[distinct.end():], proj_masked[distinct.end():]
    columns = _split_columns(proj, proj_masked)
    if not columns or any(not c for c in columns):
        return None
    return _Return(head, bool(distinct), columns, body(order), body(skip), body(limit))


def _column(col: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """``(variable, property, alias)`` of a ``v`` / ``v.p`` [``AS a``] column, else ``None``."""
    alias = None
    m = _ALIAS.match(col)
    if m:
        col, alias = m.group("expr").strip(), m.group("alias").strip("`")
    m = _COLUMN.fullmatch(col.strip())
    if not m:
        return None
    return m.group(1), m.group(2), alias


def _binds_node(head: str, var: str) -> bool:
    """Is *var* introduced as a node in a pattern of *head* — ``(var:Label``,
    ``(var)``, ``(var {``, ``(var WHERE`` — and not as an alias (``... AS var``)?"""
    masked = _mask(head)[1]
    v = re.escape(var)
    if re.search(rf"\bAS\s+{v}\b", masked, flags=re.I):
        return False
    return bool(re.search(rf"\(\s*{v}\s*(?::|\)|\{{|WHERE\b)", masked, flags=re.I))


def gold_node_var(gold_cypher: Optional[str]) -> Optional[str]:
    """The node variable when *gold_cypher* returns exactly one whole node
    (``RETURN [DISTINCT] x [ORDER BY ..] [SKIP n] [LIMIT n]``), else ``None``."""
    ret = _parse_return(gold_cypher)
    if ret is None or len(ret.columns) != 1:
        return None
    col = _column(ret.columns[0])
    if col is None or col[1] is not None:
        return None
    return col[0] if _binds_node(ret.head, col[0]) else None


_WRITES = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV)\b", re.I)


def project_to_node(pred_cypher: Optional[str]) -> Optional[str]:
    """*pred_cypher* with its RETURN clause projected onto the one node variable
    whose properties it returns, or ``None`` when it returns anything else — or
    when it contains a writing clause (such a query is never run again)."""
    ret = _parse_return(pred_cypher)
    if ret is None:
        return None
    if _WRITES.search(_mask(ret.head)[1]):
        return None
    cols = [_column(c) for c in ret.columns]
    if any(c is None for c in cols):
        return None
    variables = {c[0] for c in cols}
    if len(variables) != 1:
        return None
    var = variables.pop()
    if ret.skip is None and ret.limit is None:
        return f"{ret.head}RETURN DISTINCT {var}"          # the order of a set does not matter
    order = ret.order
    if order is not None:
        # ORDER BY may name the alias of a column the projection drops: put the expression back.
        for v, prop, alias in cols:
            if not alias or alias == var:
                continue
            target = f"{v}.{prop}" if prop else v
            hits = list(re.finditer(rf"(?<![\w.`]){re.escape(alias)}(?![\w(`])", _mask(order)[1]))
            for m in reversed(hits):
                order = order[:m.start()] + target + order[m.end():]
    out = f"{ret.head}RETURN {'DISTINCT ' if ret.distinct else ''}{var}"
    if order is not None:
        out += f" ORDER BY {order}"
    if ret.skip is not None:
        out += f" SKIP {ret.skip}"
    if ret.limit is not None:
        out += f" LIMIT {ret.limit}"
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Result helpers + the verdict
# ──────────────────────────────────────────────────────────────────────────────

def _nodes(rows: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
    """The property maps of a one-column result whose every cell is a node, else ``None``.
    (``Record.data()`` — what LangChain's ``Neo4jGraph.query`` and ``safe_cypher_run``
    return — turns a node into the plain dict of its properties.)"""
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            cells = list(row.values())
        elif isinstance(row, (list, tuple)):
            cells = list(row)
        else:
            return None
        if len(cells) != 1:
            return None
        cell = cells[0]
        if _is_neo4j_node(cell):
            cell = dict(cell.items())
        if not isinstance(cell, dict):
            return None
        out.append(cell)
    return out


def _signatures(nodes: List[Dict[str, Any]]) -> set:
    return set(normalize_result_set([{"n": n} for n in nodes], **_NORMALIZE_KW))


def node_set_verdict(pred_cypher: Optional[str], gold_cypher: Optional[str],
                     gold_rows: Optional[List[Any]], execute: Executor) -> Optional[bool]:
    """The node-set verdict for one question, or ``None`` when the rule does not
    apply (the gold does not return a node, the prediction does not return
    properties of one variable, or its projected query does not run).

    *execute* runs a Cypher statement and returns ``(rows, error)``."""
    if gold_node_var(gold_cypher) is None:
        return None
    gold_nodes = _nodes(gold_rows)
    if gold_nodes is None:
        return None
    projected = project_to_node(pred_cypher)
    if projected is None:
        return None
    rows, err = execute(projected)
    if err is not None or rows is None:
        return None
    pred_nodes = _nodes(rows)
    if pred_nodes is None:
        return None
    return _signatures(pred_nodes) == _signatures(gold_nodes)


def judge(strict: Optional[bool], pred_cypher: Optional[str], gold_cypher: Optional[str],
          gold_rows: Optional[List[Any]], execute: Executor) -> Optional[bool]:
    """Final EA from the value verdict *strict*: unchanged unless it is False and the
    node-set rule accepts the prediction."""
    if strict is not False:
        return strict
    try:
        return node_set_verdict(pred_cypher, gold_cypher, gold_rows, execute) is True
    except Exception:  # noqa: BLE001 — a query this module cannot take apart keeps its value verdict
        return False


def is_stale(record: Dict[str, Any]) -> bool:
    """Was this record's "wrong" decided before the node-set rule existed? True for a
    False ``ea`` on a node-returning gold query with no ``ea_strict`` next to it."""
    return (record.get("ea") is False and "ea_strict" not in record
            and gold_node_var(record.get("gold_cypher")) is not None)


def stale_count(records: List[Dict[str, Any]]) -> int:
    return sum(1 for r in records if is_stale(r))


def strict_value(record: Dict[str, Any]) -> Any:
    """The value-comparison verdict of a record (``ea_strict`` when recorded, else ``ea``)."""
    return record["ea_strict"] if "ea_strict" in record else record.get("ea")


def capped_executor(graph: Any, timeout: float = 60.0) -> Executor:
    """An executor over a LangChain ``Neo4jGraph``-like object. With a reachable
    driver the statement runs under a server-side transaction timeout; without
    one it falls back to ``graph.query``."""
    def run(cypher: str) -> Tuple[Optional[List[Any]], Optional[str]]:
        if not cypher or not cypher.strip():
            return None, "empty cypher"
        try:
            driver = getattr(graph, "_driver", None)
            if driver is not None:
                from neo4j_lib.safe_query import safe_cypher_run
                return list(safe_cypher_run(driver, cypher, params=None, timeout=float(timeout),
                                            database=getattr(graph, "_database", None)) or []), None
            return list(graph.query(cypher) or []), None
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"
    return run
