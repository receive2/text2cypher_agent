#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ner_agent_auto.py
=================
Drop-in extension of ``ner_agent.py`` that *automatically* picks only the
most relevant ``@tool`` functions for each user query instead of wiring every
tool into every agent call.

New public API (mirrors ner_agent.py)
--------------------------------------
  get_ner_auto(prompt, top_k=5, verbose=False)  → JSON string
  get_ner_dict_auto(prompt, top_k=5, verbose=False) → dict

Prerequisite
------------
Run ``python gen_tools.py`` once to generate
``generated_node_tools.py`` and ``generated_rel_tools.py``.
The first call to any ``*_auto`` function will also build the
FAISS index in ``faiss_tools_auto/`` (subsequent calls load it from disk).

How tool selection works
------------------------
1. ``build_tool_registry()``
   Imports ``generated_node_tools`` and ``generated_rel_tools``, scans their
   module-level names for ``BaseTool`` instances, and returns a registry dict::

       {"get_movie_title": <BaseTool>, "get_person_name": <BaseTool>, ...}

2. ``get_or_build_tools_faiss(registry)``
   Builds (or loads from disk) a FAISS vector index where each document
   represents one tool. The embedding text is::

       "get_movie_title: get_movie_title: Get the canonical Movie.title …"

3. ``select_tools_for_query(user_query, top_k)``
   Embeds the user query, searches FAISS, and returns the top-k matching
   ``BaseTool`` callables.

4. ``create_agent_auto(user_query, top_k)``
   Builds a LangGraph ReAct agent wired with only the selected tools.

5. ``get_ner_auto(prompt, top_k, verbose)``
   Orchestrates steps 3-4, runs the agent, and parses the output to the
   canonical JSON string ``{"Label.property": [values, ...]}`` — identical
   format to ``ner_agent.get_ner()``.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv
from loguru import logger

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import BaseTool
from langchain_neo4j import GraphCypherQAChain
from langgraph.prebuilt import create_react_agent

from config import NER_SP, DEFAULT_TOP_K
from ner_agent import llm, neo4j_graph, get_entity
from neo4j_search import search_tool
from tool_search import (
    ToolSearchHit,
    build_embeddings,
    build_tool_registry_from_modules,
    get_or_build_tools_faiss,
    hits_to_callables,
    search_tools,
)

load_dotenv(".env", override=True)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

FAISS_AUTO_DIR: str = "faiss_tools_auto"
# DEFAULT_TOP_K is imported from config.py so it can be tuned in one place.

# ──────────────────────────────────────────────────────────────────────────────
# 1. LLM, Neo4j & entity extraction — reused from ner_agent.py
#    Imported at the top of this module:
#      from ner_agent import llm, neo4j_graph, get_entity
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# 3. Tool registry  — scan generated modules for @tool instances
# ──────────────────────────────────────────────────────────────────────────────

def build_tool_registry() -> Dict[str, BaseTool]:
    """
    Import ``generated_node_tools`` and ``generated_rel_tools``, scan their
    module-level attributes for ``BaseTool`` instances, and return a registry::

        {"get_movie_title": <BaseTool>, "get_person_name": <BaseTool>, ...}

    Raises
    ------
    RuntimeError
        If neither generated module can be imported (i.e. ``gen_tools.py``
        has not been run yet).
    """
    modules = []
    for mod_name in ("generated_node_tools", "generated_rel_tools"):
        try:
            mod = importlib.import_module(mod_name)
            importlib.reload(mod)          # pick up fresh re-generations
            modules.append(mod)
            logger.debug(f"Imported {mod_name!r}")
        except ImportError:
            logger.warning(
                f"Could not import {mod_name!r}. "
                "Run `python gen_tools.py` to generate it."
            )

    if not modules:
        raise RuntimeError(
            "No generated tool modules found. "
            "Please run `python gen_tools.py` first to create "
            "`generated_node_tools.py` and `generated_rel_tools.py`."
        )

    registry = build_tool_registry_from_modules(modules)
    logger.info(f"Tool registry built: {len(registry)} tools loaded.")
    return registry


