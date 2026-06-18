#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval/graph_guard.py
===================
Cross-check that the per-graph **artifacts** (the generated node tools)
actually correspond to the **connected Neo4j graph**.

Why this exists
---------------
The harness keeps ONE live copy of the per-graph artifacts
(``generated/generated_node_tools.py``, ``schema_data/``, ``prompts.py``,
the FAISS dirs, the FCAV index) and swaps archives in/out of those same
paths for each ``(dataset, graph)`` pair.  Nothing in the system binds
those artifacts to the graph's *content*:

* the ``.current_setup`` sentinel only records a **name**, and ``swap_in``
  trusts it blindly (no-ops when the name matches);
* the FAISS fingerprint's identity fields are ``database`` and
  ``neo4j_uri_host`` — but every graph on the shared VM has
  ``database="neo4j"`` and host ``34.9.85.21``, distinguished only by a
  **port the fingerprint drops**.  So the fingerprint only proves the
  tools and the index are consistent with *each other*, not with the
  graph.

The result: a botched swap, a failed ``gen_tools`` step, or a hand
recovery can leave the live tools searching one graph's labels while the
eval runs against another graph's database.  Grounding then silently
finds nothing and the run scores at the *no-val-link* floor — with no
error, just a low number a collaborator can't explain.

This module asks the only source of truth — the database itself —
whether the labels the node tools search actually exist there.  One
cheap ``CALL db.labels()`` turns the silent failure into a loud one.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

# Node tools are generated with a literal ``node_label="<Label>"`` kwarg
# (see tools/gen_tools.py). Extracting them is a cheap regex — no import of
# the tool registry (which would require a live Neo4j connection of its own).
_NODE_LABEL_RE = re.compile(r'node_label\s*=\s*"([^"]+)"')


def node_tool_labels(tools_file) -> set[str]:
    """Distinct node labels the generated node tools search."""
    text = Path(tools_file).read_text(encoding="utf-8")
    return set(_NODE_LABEL_RE.findall(text))


def label_node_counts(
    labels, uri: str, user: str, password: str, database: str
) -> dict[str, int]:
    """
    Node count for each label in *labels* on the connected graph.

    We count rather than rely on ``CALL db.labels()`` because Neo4j keeps
    a label in the registry even after every node bearing it is deleted —
    so a container that once held a different graph reports *ghost* labels
    with zero nodes.  (Empirically, the movie container reports flight's
    ``FlightAccident``/``Airport`` labels with 0 nodes.)  A single-label
    ``count`` hits Neo4j's count store and is O(1), so this stays cheap
    even on multi-hundred-thousand-node graphs.
    """
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password))
    counts: dict[str, int] = {}
    try:
        with driver.session(database=database) as session:
            for label in labels:
                # Label comes from our own generated tools (a Python
                # identifier), but backtick-quote defensively anyway.
                safe = "`" + label.replace("`", "``") + "`"
                rec = session.run(
                    f"MATCH (n:{safe}) RETURN count(n) AS c"
                ).single()
                counts[label] = int(rec["c"]) if rec else 0
    finally:
        driver.close()
    return counts


def check_tools_match_graph(
    tools_file,
    uri: str,
    user: str,
    password: str,
    database: str,
) -> Tuple[bool, str]:
    """
    Verify the node tools in *tools_file* match the connected graph.

    Returns ``(ok, detail)``.  ``ok`` is ``False`` when the tools search
    one or more labels that have **zero nodes** in the connected graph —
    the contamination signature (e.g. flight's ``FlightAccident`` tools
    pointed at the movie database, where that label is an empty ghost in
    the registry).  Counting nodes — not just checking ``db.labels()`` —
    is what makes the check decisive: a ghost label passes a presence
    check but fails a count check.

    The detail string is written to be readable by a collaborator who has
    never seen the harness internals.
    """
    live = node_tool_labels(tools_file)
    if not live:
        return False, (
            f"no node_label found in {tools_file} — the node tools are "
            "empty or unparsable. Re-run scripts/setup_and_archive.py for "
            "this pair."
        )
    counts = label_node_counts(live, uri, user, password, database)
    empty = sorted(lbl for lbl, c in counts.items() if c == 0)
    if empty:
        return False, (
            f"ARTIFACT/GRAPH MISMATCH: the node tools search labels {empty} "
            f"that have ZERO nodes in this graph — they belong to a "
            f"different graph (counts={counts}). The archive for this pair "
            "is contaminated. Re-run `python scripts/setup_and_archive.py "
            "<dataset> <graph> --force` before evaluating."
        )
    return True, (
        f"ok ({len(live)} tool labels, all non-empty; "
        f"min count={min(counts.values())})"
    )
