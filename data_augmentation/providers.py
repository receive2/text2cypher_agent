"""
data_augmentation.providers
============================
Factory that builds the live validity + alias providers for a
``(dataset, graph)`` pair, wiring the augmentation pipeline to the real graph
DB (``eval_config.GRAPH_CONNS``) and the attested-alias sources.

Used by the staging runner and (later) ``run_data_augmentation.py``.  Reaching
the VM requires the corporate VPN disconnected (see env-vpn-proxy memory).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from loguru import logger

from data_augmentation.kb_aliases import AliasProvider
from data_augmentation.validity import Neo4jValueProvider, ValueProvider


# Cache one driver per (uri, database) so repeated graphs reuse the connection.
_DRIVERS: Dict[Tuple[str, str], object] = {}


def _driver_for(uri: str, user: str, password: str, database: str):
    key = (uri, database)
    if key not in _DRIVERS:
        from neo4j import GraphDatabase
        _DRIVERS[key] = GraphDatabase.driver(uri, auth=(user, password),
                                             connection_timeout=15)
    return _DRIVERS[key]


def build_providers(
    dataset: str,
    graph: str,
    *,
    conn_graph: Optional[str] = None,
    rxnorm_path: Optional[str] = None,
) -> Tuple[ValueProvider, AliasProvider]:
    """Return ``(value_provider, alias_provider)`` for a (dataset, graph).

    The value provider queries the live graph for distinct (label, prop) value
    sets (cached per (label, prop)); the alias provider reads the graph's
    shipped Wikidata aliases + curated tables (+ optional RxNorm).

    ``conn_graph`` overrides the key used to look up the connection in
    ``eval_config.GRAPH_CONNS`` when the dataset's graph name differs from the
    registered key (e.g. Mind-the-Query dir ``bloom`` ↔ conn key ``bloom50``).
    ``graph`` itself still drives alias lookup + synthetic-domain detection.
    """
    import eval_config as cfg

    conn = cfg.conn_for(dataset, conn_graph or graph)
    database = getattr(conn, "database", None) or "neo4j"
    driver = _driver_for(conn.uri, conn.user, conn.password, database)
    values = Neo4jValueProvider(driver, database)
    aliases = AliasProvider(graph=graph, rxnorm_path=rxnorm_path)
    logger.debug(f"providers: built for ({dataset}, {graph}) → {conn.uri} db={database}")
    return values, aliases


def close_all() -> None:
    """Close every cached driver (call once at end of a run)."""
    for d in _DRIVERS.values():
        try:
            d.close()
        except Exception:  # noqa: BLE001
            pass
    _DRIVERS.clear()