# ──────────────────────────────────────────────────────────────────────────────
# 4. Module-level lazy singletons for registry and FAISS
# ──────────────────────────────────────────────────────────────────────────────

_registry:     Optional[Dict[str, BaseTool]]  = None
_embeddings                                   = None
_vectorstore                                  = None


def _get_registry() -> Dict[str, BaseTool]:
    """Return the tool registry, building it on first call."""
    global _registry
    if _registry is None:
        _registry = build_tool_registry()
    return _registry


def _get_embeddings():
    """Return the shared embeddings client, building it on first call."""
    global _embeddings
    if _embeddings is None:
        _embeddings = build_embeddings()
    return _embeddings


def _get_vectorstore(faiss_dir: str = FAISS_AUTO_DIR, rebuild: bool = False):
    """Return the FAISS vectorstore, building / loading it on first call."""
    global _vectorstore
    if _vectorstore is None or rebuild:
        _vectorstore = get_or_build_tools_faiss(
            registry   = _get_registry(),
            faiss_dir  = faiss_dir,
            rebuild    = rebuild,
            embeddings = _get_embeddings(),
        )
    return _vectorstore


# ──────────────────────────────────────────────────────────────────────────────
# 5. Tool selection
# ──────────────────────────────────────────────────────────────────────────────

def select_tools_for_query(
    user_query:           str,
    top_k:                int  = DEFAULT_TOP_K,
    faiss_dir:            str  = FAISS_AUTO_DIR,
    rebuild:              bool = False,
    filter_connectivity:  bool = True,
    verbose:              bool = False,
) -> List[BaseTool]:
    """
    Use FAISS semantic search to select the *top_k* most relevant tools for
    *user_query* from the full tool registry, then optionally prune relation
    tools that are not connected to any selected node label.

    Parameters
    ----------
    user_query           : Natural-language question or instruction.
    top_k                : Maximum number of tools to return (default 5).
    faiss_dir            : Directory of the FAISS index (built automatically if absent).
    rebuild              : Force-rebuild the FAISS index even if it already exists.
    filter_connectivity  : When *True* (default), call
                           :func:`filter_tools_by_connectivity` after FAISS
                           search to remove relation tools whose node labels
                           don't overlap with the selected node tools.
                           Set to *False* to keep all FAISS hits as-is.
    verbose              : Print ranked hits and filter decisions to stdout.

    Returns
    -------
    List[BaseTool]
        Ordered from most to least relevant.  May be fewer than *top_k* if
        the registry is smaller, duplicates are collapsed, or connectivity
        filtering removes unrelated relation tools.

    Example
    -------
    >>> tools = select_tools_for_query("movies released in 2015", top_k=5)
    >>> [t.name for t in tools]
    ['get_movie_released', 'get_movie_title', 'get_acted_in_roles']
    # get_follows_relation was dropped — FOLLOWS connects Person→Person,
    # not connected to Movie which is the only selected node label.
    """
    vs   = _get_vectorstore(faiss_dir=faiss_dir, rebuild=rebuild)
    hits = search_tools(vs, user_query=user_query, top_l=top_k)

    if verbose:
        print(f"\n── Tool selection for: {user_query!r} (top_k={top_k}) ──")
        for h in hits:
            print(f"  [{h.rank}] score={h.score:.4f}  {h.func_name}  — {h.description[:80]}")

    tools = hits_to_callables(hits, _get_registry())

    if filter_connectivity:
        tools = filter_tools_by_connectivity(tools, verbose=verbose)

    return tools


# ──────────────────────────────────────────────────────────────────────────────
# 5.5  Connectivity filter — drop relation tools that don't connect to any
#      node label covered by the selected node tools
# ──────────────────────────────────────────────────────────────────────────────

# Pre-compiled patterns used by the helpers below.
_RE_NODE_DESC       = re.compile(r"canonical\s+(\w+)\.(\w+)\s+values")
_RE_STRUCTURAL_DESC = re.compile(
    r"via\s+\(:(\w+)\)-\[:(\w+)\]->\(:(\w+)\)"
)
_RE_ALL_CAPS        = re.compile(r"^[A-Z][A-Z_]+$")   # rel type (e.g. ACTED_IN)
_RE_PASCAL          = re.compile(r"^[A-Z][a-z]\w*$")  # node label (e.g. Movie)


