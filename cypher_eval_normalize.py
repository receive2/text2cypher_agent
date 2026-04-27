#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cypher_eval_normalize.py
========================
Result-set normalisation for Text2Cypher Execution-Accuracy evaluation.

This module is intentionally **pure / stateless** so it is safe to call from
multiple threads (CypherBench's reference impl does, and we may parallelise
``metrics_CypherBench.evaluate_dataset`` in the future).

Why this exists
---------------
The original CypherBench EX implementation (see
``cypherbench/metrics/execution_accuracy.py`` upstream) was written under
the assumption that *all* gold queries ``RETURN`` literal scalars only — never
``Node`` / ``Relationship`` / ``Path`` objects.  When we score a Text2Cypher
agent that may emit ``RETURN p`` / ``RETURN p, m, r``, or when we evaluate
against datasets like *Mind the Query* whose gold queries return nodes
directly, the upstream comparator silently produces wrong numbers because:

* ``Node.__eq__`` uses ``element_id``, which is **not stable** across two
  separate query executions.
* Stringifying a ``Node`` via ``repr()`` embeds that same transient id.
* ``Path`` objects raise ``TypeError`` in upstream's ``to_hashable``.

This module provides :func:`normalize_result_set` which turns a Neo4j
result list into a list of hashable, comparison-safe row signatures with
explicit, structural handling of Node / Relationship / Path.

Scoping note (do not "fix" this without reading the docstring of
``metrics_CypherBench.execution_accuracy`` first):

    * EA stays multiset, EM stays ordered.
    * The ``has_order_by`` heuristic only governs ``sort_collections``
      *inside* ``collect()``-style cells — it does **not** auto-promote
      EA from multiset to ordered.  The EA−EM gap is the consumer's
      "fraction of items where ordering matters" signal; auto-promoting
      EA on ORDER BY would destroy that signal.

Strict-CypherBench mode
-----------------------
Passing ``strict_cypherbench=True`` (or equivalently the four knobs set as
``STRICT_CYPHERBENCH_KW``) reproduces upstream CypherBench's actual
``to_hashable`` behaviour, verified against
``megagonlabs/cypherbench@main``:cypherbench/metrics/execution_accuracy.py:

    * lines 30-32 — int/float/str/bool/None pass through unchanged
      (→ ``float_eps=0.0``, ``case_insensitive_strings=False``).
    * lines 35-39 — list/tuple branch sorts with ``unorder_list=True`` by
      default (→ ``sort_collections=True``).
    * line 51 — Node / Relationship raise ``TypeError`` (→ we mirror this
      by leaving ``expand_nodes`` / ``expand_relationships`` *off* so the
      legacy ``repr()`` fallback in ``metrics_CypherBench`` is preserved).

Note: today's *local* ``metrics_CypherBench._normalise_scalar`` already
drifts from upstream — it does ``str.strip().lower()`` and never sorts
lists.  Strict mode here matches **upstream**, not today's local code.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# Sentinels — used to keep normalised values from the structural branches
# from accidentally colliding with literal tuples that share the same shape.
# ──────────────────────────────────────────────────────────────────────────────

_NODE_TAG = "__node__"
_REL_TAG  = "__rel__"
_PATH_TAG = "__path__"
_BOOL_TAG = "__bool__"
_DT_TAG   = "__datetime__"


# ──────────────────────────────────────────────────────────────────────────────
# Driver-type detection — done by attribute / module name rather than a hard
# import, so this module does not require a specific neo4j driver version.
# ──────────────────────────────────────────────────────────────────────────────

def _is_neo4j_node(v: Any) -> bool:
    cls = type(v)
    mod = getattr(cls, "__module__", "")
    if mod.startswith("neo4j.graph") and cls.__name__ == "Node":
        return True
    # Duck-typing fallback for tests / mocks: has labels + items()
    return (
        hasattr(v, "labels")
        and hasattr(v, "items")
        and not hasattr(v, "type")          # disambiguate from Relationship
        and not hasattr(v, "nodes")         # disambiguate from Path
    )


def _is_neo4j_relationship(v: Any) -> bool:
    cls = type(v)
    mod = getattr(cls, "__module__", "")
    if mod.startswith("neo4j.graph") and cls.__name__ == "Relationship":
        return True
    return (
        hasattr(v, "type")
        and hasattr(v, "items")
        and not hasattr(v, "labels")
    )


