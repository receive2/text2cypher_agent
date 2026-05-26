# -*- coding: utf-8 -*-
"""
neo4j_lib.safe_query
====================
Driver-level helper for running Cypher with a **server-side transaction
timeout**.

Why this exists
---------------
The repo's deployed Neo4j is **Aura** (managed cloud, URI ``neo4j+s://…``),
which means we cannot edit ``neo4j.conf`` ourselves to set
``dbms.transaction.timeout``.  All transaction-timeout enforcement therefore
has to happen **client-side**, via the driver's per-transaction ``timeout``
kwarg.  When set, the driver tells the server "abort this transaction after
N seconds"; the server raises ``TransactionTimedOut`` and the client raises
:class:`neo4j.exceptions.TransientError` / :class:`ClientError` accordingly.

Important: the neo4j 5.x Python driver does **not** accept ``timeout=`` on
:meth:`neo4j.Session.run`.  The server-side cap must be set when the
transaction is opened — either via :meth:`Session.begin_transaction` or
via :func:`@neo4j.unit_of_work(timeout=…)` decorating the function passed
to :meth:`Session.execute_read` / ``execute_write``.  This helper uses
:meth:`begin_transaction` because it preserves the simple
"run a single statement, get rows back" call shape that the existing call
sites in this repo use.

When to use this helper
-----------------------
Use ``safe_cypher_run`` instead of the bare
``with driver.session(...) as s: s.run(cypher).data()`` pattern whenever
the Cypher being executed:

  * comes from an LLM (``GraphCypherQAChain.invoke`` predicted Cypher),
  * is the "gold" Cypher loaded from a benchmark (``execute_cypher``),
  * is a provenance / path-walking query that touches large neighborhoods
    (the rewritten queries inside ``eval/psjs.py``),

i.e. anywhere a pathological query could plausibly hang the worker.

Do **not** use it for trivial introspection queries that are known to be
O(1) on the server (``CALL db.labels()``, ``RETURN 1 AS ok``, etc.) — the
extra transaction overhead is unnecessary there.

Existing call sites are intentionally *not* migrated by this change; this
module only introduces the helper.  Migrate call sites in follow-up edits.

Example
-------
::

    from neo4j import GraphDatabase
    from neo4j_lib.safe_query import safe_cypher_run

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        rows = safe_cypher_run(
            driver,
            "MATCH (m:Movie {title: $t}) RETURN m.released AS year",
            params={"t": "Inception"},
            timeout=30,
            database="neo4j",
        )
    except TransactionTimedOutError:
        rows = None   # caller decides how to mark the failure
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neo4j import Driver
from neo4j.exceptions import ClientError, TransientError

# Re-exported alias so callers don't all have to import the underlying
# driver exception classes.  ``TransactionTimedOut`` is raised by Neo4j
# as a TransientError (code: Neo.ClientError.Transaction.TransactionTimedOut
# on some versions, Neo.TransientError.Transaction.* on others).  Callers
# should ``except TransactionTimedOutError`` and treat it as "this query
# took too long; mark the run as a timeout and move on".
TransactionTimedOutError = (TransientError, ClientError)


def safe_cypher_run(
    driver: Driver,
    cypher: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
    database: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Run a single Cypher statement with a server-side transaction timeout.

    Parameters
    ----------
    driver : neo4j.Driver
        An already-constructed Neo4j driver.  The caller owns its
        lifecycle — this helper does **not** close it.
    cypher : str
        The Cypher statement to execute.  A single statement; do not
        concatenate multiple semicolon-separated queries.
    params : dict, optional
        Cypher parameters.  Prefer parameters over string interpolation —
        the server caches plans by parameterized statement.
    timeout : float, default 60
        Per-transaction server-side timeout, in **seconds**.  Passed to
        :meth:`neo4j.Session.begin_transaction` as ``timeout=…``; the
        server enforces this and aborts the transaction if it overruns.
        On overrun a :class:`neo4j.exceptions.TransientError` (or, on
        some server versions, a :class:`ClientError`) is raised — both
        are captured in :data:`TransactionTimedOutError`.
    database : str, optional
        Database name (Aura multi-db / Neo4j 4+ tenancy).  ``None`` uses
        the driver's default database.

    Returns
    -------
    list[dict]
        Result records as plain ``dict``s (one per row).  Materialized
        before the transaction commits, so the caller does not need to
        hold the session open.

    Raises
    ------
    neo4j.exceptions.TransientError
    neo4j.exceptions.ClientError
        On transaction timeout (caller should catch
        :data:`TransactionTimedOutError`).
    Any other :class:`neo4j.exceptions.Neo4jError`
        Propagates as usual (syntax errors, constraint violations, etc.).
    """
    sess_kwargs: Dict[str, Any] = {}
    if database is not None:
        sess_kwargs["database"] = database

    with driver.session(**sess_kwargs) as session:
        # ``begin_transaction(timeout=…)`` is the correct API in neo4j
        # 5.x for setting a server-side per-tx timeout.  ``Session.run``
        # itself does not accept a ``timeout`` kwarg.
        with session.begin_transaction(timeout=timeout) as tx:
            result = tx.run(cypher, params or {})
            rows = [record.data() for record in result]
            # Explicit commit so the timeout window covers the full
            # read+materialize cycle; the context manager would commit
            # on exit anyway but being explicit is clearer.
            tx.commit()
    return rows