def _build_rel_connectivity_map(
    registry: Dict[str, BaseTool],
) -> Dict[str, Set[str]]:
    """
    Scan the full tool registry for structural relation tools and build a
    mapping ``{rel_type: {from_label, to_label}}``.

    Structural rel tool descriptions follow the pattern::

        "Find Movie.title values reachable via (:Person)-[:DIRECTED]->(:Movie)…"

    which yields ``{"DIRECTED": {"Person", "Movie"}}``.

    This map is used to resolve the connected node labels for
    *relationship-property* tools (e.g. ``get_acted_in_roles``) whose own
    descriptions don't mention node labels directly.
    """
    conn: Dict[str, Set[str]] = {}
    for tool_obj in registry.values():
        m = _RE_STRUCTURAL_DESC.search(tool_obj.description or "")
        if m:
            from_label = m.group(1)
            rel_type   = m.group(2)
            to_label   = m.group(3)
            conn.setdefault(rel_type, set()).update({from_label, to_label})
    return conn


def _is_rel_tool(tool_obj: BaseTool) -> bool:
    """
    Return *True* when *tool_obj* is a relation tool (property or structural).

    Heuristic:
    - Structural rel tool  → description contains ``"via (:"``
    - Rel-property tool    → description matches ``"canonical ALL_CAPS.prop"``
    """
    desc = tool_obj.description or ""
    if "via (:" in desc:
        return True
    m = _RE_NODE_DESC.search(desc)
    if m:
        return bool(_RE_ALL_CAPS.match(m.group(1)))
    return False


def _get_tool_node_labels(
    tool_obj: BaseTool,
    rel_conn: Dict[str, Set[str]],
) -> Set[str]:
    """
    Return the set of node labels that *tool_obj* relates to.

    ============== ======================================== =============
    Tool kind      Example description                      Labels
    ============== ======================================== =============
    Node           "canonical Movie.title values"           {"Movie"}
    Structural rel "via (:Person)-[:DIRECTED]->(:Movie)"    {"Person","Movie"}
    Rel property   "canonical ACTED_IN.roles values"        rel_conn["ACTED_IN"]
    ============== ======================================== =============

    Returns an empty set when the tool type cannot be determined.
    """
    desc = tool_obj.description or ""

    # ── Structural rel tool ────────────────────────────────────────────────────
    m = _RE_STRUCTURAL_DESC.search(desc)
    if m:
        return {m.group(1), m.group(3)}          # {from_label, to_label}

    # ── Node tool or rel-property tool ────────────────────────────────────────
    m = _RE_NODE_DESC.search(desc)
    if m:
        word = m.group(1)
        if _RE_ALL_CAPS.match(word):
            # Rel-property tool — look up connected labels from the map
            return rel_conn.get(word, set())
        if _RE_PASCAL.match(word):
            # Node tool
            return {word}

    return set()