def _is_neo4j_path(v: Any) -> bool:
    cls = type(v)
    mod = getattr(cls, "__module__", "")
    if mod.startswith("neo4j.graph") and cls.__name__ == "Path":
        return True
    return hasattr(v, "nodes") and hasattr(v, "relationships")


def _is_datetime_like(v: Any) -> bool:
    # Covers stdlib datetime/date and neo4j.time.{Date,DateTime,Time,Duration}.
    return hasattr(v, "isoformat") or hasattr(v, "iso_format")


# ──────────────────────────────────────────────────────────────────────────────
# ORDER BY heuristic
# ──────────────────────────────────────────────────────────────────────────────

# Best-effort: strip subquery blocks ``CALL { ... }`` (one level of nesting)
# and look for a top-level ``ORDER BY``.  Documented as best-effort because
# we deliberately avoid pulling in a Cypher parser — see Constraints in the
# task description.
_CALL_BLOCK_RE = re.compile(r"CALL\s*\{[^{}]*\}", re.IGNORECASE | re.DOTALL)
_ORDER_BY_RE   = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)


def has_order_by(cypher: Optional[str]) -> bool:
    """Return True if *cypher* contains a top-level ``ORDER BY`` clause.

    Heuristic only — strips one level of ``CALL { ... }`` blocks before
    matching.  Nested/correlated subqueries that themselves contain
    ``ORDER BY`` may produce false positives; that is acceptable for
    eval-time use.
    """
    if not cypher:
        return False
    stripped = _CALL_BLOCK_RE.sub(" ", cypher)
    return bool(_ORDER_BY_RE.search(stripped))


# ──────────────────────────────────────────────────────────────────────────────
# Cell normalisation
# ──────────────────────────────────────────────────────────────────────────────

def _round_float(v: float, eps: float) -> float:
    if eps <= 0.0:
        return float(v)
    # Snap to the nearest multiple of eps so 0.3333333 and 0.3333334 collapse.
    return round(float(v) / eps) * eps


def _normalize_cell(
    v: Any,
    *,
    float_eps: float,
    sort_collections: bool,
    expand_nodes: bool,
    expand_relationships: bool,
    case_insensitive_strings: bool,
) -> Any:
    """Normalise a single cell value into a hashable, comparison-safe form."""
    # None
    if v is None:
        return None

    # Booleans must come before int/float because ``bool`` is a subclass of int.
    if isinstance(v, bool):
        return (_BOOL_TAG, v)

    # Numerics
    if isinstance(v, (int, float)):
        return _round_float(v, float_eps)

    # Strings
    if isinstance(v, str):
        if case_insensitive_strings:
            return v.strip().lower()
        return v

    # Datetime-like (stdlib + neo4j.time.*)
    if _is_datetime_like(v):
        try:
            iso = v.iso_format()  # neo4j.time.Date / DateTime
        except AttributeError:
            iso = v.isoformat()
        return (_DT_TAG, iso)

    # Neo4j Path — order-preserving; we do NOT sort path elements.
    if _is_neo4j_path(v):
        if not (expand_nodes or expand_relationships):
            return repr(v)
        nodes = list(v.nodes)
        rels  = list(v.relationships)
        elems: List[Any] = []
        # Interleave nodes and relationships in path order: n0, r0, n1, r1, ...
        for i, node in enumerate(nodes):
            elems.append(_normalize_cell(
                node,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            ))
            if i < len(rels):
                elems.append(_normalize_cell(
                    rels[i],
                    float_eps=float_eps,
                    sort_collections=sort_collections,
                    expand_nodes=expand_nodes,
                    expand_relationships=expand_relationships,
                    case_insensitive_strings=case_insensitive_strings,
                ))
        return (_PATH_TAG, tuple(elems))

    # Neo4j Node
    if _is_neo4j_node(v):
        if not expand_nodes:
            return repr(v)  # legacy fallback (preserves strict-CypherBench)
        labels = tuple(sorted(str(lbl) for lbl in (v.labels or ())))
        props = tuple(sorted(
            (str(k), _normalize_cell(
                val,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            ))
            for k, val in v.items()
        ))
        return (_NODE_TAG, labels, props)

    # Neo4j Relationship
    if _is_neo4j_relationship(v):
        if not expand_relationships:
            return repr(v)
        rtype = str(getattr(v, "type", ""))
        props = tuple(sorted(
            (str(k), _normalize_cell(
                val,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            ))
            for k, val in v.items()
        ))
        return (_REL_TAG, rtype, props)

    # Plain dict (e.g. apoc.map.* output, or LangChain's pre-flattened Node)
    if isinstance(v, dict):
        items = [
            (str(k), _normalize_cell(
                val,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            ))
            for k, val in v.items()
        ]
        items.sort(key=lambda kv: kv[0])
        return tuple(items)

    # List / tuple (e.g. collect())
    if isinstance(v, (list, tuple)):
        elems = [
            _normalize_cell(
                x,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            )
            for x in v
        ]
        if sort_collections:
            # Sort by repr to give a total order even across heterogeneous
            # element types; matches upstream CypherBench's intent.
            elems.sort(key=repr)
        return tuple(elems)

    # Set / frozenset
    if isinstance(v, (set, frozenset)):
        elems = sorted(
            (_normalize_cell(
                x,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            ) for x in v),
            key=repr,
        )
        return tuple(elems)

    # Fallback — repr keeps unknown types comparable; matches today's behaviour.
    return repr(v)


