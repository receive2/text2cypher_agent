#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
psjs.py
=======
Provenance Subgraph Jaccard Similarity (PSJS) for text-to-Cypher evaluation.

Source of the implementation
----------------------------
This module ports the **CypherBench reference implementation** of PSJS at::

    https://github.com/megagonlabs/cypherbench
        cypherbench/metrics/provenance_subgraph_jaccard_similarity.py

with two deliberate deviations driven by the evaluation harness spec:

    1. **Combined node + relationship IDs.**  The reference impl is
       ``node_element_id_only=True`` for its actual PSJS metric — only
       node ``elementId``s are compared (relationships are tracked only
       in the unused visualisation branch).  Per the user-supplied spec
       ("PSJS is |P_pred ∩ P_gold| / |P_pred ∪ P_gold| over the combined
       node+relationship ID set"), we collect *both* sets and union them
       before computing Jaccard.

    2. **Different fallback when a query cannot be rewritten.**
       Reference impl emits an empty provenance set in that case,
       which yields PSJS = 0.0 on both empty sets (U = 0).  Per the
       harness spec ("If a query cannot be rewritten to expose its
       provenance (e.g. pure aggregation with no traversal), fall back
       to PSJS = 1.0 if EA is true and 0.0 otherwise, and log the
       fallback") we use Execution Accuracy as the tiebreaker.  Callers
       pass in ``ea_value`` and we honour it; if ``ea_value`` is None we
       return None.

The query-rewriting logic — ``split_by_union``, ``split_cypher_into_clauses``,
``extract_match_cypher``, ``add_variables``, ``extract_node_variables``,
``extract_relationship_variables``, ``get_ps_cypher`` — is a faithful port
of the reference and behaves identically modulo the two deviations above.

Reference paper
---------------
Feng, Y. et al. (2024). *CypherBench: Towards Precise Retrieval over
Full-scale Modern Knowledge Graphs in the LLM Era*.  arXiv:2412.18702.

elementId() vs id()
-------------------
Neo4j 5.x exposes the stable, string-typed ``elementId(n)``.  Older
Neo4j 4.x deployments only expose the integer ``id(n)``, which is also
stable within a single transaction.  We try ``elementId`` first and fall
back to ``id`` on failure (controlled by ``element_id_first=True``).

Public API
----------
    rewrite_for_provenance(cypher) -> Optional[str]
        Returns the rewritten Cypher query that, when executed, yields a
        single column of node + relationship element IDs touched by the
        original query.  Returns ``None`` if the query cannot be
        rewritten (no MATCH clause, e.g. pure aggregations or
        ``RETURN``-only queries).

    compute_psjs(pred_cypher, gold_cypher, *, neo4j_graph,
                 ea_value=None, timeout=120) -> Optional[float]
        Executes the rewritten predicted and gold queries against
        *neo4j_graph* (a ``langchain_neo4j.Neo4jGraph``-like object with a
        ``.query(cypher)`` method) and returns the Jaccard similarity in
        [0, 1].  Returns the ``ea_value`` fallback when rewriting fails;
        ``None`` if EA is also unavailable.  Identical predicted == gold
        short-circuits to 1.0 (matches the reference impl).
"""

from __future__ import annotations

import os
import re
from typing import Any, List, Optional, Set, Tuple

from loguru import logger

from neo4j_lib.safe_query import (
    TransactionTimedOutError,
    safe_cypher_run,
)


# ──────────────────────────────────────────────────────────────────────────────
# Timeout-classification helper
#
# ``safe_query.TransactionTimedOutError`` is the tuple
# ``(TransientError, ClientError)`` because the Neo4j 5.x server raises
# timeouts as one or the other depending on version.  That tuple is far too
# broad to use as a binary "this was a timeout" signal — *every* malformed
# predicted Cypher (unknown label, syntax error, missing parameter) also
# raises ``ClientError`` and was previously being mis-classified as
# "transaction timeout" in the eval logs.  That's why qids c64fb6db
# (Metro-Goldwyn-Mayer) and 18046b50 (Lord of the Rings) showed PSJS-timeout
# warnings within 7–15 s of starting, instead of the 120 s server cap.
#
# The Neo4j Python driver attaches a ``.code`` attribute of the form
# ``Neo.<Category>.<Sub>.<Specific>`` to every error.  Real transaction
# timeouts use codes that contain ``Timeout`` / ``TimedOut`` / ``Terminated``;
# we match on that substring rather than on exception class.
# ──────────────────────────────────────────────────────────────────────────────
_TIMEOUT_CODE_RE = re.compile(r"(Timeout|TimedOut|Terminated)", re.IGNORECASE)


def _safe_exc_text(exc: BaseException) -> str:
    """Render an exception as ``ClassName: message`` while tolerating
    ``__str__`` implementations that themselves raise (some neo4j driver
    error subclasses crash in ``__str__`` when they're only partially
    hydrated — e.g. in test harnesses)."""
    name = type(exc).__name__
    try:
        body = str(exc)
    except Exception:  # noqa: BLE001 — defensive only
        # Fall back to fields most likely to be populated.
        body = getattr(exc, "message", None) or getattr(exc, "code", None) or "<unrenderable>"
    return f"{name}: {body}"


def _is_real_timeout(exc: BaseException) -> bool:
    """Return True iff *exc* is a Neo4j transaction-timeout (not a generic
    client/transient error)."""
    code = getattr(exc, "code", None) or ""
    if isinstance(code, str) and _TIMEOUT_CODE_RE.search(code):
        return True
    # Some driver versions stash the status code in ``.gql_status`` or only
    # in the message body — fall back to a substring match on the rendered
    # text.  Wrap ``str(exc)`` in a try/except: partially-constructed
    # exception objects (synthetic test doubles, half-hydrated driver
    # errors) can raise inside ``__str__``.
    try:
        msg = str(exc)
    except Exception:  # noqa: BLE001 — defensive only
        msg = ""
    return bool(_TIMEOUT_CODE_RE.search(msg))


# Default per-query, server-side transaction-timeout cap (seconds).  Overridable
# via ``EVAL_PSJS_TIMEOUT_SEC`` so operators can bump or lower it without a
# code edit.  60 s aligns with the per-example wall-clock watchdog in
# ``metrics_CypherBench.evaluate_dataset`` — no point keeping PSJS alive past
# the point its parent example has already been killed.
try:
    _DEFAULT_PSJS_TIMEOUT_SEC = int(os.environ.get("EVAL_PSJS_TIMEOUT_SEC", "60"))
except ValueError:
    _DEFAULT_PSJS_TIMEOUT_SEC = 60


# ──────────────────────────────────────────────────────────────────────────────
# 1. Query-rewriting primitives — direct port of cypherbench reference
# ──────────────────────────────────────────────────────────────────────────────

# Cypher clause-header regex used to split a query into top-level clauses.
# Whitespace-insensitive, case-sensitive (matches reference behaviour;
# CypherBench gold queries are written with upper-case keywords).
_CLAUSE_PATTERN = re.compile(
    r'\b(MATCH|OPTIONAL MATCH|WHERE|RETURN|UNION|WITH|CREATE|SET|DELETE|MERGE|'
    r'UNWIND|ORDER BY|LIMIT|SKIP|FOREACH|CALL|YIELD)\b'
)

# UNION at top level of a query (whole-word, case-sensitive).
_UNION_PATTERN = re.compile(r'\bUNION\b')

# Anonymous node ``(:Label {props})`` capture.
_ANON_NODE_RE = re.compile(r'(\(:)([A-Za-z]+)(\s*\{.*?\})?\)')

# Anonymous relationship ``[:REL ...]`` capture.
_ANON_REL_RE = re.compile(r'(\[)(:.*?)(\])')

# Variable extractors.
_NODE_VAR_RE = re.compile(r'\((\w+)(?::[^\)]*|\))')
_REL_VAR_RE  = re.compile(r'-\[(\w+)(?::|\])')

# Replace property-blocks ``{ ... }`` with a placeholder so node-var
# extraction does not confuse property keys for variable names.
_PROP_BLOCK_RE = re.compile(r'\{[^}]*\}')


def _split_by_union(cypher: str) -> List[str]:
    """
    Split *cypher* on top-level ``UNION``, with the special case for queries
    that begin with ``CALL { ... }`` containing inner UNIONs.

    Faithful port of ``cypherbench.metrics.provenance_subgraph_jaccard_similarity.split_by_union``.
    """
    if cypher.strip().startswith("CALL"):
        inner_match = re.search(
            r'CALL\s*\{(.*?)\}\s*(WITH|RETURN|WHERE|UNWIND)',
            cypher,
            re.DOTALL,
        )
        if inner_match:
            inner = inner_match.group(1)
            return [q.strip() for q in _UNION_PATTERN.split(inner)]
        return [cypher.strip()]
    return [q.strip() for q in _UNION_PATTERN.split(cypher)]


def _split_cypher_into_clauses(cypher_query: str) -> List[str]:
    """Split a Cypher query string into a list of top-level clauses."""
    matches = list(_CLAUSE_PATTERN.finditer(cypher_query))
    clauses: List[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cypher_query)
        clauses.append(cypher_query[start:end].strip())
    return clauses


def _extract_match_cypher(cypher: str) -> Optional[str]:
    """
    Keep only the ``MATCH`` / ``OPTIONAL MATCH`` / ``WHERE`` / non-aliasing
    ``WITH *`` clauses that lead the query.  Returns ``None`` if the query
    does not start with ``MATCH``.
    """
    if not cypher.startswith('MATCH'):
        return None

    clauses = _split_cypher_into_clauses(cypher)
    match_clauses: List[str] = []
    for clause in clauses:
        if not any(
            clause.startswith(kw)
            for kw in ('MATCH', 'OPTIONAL MATCH', 'WITH', 'WHERE')
        ):
            break
        if clause.startswith('WITH'):
            if ' as ' in clause.lower():
                # Aliased WITH renames variables — abort, downstream
                # MATCH/WHERE references would no longer resolve to the
                # original node vars.
                break
            match_clauses.append('WITH *')
        else:
            match_clauses.append(clause)

    while match_clauses and match_clauses[-1].startswith('WITH'):
        match_clauses.pop()

    return ' '.join(match_clauses) if match_clauses else None


def _add_variables(match_cypher: str) -> str:
    """
    Inject synthetic ``ntmp{i}`` and ``rtmp{i}`` variables into anonymous
    nodes and relationships so they can be referenced in ``elementId()``.
    """
    node_counter = 0
    rel_counter = 0

    def _replace_node(match: re.Match) -> str:
        nonlocal node_counter
        replacement = f"(ntmp{node_counter}:{match.group(2)}{match.group(3) or ''})"
        node_counter += 1
        return replacement

    def _replace_rel(match: re.Match) -> str:
        nonlocal rel_counter
        replacement = f"[rtmp{rel_counter}{match.group(2)}]"
        rel_counter += 1
        return replacement

    clauses = _split_cypher_into_clauses(match_cypher)
    for i, clause in enumerate(clauses):
        if clause.startswith('MATCH') or clause.startswith('OPTIONAL MATCH'):
            clause = _ANON_REL_RE.sub(_replace_rel, clause)
            clauses[i] = _ANON_NODE_RE.sub(_replace_node, clause)
    return ' '.join(clauses)


def _extract_node_variables(match_cypher: str) -> List[str]:
    """Distinct, sorted list of node variable names appearing in MATCH clauses."""
    cleaned = _PROP_BLOCK_RE.sub('{dummy}', match_cypher)
    vars_: List[str] = []
    for clause in _split_cypher_into_clauses(cleaned):
        if clause.startswith('MATCH') or clause.startswith('OPTIONAL MATCH'):
            vars_ += _NODE_VAR_RE.findall(clause)
    return sorted(set(vars_))


def _extract_relationship_variables(match_cypher: str) -> List[str]:
    """Distinct, sorted list of relationship variable names appearing in MATCH clauses."""
    vars_: List[str] = []
    for clause in _split_cypher_into_clauses(match_cypher):
        if clause.startswith('MATCH') or clause.startswith('OPTIONAL MATCH'):
            vars_ += _REL_VAR_RE.findall(clause)
    return sorted(set(vars_))


# ──────────────────────────────────────────────────────────────────────────────
# 2. Public rewriter — emits a Cypher query whose RETURN is the provenance set
# ──────────────────────────────────────────────────────────────────────────────

def _build_ps_cypher(
    cypher: str,
    *,
    return_var: str,
    use_element_id: bool,
) -> Optional[str]:
    """
    Build the rewritten provenance-fetch Cypher.

    Parameters
    ----------
    cypher
        Original gold or predicted query.
    return_var
        Column name to use in the final ``RETURN``.
    use_element_id
        When True, emit ``elementId(var)``; when False, emit ``id(var)``
        (Neo4j 4.x compatibility fallback).

    Returns
    -------
    str | None
        Rewritten Cypher string, or ``None`` if every UNION-branch failed
        to rewrite (no MATCH clause anywhere).
    """
    id_fn = "elementId" if use_element_id else "id"
    sub_cyphers = _split_by_union(cypher)
    ps_cyphers: List[str] = []

    for sub in sub_cyphers:
        match_part = _extract_match_cypher(sub)
        if not match_part:
            continue
        match_part = _add_variables(match_part)
        node_vars = _extract_node_variables(match_part)
        rel_vars  = _extract_relationship_variables(match_part)

        node_expr = (
            ' + '.join(f'collect(distinct {id_fn}({v}))' for v in node_vars)
            if node_vars else "[]"
        )
        rel_expr = (
            ' + '.join(f'collect(distinct {id_fn}({v}))' for v in rel_vars)
            if rel_vars else "[]"
        )

        # Combined node + relationship IDs in a single elemIds list.
        if node_vars and rel_vars:
            combined = f'{node_expr} + {rel_expr}'
        elif node_vars:
            combined = node_expr
        elif rel_vars:
            combined = rel_expr
        else:
            combined = "[]"

        ps_cyphers.append(
            f'{match_part} '
            f'WITH {combined} AS elemIds '
            f'UNWIND elemIds AS elemId '
            f'RETURN elemId AS {return_var}'
        )

    if not ps_cyphers:
        return None
    return ' UNION '.join(ps_cyphers)


def rewrite_for_provenance(cypher: str) -> Optional[str]:
    """
    Public entry-point: rewrite *cypher* for provenance extraction using
    ``elementId(...)``.  Returns ``None`` if the query has no rewritable
    MATCH clause (e.g. pure ``RETURN`` aggregations, ``CALL``-only
    procedures with no MATCH, etc.).

    Callers that need an ``id()`` fallback should call
    :func:`_build_ps_cypher` directly with ``use_element_id=False``;
    :func:`compute_psjs` does this transparently.
    """
    if not cypher or not cypher.strip():
        return None
    return _build_ps_cypher(cypher, return_var="elemId", use_element_id=True)


# ──────────────────────────────────────────────────────────────────────────────
# 3. PSJS metric — execute both rewrites and Jaccard their result sets
# ──────────────────────────────────────────────────────────────────────────────

def _run_provenance_query(
    neo4j_graph: Any,
    cypher: str,
    return_col: str,
    *,
    use_element_id: bool,
    timeout: Optional[float] = None,
) -> Tuple[Optional[Set[Any]], Optional[str]]:
    """
    Rewrite *cypher* for provenance and execute it.

    Parameters
    ----------
    timeout
        Per-transaction server-side timeout, in seconds.  When supplied,
        the query is executed via :func:`neo4j_lib.safe_query.safe_cypher_run`
        using the driver embedded in *neo4j_graph* (LangChain
        ``Neo4jGraph`` exposes its driver as ``_driver``).  When ``None``,
        falls back to the historic ``neo4j_graph.query(...)`` path which
        has no client-side timeout enforcement.

    Returns
    -------
    (id_set, error)
        On success, ``id_set`` is the set of element-IDs touched by the
        query and ``error`` is None.  On rewrite-failure ``id_set`` is
        ``None`` and ``error`` is a human-readable reason.  On execution
        failure both are None / error string respectively.  Transaction
        timeouts surface as ``error="transaction timeout: …"``.
    """
    rewritten = _build_ps_cypher(
        cypher, return_var=return_col, use_element_id=use_element_id
    )
    if rewritten is None:
        return None, "no MATCH clause to rewrite"

    # Prefer the timeout-enforcing helper when we can reach the underlying
    # driver.  LangChain's ``Neo4jGraph`` stores it as ``_driver`` and the
    # active database name as ``_database``.  If those attributes are
    # missing (custom wrapper), fall through to the legacy path.
    driver = getattr(neo4j_graph, "_driver", None) if timeout is not None else None
    database = getattr(neo4j_graph, "_database", None) if driver is not None else None

    try:
        if driver is not None:
            rows = safe_cypher_run(
                driver,
                rewritten,
                params=None,
                timeout=float(timeout),
                database=database,
            )
        else:
            rows = neo4j_graph.query(rewritten)
    except TransactionTimedOutError as exc:  # type: ignore[misc]
        # ``TransactionTimedOutError`` is the tuple ``(TransientError,
        # ClientError)`` — both classes also cover ordinary client-side
        # errors (unknown labels, syntax errors, missing params).  We must
        # interrogate ``.code`` to tell a *real* timeout apart from a
        # garden-variety bad-Cypher error; otherwise both end up logged as
        # "transaction timeout" and PSJS silently returns 0.0 for what is
        # actually a malformed predicted query.
        text = _safe_exc_text(exc)
        if _is_real_timeout(exc):
            return None, f"transaction timeout: {text}"
        return None, text
    except Exception as exc:  # noqa: BLE001 — surface every failure
        return None, _safe_exc_text(exc)

    ids = {r[return_col] for r in (rows or []) if r.get(return_col) is not None}
    return ids, None


def compute_psjs(
    pred_cypher: Optional[str],
    gold_cypher: Optional[str],
    *,
    neo4j_graph: Any,
    ea_value: Optional[bool] = None,
    timeout: Optional[int] = None,
) -> Optional[float]:
    """
    Compute Provenance Subgraph Jaccard Similarity between *pred_cypher* and
    *gold_cypher*.

    Parameters
    ----------
    pred_cypher
        Agent-predicted Cypher.  ``None`` / empty ⇒ PSJS = 0.0 if a gold
        was supplied, else ``None``.
    gold_cypher
        Reference Cypher.  ``None`` ⇒ PSJS is N/A — returns ``None``.
    neo4j_graph
        Object with a ``.query(cypher)`` method (e.g.
        ``langchain_neo4j.Neo4jGraph``).  When the object also exposes a
        ``_driver`` attribute (LangChain's ``Neo4jGraph`` does), each
        provenance query is run via
        :func:`neo4j_lib.safe_query.safe_cypher_run` so the *timeout*
        below is enforced as a **server-side per-transaction cap**.  When
        ``_driver`` is missing, the query falls back to
        ``neo4j_graph.query(...)`` and the timeout is **not** enforced
        (the caller should treat that as best-effort).
    ea_value
        Execution-Accuracy verdict (``True`` / ``False``).  Used **only**
        when one or both queries cannot be rewritten for provenance —
        per the harness spec the fallback is PSJS = 1.0 if EA else 0.0.
        If *ea_value* is ``None`` and a fallback is needed, this function
        returns ``None``.
    timeout
        Per-query, server-side transaction-timeout cap in **seconds**,
        applied independently to the gold and the predicted provenance
        rewrites.  When either query exceeds it, Neo4j aborts the
        transaction (raising :class:`TransientError` /
        :class:`ClientError`) and this function returns ``0.0``,
        matching the existing "execution failure" convention.  The
        caller's example is **not** aborted.

    Returns
    -------
    float | None
        Jaccard similarity in [0, 1], or ``None`` when PSJS is not
        applicable (no gold) or no fallback is available.  Returns
        ``0.0`` if either provenance query failed (including on
        transaction timeout).
    """
    if gold_cypher is None:
        return None
    if pred_cypher is None or not pred_cypher.strip():
        # No prediction at all — symmetric with reference impl, which would
        # yield empty pred_ps and (assuming non-empty gold_ps) PSJS = 0.
        return 0.0

    # Identical-strings short-circuit (matches reference impl).
    if pred_cypher == gold_cypher:
        return 1.0

    if timeout is None:
        timeout = _DEFAULT_PSJS_TIMEOUT_SEC

    # ── Try elementId() first; fall back to id() on syntax failure ──────────
    use_eid = True
    gold_ids, gold_err = _run_provenance_query(
        neo4j_graph, gold_cypher, "elemId1",
        use_element_id=use_eid, timeout=timeout,
    )
    if gold_err and "elementId" in (gold_err or ""):
        # Likely Neo4j < 5 — retry whole pipeline with id().
        use_eid = False
        gold_ids, gold_err = _run_provenance_query(
            neo4j_graph, gold_cypher, "elemId1",
            use_element_id=use_eid, timeout=timeout,
        )
    pred_ids, pred_err = _run_provenance_query(
        neo4j_graph, pred_cypher, "elemId2",
        use_element_id=use_eid, timeout=timeout,
    )

    # ── Fallback path: at least one query is not rewritable ─────────────────
    rewrite_failed = (
        gold_err == "no MATCH clause to rewrite"
        or pred_err == "no MATCH clause to rewrite"
    )
    if rewrite_failed:
        if ea_value is None:
            logger.info(
                "PSJS fallback triggered (query not rewritable) but no EA "
                "value supplied — returning None.  gold_err={!r} pred_err={!r}",
                gold_err, pred_err,
            )
            return None
        psjs_fb = 1.0 if ea_value else 0.0
        logger.info(
            "PSJS fallback: query not rewritable for provenance — using EA={} "
            "→ PSJS={}.  gold_err={!r} pred_err={!r}",
            ea_value, psjs_fb, gold_err, pred_err,
        )
        return psjs_fb

    # ── Other execution errors — match reference: return 0.0 ────────────────
    if gold_err is not None or pred_err is not None:
        # Distinguish timeout in the log message so operators can grep
        # for it; the return value (0.0) follows the existing convention.
        # Note: ``_run_provenance_query`` now only emits the
        # "transaction timeout" prefix for *real* server-side timeouts (per
        # ``_is_real_timeout``), so other ClientError / TransientError
        # cases — invalid label, syntax error, etc. — land in the generic
        # branch below with the original exception text intact.
        timed_out = (
            (gold_err or "").startswith("transaction timeout")
            or (pred_err or "").startswith("transaction timeout")
        )
        if timed_out:
            logger.warning(
                "PSJS provenance query timed out after {}s — returning 0.0.  "
                "gold_err={!r} pred_err={!r}",
                timeout, gold_err, pred_err,
            )
        else:
            logger.warning(
                "PSJS execution failed — returning 0.0.  "
                "gold_err={!r} pred_err={!r}",
                gold_err, pred_err,
            )
        return 0.0

    # gold_ids / pred_ids are guaranteed to be sets at this point.
    inter = len(gold_ids & pred_ids)
    union = len(gold_ids | pred_ids)
    if union == 0:
        # Both rewrites executed cleanly but neither touched any nodes /
        # rels (very rare — e.g. a MATCH whose pattern doesn't bind any
        # named vars).  Apply EA-based fallback for parity with the
        # "non-rewritable" branch above.
        if ea_value is None:
            return None
        return 1.0 if ea_value else 0.0
    return inter / union