def filter_tools_by_connectivity(
    selected_tools: List[BaseTool],
    registry: Optional[Dict[str, BaseTool]] = None,
    verbose: bool = False,
) -> List[BaseTool]:
    """
    Remove relation tools from *selected_tools* whose connected node labels
    have **no overlap** with the node labels already covered by the selected
    node tools.

    Algorithm
    ---------
    1. Build a ``{rel_type: {labels}}`` connectivity map from **all** tools in
       the full registry (structural rel tool docstrings encode the pattern
       ``(:{From})-[:{REL}]->(:{To})``).
    2. Collect the node labels covered by every *node* tool in the selection.
    3. For each *relation* tool in the selection, compute its connected labels
       and test whether they intersect with the node-label set from step 2.
       Drop the relation tool if the intersection is empty.

    Node tools are **always** kept.

    Parameters
    ----------
    selected_tools : Tools returned by :func:`select_tools_for_query`.
    registry       : Full tool registry.  When *None*, the module-level
                     singleton ``_registry`` is used.
    verbose        : Log which tools are dropped and why.

    Returns
    -------
    List[BaseTool]  Filtered tool list, preserving the original order.

    Example
    -------
    Suppose the query is *"movies directed by Spielberg"* and FAISS returns::

        [get_movie_title, get_acted_in_roles, get_follows_relation]

    Node labels from node tools = {``Movie``}

    ========================== ============================ ======
    Relation tool              Connected labels             Action
    ========================== ============================ ======
    ``get_acted_in_roles``     ``{Person, Movie}``          **KEEP**  (Movie ∈ {Movie})
    ``get_follows_relation``   ``{Person}``                 **DROP**  (Person ∉ {Movie})
    ========================== ============================ ======

    Result: ``[get_movie_title, get_acted_in_roles]``
    """
    if registry is None:
        registry = _get_registry()

    # Build {rel_type → {label, …}} from the full registry
    rel_conn = _build_rel_connectivity_map(registry)

    # ── Step 1: collect labels from selected NODE tools ────────────────────────
    selected_node_labels: Set[str] = set()
    for tool_obj in selected_tools:
        if not _is_rel_tool(tool_obj):
            labels = _get_tool_node_labels(tool_obj, rel_conn)
            selected_node_labels.update(labels)

    if not selected_node_labels:
        # Cannot determine node context → skip filtering to avoid dropping
        # all relation tools incorrectly.
        if verbose:
            logger.info(
                "filter_tools_by_connectivity: no node labels identified "
                "in selected tools — skipping filter."
            )
        return selected_tools

    # ── Step 2: filter ─────────────────────────────────────────────────────────
    kept:    List[BaseTool] = []
    dropped: List[BaseTool] = []

    for tool_obj in selected_tools:
        if not _is_rel_tool(tool_obj):
            kept.append(tool_obj)          # node tools are always kept
            continue

        labels = _get_tool_node_labels(tool_obj, rel_conn)
        if labels & selected_node_labels:
            kept.append(tool_obj)
        else:
            dropped.append(tool_obj)

    if verbose:
        if dropped:
            logger.info(
                f"filter_tools_by_connectivity: "
                f"selected node labels = {selected_node_labels}  |  "
                f"dropped {len(dropped)} unconnected relation tool(s): "
                f"{[t.name for t in dropped]}"
            )
        else:
            logger.info(
                f"filter_tools_by_connectivity: "
                f"selected node labels = {selected_node_labels}  |  "
                f"all {len(kept)} relation tools are connected — nothing dropped."
            )

    return kept


# ──────────────────────────────────────────────────────────────────────────────
# 6. Agent factory with auto tool selection
# ──────────────────────────────────────────────────────────────────────────────