# ──────────────────────────────────────────────────────────────────────────────
# Row + result-set normalisation
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_row(
    row: Any,
    *,
    float_eps: float,
    sort_collections: bool,
    expand_nodes: bool,
    expand_relationships: bool,
    case_insensitive_strings: bool,
    compare_keys: bool,
    compare_column_order: bool,
) -> Any:
    """Convert a single result row into a hashable signature.

    Layout depends on ``compare_keys`` / ``compare_column_order``:

    * ``compare_keys=False, compare_column_order=False`` (default):
      sorted tuple of normalised values; column names and positions both
      ignored.  Single-column dicts are unwrapped so ``[{"x":1}]`` matches
      ``[1]``.
    * ``compare_keys=True``: ``frozenset`` of ``(key, normalised_value)``
      pairs (record fields are named, not positional, so we never enforce
      positional order under ``compare_keys`` alone).
    * ``compare_column_order=True`` (orthogonal): preserve positional
      order; use only when callers explicitly want positional compare.
    """
    if isinstance(row, dict):
        items = [
            (str(k), _normalize_cell(
                v,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            ))
            for k, v in row.items()
        ]
        if compare_keys:
            # Key-set equality + per-key value compare; record fields are
            # named, not positional, so we don't impose positional order here.
            return frozenset(items)
        if compare_column_order:
            # Preserve insertion order for positional compare.
            return tuple(v for _, v in items)
        # Default: drop keys, drop column order.
        sigs = [v for _, v in items]
        if len(sigs) == 1:
            return (sigs[0],)
        return tuple(sorted(sigs, key=repr))

    if isinstance(row, (list, tuple)):
        sigs = [
            _normalize_cell(
                v,
                float_eps=float_eps,
                sort_collections=sort_collections,
                expand_nodes=expand_nodes,
                expand_relationships=expand_relationships,
                case_insensitive_strings=case_insensitive_strings,
            )
            for v in row
        ]
        if compare_column_order:
            return tuple(sigs)
        return tuple(sorted(sigs, key=repr))

    return (_normalize_cell(
        row,
        float_eps=float_eps,
        sort_collections=sort_collections,
        expand_nodes=expand_nodes,
        expand_relationships=expand_relationships,
        case_insensitive_strings=case_insensitive_strings,
    ),)


def _column_count(row: Any) -> Optional[int]:
    if isinstance(row, dict):
        return len(row)
    if isinstance(row, (list, tuple)):
        return len(row)
    return None  # scalar row — count unknown / not enforced