def create_agent_auto(
    user_query:          str,
    top_k:               int  = DEFAULT_TOP_K,
    faiss_dir:           str  = FAISS_AUTO_DIR,
    rebuild:             bool = False,
    filter_connectivity: bool = True,
    verbose:             bool = False,
):
    """
    Build a LangGraph ReAct agent wired with only the tools that are
    semantically relevant to *user_query*.

    First calls :func:`select_tools_for_query` (which internally runs
    :func:`filter_tools_by_connectivity`) so the agent never receives
    relation tools that are disconnected from the selected node labels.

    Parameters
    ----------
    user_query           : The user's natural-language question.
    top_k                : How many FAISS-selected tools to start with (default 5).
    faiss_dir            : FAISS index directory.
    rebuild              : Force-rebuild the FAISS index.
    filter_connectivity  : Drop relation tools unconnected to selected node
                           labels (default *True*).
    verbose              : Log selected tools and filter decisions.

    Returns
    -------
    CompiledStateGraph  A LangGraph ReAct agent ready to ``.stream()``.

    Raises
    ------
    RuntimeError
        If no relevant tools remain after selection and filtering.
    """
    selected_tools = select_tools_for_query(
        user_query          = user_query,
        top_k               = top_k,
        faiss_dir           = faiss_dir,
        rebuild             = rebuild,
        filter_connectivity = filter_connectivity,
        verbose             = verbose,
    )

    if not selected_tools:
        raise RuntimeError(
            f"No tools selected for query {user_query!r}. "
            "Ensure generated tool files exist and the FAISS index is populated."
        )

    if verbose:
        names = [t.name for t in selected_tools]
        logger.info(f"Agent assembled with {len(selected_tools)} tools: {names}")

    return create_react_agent(
        model       = llm,
        tools       = selected_tools,
        prompt      = NER_SP,
        checkpointer= False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 7. Output parsing  (identical to ner_agent.py)
# ──────────────────────────────────────────────────────────────────────────────

def _to_list(v: Any) -> List[Any]:
    """Normalise any scalar / list-ish value into a plain Python list."""
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return list(v)
    return [v]


def extract_content(input_string: str) -> str:
    """
    Parse the agent's final message into a canonical JSON string of the form::

        {"Label.property": [values, ...]}

    Returns ``"{}"`` on any failure so downstream code never crashes.
    """
    if not input_string:
        return "{}"
    text = input_string.strip()

    # Strip optional markdown fences
    m = re.search(r"```(?:python|json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    parsed: Optional[Dict[str, Any]] = None
    for loader in (json.loads, ast.literal_eval):
        try:
            obj = loader(text)
            if isinstance(obj, dict):
                parsed = obj
                break
        except Exception:
            continue

    if parsed is None:
        return "{}"

    normalized = {k: _to_list(v) for k, v in parsed.items()}
    return json.dumps(normalized, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────────
# 8. Main entry points
# ──────────────────────────────────────────────────────────────────────────────

def get_ner_auto(
    prompt:    str,
    top_k:     int  = DEFAULT_TOP_K,
    faiss_dir: str  = FAISS_AUTO_DIR,
    rebuild:   bool = False,
    verbose:   bool = False,
) -> str:
    """
    Run the NER agent on *prompt* with auto-selected tools and return a
    canonical JSON string.

    This is the ``ner_agent_auto`` counterpart of ``ner_agent.get_ner()``.
    The return format is identical::

        '{"Movie.title": ["The Matrix"], "Movie.released": [1999]}'

    Parameters
    ----------
    prompt    : User's natural-language question.
    top_k     : Number of tools to select (default 5).
    faiss_dir : FAISS index directory.
    rebuild   : Force-rebuild the FAISS tool index.
    verbose   : Stream agent messages and print tool-selection details.

    Returns
    -------
    str  Canonical JSON string (``"{}"`` on failure).
    """
    inputs      = {"messages": [("user", prompt)]}
    agent_graph = create_agent_auto(
        user_query = prompt,
        top_k      = top_k,
        faiss_dir  = faiss_dir,
        rebuild    = rebuild,
        verbose    = verbose,
    )

    message = None
    for msgs in agent_graph.stream(inputs, stream_mode="values"):
        tool_msgs = [m for m in msgs["messages"] if isinstance(m, ToolMessage)]
        message   = msgs["messages"][-1]

        if verbose:
            if isinstance(message, tuple):
                logger.info(message)
            else:
                message.pretty_print()
            for tm in tool_msgs:
                logger.info(tm.content)

    if message is None:
        return "{}"

    return extract_content(message.content)


def get_ner_dict_auto(
    prompt:    str,
    top_k:     int  = DEFAULT_TOP_K,
    faiss_dir: str  = FAISS_AUTO_DIR,
    rebuild:   bool = False,
    verbose:   bool = False,
) -> Dict[str, List[Any]]:
    """
    Convenience wrapper around :func:`get_ner_auto` that returns a Python dict
    instead of a JSON string.

    Returns
    -------
    dict  ``{"Label.property": [values, ...]}`` or ``{}`` on failure.
    """
    raw = get_ner_auto(
        prompt    = prompt,
        top_k     = top_k,
        faiss_dir = faiss_dir,
        rebuild   = rebuild,
        verbose   = verbose,
    )
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# 9. Full pipeline: NER → Cypher → Neo4j → answer
# ──────────────────────────────────────────────────────────────────────────────

# Cypher generation prompt template.
# ``{relevant_entities}`` is filled at runtime with the NER output.
# ``{schema}`` and ``{question}`` are handled by GraphCypherQAChain.
CYPHER_TEMPLATE = """\
Task: Generate a Cypher statement to query a Neo4j database.

Rules:
- Use ONLY relationship types, labels, and properties present in the provided schema.
- Do NOT invent properties or relationship types not in the schema.
- Return ONLY the Cypher query (no backticks, no prose, no explanation).
- Prefer safe read patterns; avoid destructive operations (no WRITE, MERGE, DELETE).

Cypher rules for literals:
- DO NOT use Cypher parameters ($param). Inline all values as literals.
  GOOD: WHERE toLower(m.title) = toLower("Inception")
  BAD:  WHERE toLower(m.title) = toLower($movie_title)
- Inline numbers directly: 2015
- Inline strings with double quotes: "Inception", "CA"

Schema:
{schema}

Schema-relevant attribute and value pairs extracted from the question
(incorporate ALL of the following in the WHERE clause):
{relevant_entities}

User question:
{question}
"""


def ask_auto(
    prompt:    str,
    top_k:     int  = DEFAULT_TOP_K,
    faiss_dir: str  = FAISS_AUTO_DIR,
    rebuild:   bool = False,
    verbose:   bool = False,
) -> Dict[str, Any]:
    """
    Full end-to-end pipeline with auto tool selection:

    1. **NER** — :func:`get_ner_auto` extracts canonical entity values using
       only the FAISS-selected, connectivity-filtered tools.
    2. **Cypher generation** — injects the extracted entities into
       ``CYPHER_TEMPLATE`` and passes it to ``GraphCypherQAChain`` which asks
       the LLM to write a Cypher query against the actual schema.
    3. **Execution** — the chain runs the Cypher query on the connected
       Neo4j graph and formats the rows into a natural-language answer.

    Parameters
    ----------
    prompt    : User's natural-language question.
    top_k     : Number of tools to select via FAISS (default 5).
    faiss_dir : FAISS tool-index directory.
    rebuild   : Force-rebuild the FAISS index before running.
    verbose   : Stream agent messages, print tool-selection decisions, and
                enable ``GraphCypherQAChain`` verbose mode.

    Returns
    -------
    dict with keys:

    =========== ============================================================
    ``entities`` Canonical entity JSON string, e.g.
                 ``'{"Movie.released": [2015]}'``
    ``cypher``   The Cypher query generated by the LLM.
    ``result``   Natural-language answer produced by the QA LLM.
    ``context``  Raw list of dicts returned by Neo4j before formatting.
    =========== ============================================================

    Example
    -------
    >>> out = ask_auto("How many movies were released before 2000?")
    >>> print(out["cypher"])
    MATCH (m:Movie) WHERE m.released < 2000 RETURN count(m) AS total
    >>> print(out["result"])
    There are 23 movies released before 2000 in the database.
    """
    # ── Step 1: entity extraction (NER) ───────────────────────────────────────
    entities = get_ner_auto(
        prompt    = prompt,
        top_k     = top_k,
        faiss_dir = faiss_dir,
        rebuild   = rebuild,
        verbose   = verbose,
    )
    if verbose:
        print(f"\n── Extracted entities ──────────────────────────────────────────────")
        print(f"  {entities}")

    # ── Step 2: build the filled Cypher prompt ────────────────────────────────
    # Escape curly braces in the entity JSON so PromptTemplate doesn't treat
    # them as placeholder markers (e.g. {"Movie.released": [2015]} → safe).
    safe_entities = entities.replace("{", "{{").replace("}", "}}")
    filled = CYPHER_TEMPLATE.replace("{relevant_entities}", safe_entities)

    cypher_prompt = PromptTemplate(
        input_variables=["schema", "question"],
        template=filled,
    )

    # ── Step 3: build GraphCypherQAChain and run ──────────────────────────────
    chain = GraphCypherQAChain.from_llm(
        graph                    = neo4j_graph,
        llm                      = llm,          # answer-formatting LLM
        cypher_llm               = llm,          # Cypher-generation LLM
        cypher_prompt            = cypher_prompt,
        verbose                  = verbose,
        allow_dangerous_requests = True,
        return_intermediate_steps= True,
    )

    response = chain.invoke({"query": prompt})

    # ── Step 4: extract Cypher + raw context from intermediate steps ──────────
    cypher_query: str  = ""
    context:      list = []
    for step in response.get("intermediate_steps", []):
        if isinstance(step, dict):
            if "query" in step and not cypher_query:
                cypher_query = str(step["query"]).strip()
            if "context" in step:
                context = step["context"]

    result = str(response.get("result", "")).strip()

    if verbose:
        print(f"\n── Generated Cypher ────────────────────────────────────────────────")
        print(f"  {cypher_query}")
        print(f"\n── Answer ──────────────────────────────────────────────────────────")
        print(f"  {result}")

    return {
        "entities": entities,
        "cypher":   cypher_query,
        "result":   result,
        "context":  context,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 10. Utility: rebuild the FAISS index on demand
# ──────────────────────────────────────────────────────────────────────────────

def rebuild_tools_faiss(faiss_dir: str = FAISS_AUTO_DIR) -> int:
    """
    Force-rebuild the tool FAISS index from the current generated tool files.

    Call this after re-running ``gen_tools.py`` to pick up schema changes.

    Returns
    -------
    int  Number of tools indexed.
    """
    global _registry, _vectorstore
    _registry    = build_tool_registry()          # reload generated modules
    _vectorstore = get_or_build_tools_faiss(
        registry   = _registry,
        faiss_dir  = faiss_dir,
        rebuild    = True,
        embeddings = _get_embeddings(),
    )
    return len(_registry)


# ──────────────────────────────────────────────────────────────────────────────
# 11. Quick demo / smoke-test
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Full pipeline: NER (auto tool selection) → Cypher → answer."
    )
    ap.add_argument("prompt", nargs="?",
                    default="How many movies were released before 2000?")
    ap.add_argument("--top-k",    type=int,  default=DEFAULT_TOP_K,
                    help=f"Tools to select per query (default {DEFAULT_TOP_K})")
    ap.add_argument("--rebuild",  action="store_true",
                    help="Force-rebuild the FAISS tool index before running")
    ap.add_argument("--ner-only", action="store_true",
                    help="Run only the NER step (skip Cypher + Neo4j)")
    ap.add_argument("--verbose",  action="store_true",
                    help="Print tool-selection, agent trace, and chain details")
    args = ap.parse_args()

    print(f"\nPrompt : {args.prompt}")
    print(f"top_k  : {args.top_k}")
    print(f"rebuild: {args.rebuild}\n")

    # ── Step 1: show which tools were selected ────────────────────────────────
    print("── Selected tools (after connectivity filter) ──────────────────────")
    tools = select_tools_for_query(
        user_query = args.prompt,
        top_k      = args.top_k,
        rebuild    = args.rebuild,
        verbose    = True,
    )
    for i, t in enumerate(tools, 1):
        print(f"  {i}. {t.name:35s}  {t.description[:60]}")

    if args.ner_only:
        # ── NER only ─────────────────────────────────────────────────────────
        print("\n── NER result ──────────────────────────────────────────────────────")
        entities = get_ner_auto(
            prompt  = args.prompt,
            top_k   = args.top_k,
            rebuild = args.rebuild,
            verbose = args.verbose,
        )
        print("entities:", entities)
    else:
        # ── Full pipeline: NER → Cypher → Neo4j → answer ─────────────────────
        print("\n── Full pipeline (NER + Cypher + Neo4j) ────────────────────────────")
        out = ask_auto(
            prompt  = args.prompt,
            top_k   = args.top_k,
            rebuild = args.rebuild,
            verbose = args.verbose,
        )
        print("\nentities :", out["entities"])
        print("cypher   :", out["cypher"])
        print("result   :", out["result"])