def normalize_result_set(
    rows: Optional[Iterable[Any]],
    *,
    gold_cypher: Optional[str] = None,           # only used by callers that
                                                 # want the ORDER BY heuristic
                                                 # to gate sort_collections
    float_eps: float = 1e-6,
    sort_collections: bool = True,
    expand_nodes: bool = True,
    expand_relationships: bool = True,
    case_insensitive_strings: bool = True,
    compare_keys: bool = False,
    compare_column_order: bool = False,
) -> List[Any]:
    """Normalise a Neo4j result set into a list of hashable row signatures.

    Parameters
    ----------
    rows
        Iterable of result rows (``dict`` / ``list`` / ``tuple`` / scalar).
        ``None`` is treated as the empty result set.
    gold_cypher
        Optional gold Cypher string.  When provided, the function applies
        the ``ORDER BY`` heuristic: if the gold query orders its results,
        ``sort_collections`` is forced to ``False`` so that ordered
        ``collect()`` outputs are not flattened.  If you don't want this
        behaviour, pass ``gold_cypher=None`` (the default).
    float_eps
        Snap floats to the nearest multiple of ``float_eps`` before
        hashing.  ``0.0`` disables rounding (exact equality).
    sort_collections
        Sort list/tuple cells (e.g. from ``collect()``) before hashing.
    expand_nodes, expand_relationships
        When True, normalise driver ``Node`` / ``Relationship`` objects
        structurally (label-set + property-set, **never** ``element_id``).
        When False, fall back to ``repr()`` — preserved for backwards
        compatibility with the original ``metrics_CypherBench``
        comparator.
    case_insensitive_strings
        Apply ``str.strip().lower()`` to string cells.  Off in strict
        mode to match upstream CypherBench, on by default to match this
        repo's existing behaviour.
    compare_keys
        Strict mode: require column **names** to match (frozenset
        equality of (key, value) pairs).  Off by default.
    compare_column_order
        Strict mode: require column **positions** to match.  Off by
        default; orthogonal to ``compare_keys``.

    Returns
    -------
    list
        One hashable signature per input row, in the input row order.
        Multiset / ordered comparison is the caller's responsibility.

    Notes
    -----
    Column count differences are *not* short-circuited here — that is a
    fast-path concern for the comparator; this function is row-local.
    """
    if rows is None:
        return []

    rows = list(rows)

    # ORDER BY heuristic only governs sort_collections inside collect() cells.
    # It does NOT auto-promote EA from multiset to ordered — see module
    # docstring "Scoping note".
    if gold_cypher is not None and has_order_by(gold_cypher):
        sort_collections = False

    return [
        _normalize_row(
            r,
            float_eps=float_eps,
            sort_collections=sort_collections,
            expand_nodes=expand_nodes,
            expand_relationships=expand_relationships,
            case_insensitive_strings=case_insensitive_strings,
            compare_keys=compare_keys,
            compare_column_order=compare_column_order,
        )
        for r in rows
    ]


def column_counts_match(
    pred_rows: Optional[Iterable[Any]],
    gold_rows: Optional[Iterable[Any]],
) -> bool:
    """Fast-path check: do pred and gold rows have the same column count?

    Returns True if either side is empty (no rows to compare on column
    count) or if every comparable row pair has matching column counts.
    Returns False on the first mismatch.
    """
    p = list(pred_rows or [])
    g = list(gold_rows or [])
    if not p or not g:
        return True
    pc = _column_count(p[0])
    gc = _column_count(g[0])
    if pc is None or gc is None:
        return True  # scalar rows — skip the check
    return pc == gc


# ──────────────────────────────────────────────────────────────────────────────
# Strict-CypherBench preset
# ──────────────────────────────────────────────────────────────────────────────
#
# Verified against megagonlabs/cypherbench@main:
#   cypherbench/metrics/execution_accuracy.py
#     lines 30-32  → int/float/str/bool/None passthrough  → float_eps=0.0,
#                                                          case_insensitive_strings=False
#     lines 35-39  → list/tuple sorted (unorder_list=True default)
#                                                          → sort_collections=True
#     line  51     → Node / Relationship raise TypeError  → expand_*=False
#                    (we mirror by leaving the legacy repr() fallback in place)

STRICT_CYPHERBENCH_KW = {
    "float_eps": 0.0,
    "sort_collections": True,
    "expand_nodes": False,
    "expand_relationships": False,
    "case_insensitive_strings": False,
    "compare_keys": False,
    "compare_column_order": False,
}


def strict_cypherbench_kwargs() -> dict:
    """Return a fresh copy of the strict-mode kwargs (safe to mutate)."""
    return dict(STRICT_CYPHERBENCH_KW)


__all__ = [
    "normalize_result_set",
    "has_order_by",
    "column_counts_match",
    "STRICT_CYPHERBENCH_KW",
    "strict_cypherbench_kwargs",
]
