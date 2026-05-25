#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_system_prompt.py
====================
Introspects a live Neo4j database and generates ``prompts.py`` from scratch —
system prompts and schema constants tailored to the actual graph.

⚠ This script ONLY writes ``prompts.py``.  It never touches ``config.py``,
which is user-managed and holds hyperparameters (LLM configs, NER_MODE,
SAMPLE_T, …).  The split prevents user-edited settings from being clobbered
each time the schema is re-derived.

What is generated
-----------------
``prompts.py`` contains three sections:

  1. **System Prompts**
       NER_SP            – NER agent prompt with a dynamic tool list,
                           hard extraction rules, and schema-derived examples.
       TEXT2CYPHER_SP    – Text-to-Cypher prompt with the graph schema baked in.
       QA_SP             – Answer-formatting prompt for GraphCypherQAChain.
       PROMPT_ALIGNER_SP – Re-words user questions to match executed Cypher.

  2. **Schema Constants**  (auto-derived from the live graph)
       NODE_<LABEL>                  e.g. NODE_MOVIE = "Movie"
       PROPERTY_<LABEL>_<PROP>       e.g. PROPERTY_MOVIE_TITLE = "title"
       REL_<TYPE>                    e.g. REL_ACTED_IN = "ACTED_IN"
       REL_PROPERTY_<TYPE>_<PROP>    e.g. REL_PROPERTY_REVIEWED_RATING = "rating"
       FILTERABLE_<LABEL>_PROPERTIES – non-numeric properties per label

  3. **Index Constants**  (fulltext index names discovered from the graph)

Runtime hyperparameters (MAX_THREAD, DEFAULT_TOP_K, TOOL_TOP_K, STABILITY_K,
MAX_VALIDATION_ROUNDS, SAMPLE_T, CAP_MULTIPLIER, NER_MODE, *_LLM_CONFIG)
live in ``config.py`` and are NOT regenerated.

Usage
-----
  python gen_system_prompt.py                     # write prompts.py
  python gen_system_prompt.py --print-only        # preview, no write
  python gen_system_prompt.py --database movies
  python gen_system_prompt.py --output path/to/prompts.py

Environment variables  (loaded from .env)
-----------------------------------------
  NEO4J_URI          bolt / neo4j+s URI  (required)
  NEO4J_USERNAME                         (required)
  NEO4J_PASSWORD                         (required)
  NEO4J_DATABASE     default: neo4j
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import logging
import os
import re
import sys
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from .gen_schema_csv import collect_node_schema, collect_rel_schema
from paths import PROMPTS

load_dotenv()

# Module logger.  Per-step progress lines emitted from generate_all() flow
# through this logger so setup_project.py can route them to the file
# handler only by default; --verbose surfaces them on the console.
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Environment & driver helpers
# ──────────────────────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"Missing required env var: {name}. Set it in .env or system environment."
        )
    return v


def _get_driver():
    return GraphDatabase.driver(
        _require_env("NEO4J_URI"),
        auth=(_require_env("NEO4J_USERNAME"), _require_env("NEO4J_PASSWORD")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Identifier helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_const(s: str) -> str:
    """
    Convert a camelCase / PascalCase / snake_case identifier to SCREAMING_SNAKE.

    Examples:
        "Movie"      → "MOVIE"
        "born"       → "BORN"
        "storeNumber"→ "STORE_NUMBER"
        "ACTED_IN"   → "ACTED_IN"
    """
    # Insert underscore before uppercase letters that follow lowercase
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    return re.sub(r"[^A-Z0-9]", "_", s.upper()).strip("_")


def _is_numeric_type(types_str: str) -> bool:
    """Return True if the property type is purely numeric."""
    return bool(re.search(r"\b(Long|Integer|Float|Double)\b", types_str or ""))


# ──────────────────────────────────────────────────────────────────────────────
# Tool registry loader
# ──────────────────────────────────────────────────────────────────────────────

def _load_tool_registry() -> Dict[str, Any]:
    """
    Import generated_node_tools + generated_rel_tools and collect all BaseTool
    instances.  Returns {} (with a warning) if the modules are absent.
    """
    try:
        from langchain_core.tools import BaseTool
    except ImportError:
        return {}

    registry: Dict[str, Any] = {}
    for mod_name in ("generated.generated_node_tools", "generated.generated_rel_tools"):
        try:
            mod = importlib.import_module(mod_name)
            importlib.reload(mod)
            for name, obj in inspect.getmembers(mod):
                if isinstance(obj, BaseTool):
                    registry[name] = obj
        except ImportError:
            logger.warning("cannot import %r. Run `python gen_tools.py` first.",
                           mod_name)
    return registry


# ──────────────────────────────────────────────────────────────────────────────
# Fulltext index discovery
# ──────────────────────────────────────────────────────────────────────────────

def _discover_fulltext_indexes(driver, database: str) -> List[Dict[str, str]]:
    """
    Query the database for existing fulltext indexes.

    Returns list of dicts: {name, type, labelsOrTypes, properties}.
    """
    indexes = []
    try:
        with driver.session(database=database) as session:
            rows = list(session.run(
                "SHOW INDEXES YIELD name, type, labelsOrTypes, properties "
                "WHERE type = 'FULLTEXT' RETURN name, type, labelsOrTypes, properties"
            ))
            for r in rows:
                indexes.append({
                    "name":           str(r.get("name", "")),
                    "type":           str(r.get("type", "")),
                    "labelsOrTypes":  list(r.get("labelsOrTypes") or []),
                    "properties":     list(r.get("properties") or []),
                })
    except Exception:
        pass
    return indexes


# ──────────────────────────────────────────────────────────────────────────────
# Centrality helper
# ──────────────────────────────────────────────────────────────────────────────

def _label_centrality(label: str, rel_rows: List[Dict[str, Any]]) -> int:
    """Count how many relations have *label* as ``from_label``.

    Used to identify the graph's "central entity" — the label that appears
    most often as the source of relationships.  In the cypherbench/movie
    schema, ``Movie`` is the centre of gravity (it has many outgoing
    relations to Person, Genre, Country, Award, ProductionCompany, …),
    while ``Award``, ``Genre``, etc. are leaf entities.

    The default alphabetical sort would otherwise make few-shot examples
    revolve around ``Award`` (alphabetically first), which mis-teaches the
    LLM about which entity is the focus of typical questions.
    """
    return sum(1 for r in rel_rows if r.get("from_label") == label)


# ──────────────────────────────────────────────────────────────────────────────
# Schema block builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_schema_block(
    node_rows: List[Dict[str, Any]],
    rel_rows:  List[Dict[str, Any]],
) -> str:
    """
    Compact, human-readable schema block for embedding inside system prompts.

    Example::
        Node Labels and Properties:
          Movie  : released (Long), tagline (String), title (String)
          Person : born (Long), name (String)

        Relationships:
          (:Person)-[:ACTED_IN {roles: StringArray}]->(:Movie)
          (:Person)-[:DIRECTED]->(:Movie)
          ...
    """
    lines: List[str] = []

    # ── Nodes ─────────────────────────────────────────────────────────────────
    label_props: Dict[str, List[str]] = defaultdict(list)
    for r in node_rows:
        entry = r["property"]
        if r.get("property_types"):
            entry += f" ({r['property_types']})"
        label_props[r["label"]].append(entry)

    max_label_len = max((len(lb) for lb in label_props), default=8)
    lines.append("Node Labels and Properties:")
    for label in sorted(label_props):
        pad = " " * (max_label_len - len(label))
        lines.append(f"  {label}{pad} : {', '.join(sorted(label_props[label]))}")

    lines.append("")

    # ── Relationships ─────────────────────────────────────────────────────────
    rel_prop_map: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
    for r in rel_rows:
        key = (r["rel_type"], r["from_label"], r["to_label"])
        if r.get("property"):
            entry = r["property"]
            if r.get("property_types"):
                entry += f": {r['property_types']}"
            rel_prop_map[key].append(entry)
        else:
            rel_prop_map.setdefault(key, [])

    lines.append("Relationships:")
    for (rt, fl, tl) in sorted(rel_prop_map):
        props = rel_prop_map[(rt, fl, tl)]
        prop_part = f" {{{', '.join(props)}}}" if props else ""
        lines.append(f"  (:{fl})-[:{rt}{prop_part}]->(:{tl})")

    # ── Central entities (graph "centre of gravity") ──────────────────────────
    # Highlight the labels that appear most often as relationship sources.
    # This signals to the LLM where typical questions are anchored — without
    # it, the model treats all labels as equally likely subjects, which is a
    # bad assumption for hub-and-spoke schemas (Movie/Person/User/etc.).
    if label_props and rel_rows:
        central_labels = sorted(
            label_props.keys(),
            key=lambda lb: (-_label_centrality(lb, rel_rows), lb),
        )
        # Keep only labels that actually have outgoing relations
        central_labels = [
            lb for lb in central_labels if _label_centrality(lb, rel_rows) > 0
        ][:3]
        if central_labels:
            lines.append("")
            lines.append(
                f"Central entities (most relationships): {', '.join(central_labels)}"
            )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Tool-list formatter for NER prompt
# ──────────────────────────────────────────────────────────────────────────────

_RE_NODE_DESC   = re.compile(r"canonical\s+(\w+)\.(\w+)\s+values")
_RE_REL_PROP    = re.compile(r"canonical\s+([A-Z][A-Z_]+)\.(\w+)\s+values")
_RE_STRUCTURAL  = re.compile(
    r"Find\s+(\w+)\.(\w+)\s+values\s+reachable\s+via\s+\(:(\w+)\)-\[:(\w+)\]->\(:(\w+)\)"
)


def _format_tool_line(func_name: str, description: str) -> str:
    # ``.search`` (not ``.match``) is intentional: tool docstrings now begin
    # with action-oriented prose like ``"Look up canonical ..."`` /
    # ``"Find ..."`` — the regex-anchored phrase may appear anywhere in the
    # description.  Capture groups remain unchanged.
    m = _RE_STRUCTURAL.search(description)
    if m:
        to_label, prop, from_label, rel_type, _ = m.groups()
        return (
            f"  {func_name:<34}  {to_label}.{prop} values "
            f"via (:{from_label})-[:{rel_type}]->(:{to_label})"
        )
    m = _RE_REL_PROP.search(description)
    if m:
        rel_type, prop = m.groups()
        return f"  {func_name:<34}  canonical {rel_type}.{prop} values"
    m = _RE_NODE_DESC.search(description)
    if m:
        label, prop = m.groups()
        return f"  {func_name:<34}  canonical {label}.{prop} values"
    short = description.split("\n")[0][:72]
    return f"  {func_name:<34}  {short}"


def _build_tool_section(registry: Dict[str, Any]) -> str:
    """Return a formatted tool-list block for the NER prompt."""
    node_lines:   List[str] = []
    rel_p_lines:  List[str] = []
    struct_lines: List[str] = []

    for func_name, tool_obj in sorted(registry.items()):
        desc  = (tool_obj.description or "").strip()
        line  = _format_tool_line(func_name, desc)
        # ``.search`` matches the regex-anchored phrase regardless of the
        # leading action prose ("Look up canonical …" / "Find …").
        if _RE_STRUCTURAL.search(desc):
            struct_lines.append(line)
        elif _RE_REL_PROP.search(desc):
            rel_p_lines.append(line)
        else:
            node_lines.append(line)

    parts: List[str] = []
    if node_lines:
        parts.append("  ── Node property tools ──\n" + "\n".join(node_lines))
    if rel_p_lines:
        parts.append("  ── Relationship property tools ──\n" + "\n".join(rel_p_lines))
    if struct_lines:
        parts.append("  ── Structural traversal tools ──\n" + "\n".join(struct_lines))

    return "\n\n".join(parts) if parts else "  (no tools loaded — run `python gen_tools.py`)"


# ──────────────────────────────────────────────────────────────────────────────
# Few-shot example derivation
# ──────────────────────────────────────────────────────────────────────────────

def _derive_few_shot(
    node_rows: List[Dict[str, Any]],
    rel_rows:  List[Dict[str, Any]],
) -> List[Tuple[str, str]]:
    """
    Return up to 5 (question, answer) tuples derived from the actual schema.
    """
    examples: List[Tuple[str, str]] = []

    # Order node_rows so that rows belonging to the most-central labels come
    # first.  Without this, alphabetical iteration biases all examples toward
    # leaf entities (e.g. "Award" comes before "Movie"), which mis-teaches the
    # NER agent about which entity the typical question is anchored on.
    # Stable sort: ties fall back to original order.
    _orig_node_index = {id(r): i for i, r in enumerate(node_rows)}
    sorted_node_rows = sorted(
        node_rows,
        key=lambda r: (
            -_label_centrality(r["label"], rel_rows),
            _orig_node_index[id(r)],
        ),
    )

    # ── 1. Identifying String property (title / name / id) ────────────────────
    # NOTE on output shape: single-entity questions emit a BARE SCALAR value
    # (no [...] wrapper).  This prevents the brackets from leaking verbatim
    # into the downstream Cypher query (a frequent failure mode where the
    # LLM copies ``["Inception"]`` into ``n.title = ["Inception"]``).
    # Multi-value examples still use JSON arrays -- see example #6 below.
    for r in sorted_node_rows:
        prop = r["property"].lower()
        if prop in ("title", "name", "id") and "String" in r.get("property_types", ""):
            label  = r["label"]
            prop_  = r["property"]
            sample = (r.get("sample_values") or "").split(" | ")[0].strip()
            sample = sample or f"Example {label}"
            examples.append((
                f'Find the {label.lower()} named "{sample}".',
                f'{{"{label}.{prop_}": "{sample}"}}',
            ))
            break

    # ── 2. Numeric property (released / born / year) ──────────────────────────
    for r in sorted_node_rows:
        prop = r["property"].lower()
        types = r.get("property_types", "")
        if prop in ("released", "born", "year") and _is_numeric_type(types):
            label  = r["label"]
            prop_  = r["property"]
            sample = (r.get("sample_values") or "").split(" | ")[0].strip()
            try:
                num = int(float(sample))
            except (ValueError, TypeError):
                num = 1999
            examples.append((
                f"How many {label.lower()}s have {prop_} before {num}?",
                f'{{"{label}.{prop_}": {num}}}',
            ))
            break

    # ── 3. Second String property (e.g. tagline, summary) ─────────────────────
    count = 0
    for r in sorted_node_rows:
        prop  = r["property"].lower()
        types = r.get("property_types", "")
        if prop not in ("title", "name", "id", "released", "born") and "String" in types:
            label  = r["label"]
            prop_  = r["property"]
            sample = (r.get("sample_values") or "").split(" | ")[0].strip()
            if sample:
                examples.append((
                    f'Which {label.lower()} has {prop_} containing "{sample[:30]}"?',
                    f'{{"{label}.{prop_}": "{sample[:30]}"}}',
                ))
                count += 1
                if count >= 1:
                    break

    # ── 4. Relationship property (e.g. ACTED_IN.roles) ────────────────────────
    for r in rel_rows:
        if r.get("property"):
            rt     = r["rel_type"]
            prop_  = r["property"]
            fl     = r["from_label"]
            tl     = r["to_label"]
            sample = (r.get("sample_values") or "").split(" | ")[0].strip()
            sample = sample or "Example Role"
            examples.append((
                f'Which {fl.lower()} has {rt.lower()} {prop_} "{sample}"?',
                f'{{"{rt}.{prop_}": "{sample}"}}',
            ))
            break

    # ── 5. Pure traversal / no entities ───────────────────────────────────────
    # Use unambiguously-global phrasing ("every entity", "show every") so the
    # agent doesn't confuse this with a constrained "list all X with Y" query
    # that still requires entity extraction.
    examples.append((
        "Show every entity in the graph.",
        "{}",
    ))

    # ── 6. Multi-entity meta-example (Coverage > caution) ─────────────────────
    # The first 5 examples each show ONE entity-type extraction.  The agent
    # learns the implicit pattern "one question → one entity type" and stops
    # after the most salient match.  Example 6 deliberately fans out across
    # TWO entity types (a node-property AND a relationship-property) so the
    # agent learns to keep going.
    #
    # Schema-agnostic construction:
    #   L1, prop1     — first node label with a String "name"/"title" property.
    #   R, propR      — first relationship type that has any property.
    # If either is unavailable, the example is skipped here and
    # ``generate_ner_sp`` injects a static fallback meta-instruction instead.
    L1: Optional[str]    = None
    prop1: Optional[str] = None
    sample_name: str     = ""
    for r in sorted_node_rows:
        prop_lower = r["property"].lower()
        if prop_lower in ("title", "name") and "String" in r.get("property_types", ""):
            L1    = r["label"]
            prop1 = r["property"]
            sv = (r.get("sample_values") or "").split(" | ")[0].strip()
            sample_name = sv or f"Example {L1}"
            break

    R: Optional[str]     = None
    propR: Optional[str] = None
    sample1: str         = ""
    sample2: str         = ""
    for r in rel_rows:
        if r.get("property"):
            R     = r["rel_type"]
            propR = r["property"]
            sv_list = [
                s.strip()
                for s in (r.get("sample_values") or "").split(" | ")
                if s.strip()
            ]
            sample1 = sv_list[0] if sv_list else "ValueA"
            sample2 = sv_list[1] if len(sv_list) > 1 else "ValueB"
            break

    if L1 and R and prop1 and propR:
        l1_lower = L1.lower()
        # Phrase the question with explicit "or" wording (teaches OR/IN logic)
        # and "specifically" disambiguation (signals which mention is the
        # entity name vs. the property values).  This is materially clearer
        # than the previous "Find X related to <rel_type>" phrasing, which
        # awkwardly leaks the relationship type into the natural language.
        q = (
            f'Find {l1_lower}s where {propR} is "{sample1}" or "{sample2}", '
            f'specifically the {l1_lower} named "{sample_name}".'
        )
        # Output shape is uniform regardless of whether ``propR`` is scalar or
        # list-typed: the entity-filter value is simply a flat JSON array of
        # the two candidate values.  The Cypher LLM decides whether to emit
        # ``IN``/``=``/``OR``-of-``IN`` based on the SCHEMA type of the
        # property -- it does not need (and must not see) any structural
        # hint from the value shape.
        rel_values = f'["{sample1}", "{sample2}"]'
        # ``{L1}.{prop1}`` carries the disambiguating entity name -- a single
        # value, so emit it as a bare scalar (no [...] wrapper).
        a = (
            f'{{"{R}.{propR}": {rel_values}, '
            f'"{L1}.{prop1}": "{sample_name}"}}'
        )
        examples.append((q, a))

    return examples[:6]


# ──────────────────────────────────────────────────────────────────────────────
# PROMPT GENERATORS
# ──────────────────────────────────────────────────────────────────────────────

def generate_ner_sp(
    node_rows: List[Dict[str, Any]],
    rel_rows:  List[Dict[str, Any]],
    registry:  Optional[Dict[str, Any]] = None,
) -> str:
    """Generate the NER agent system prompt.

    The "Available tools" block is intentionally emitted as a ``{tool_list}``
    placeholder.  The actual tool names are unknown at generation time — they
    are decided at runtime by ``ner_agent_auto.py`` after FAISS-based tool
    selection (see ``_build_dynamic_prompt``).  Baking a static tool list
    here would (a) drift the moment ``gen_tools.py`` re-runs and
    (b) advertise tools that the live agent has not registered.

    The ``registry`` parameter is accepted for backward compatibility but
    is ignored — kept so existing callers don't have to change signatures.
    """
    _ = registry  # intentionally unused — see docstring
    examples = _derive_few_shot(node_rows, rel_rows)

    # Build key-format note from actual labels
    key_samples = [
        f'"{r["label"]}.{r["property"]}"' for r in node_rows[:3]
    ]
    key_note = ", ".join(key_samples) if key_samples else '"Label.property"'

    example_block = "\n\n".join(
        f"Q: {q}\nA: {a}" for q, a in examples
    )

    # If ``_derive_few_shot`` could not construct a multi-entity example
    # (the schema lacks a relationship-with-property), inject a static
    # meta-instruction so the agent still receives the "fan out across
    # entity types" lesson.  Five base examples + the dynamic example would
    # be six; anything less means dynamic construction was skipped.
    #
    # Wording is bounded ("ALL of them" but subject to rule 7's 4-call
    # hard budget) — earlier "Never stop after the first successful
    # lookup" wording combined with the unconditional rule 7 to push the
    # agent past its ReAct recursion budget on multi-entity questions.
    if len(examples) < 6:
        example_block += (
            "\n\nNote: When a question mentions multiple distinct entity "
            "types (e.g. both a movie AND the role played in it), call "
            "the appropriate name/title tool for each one and include "
            "ALL resolved keys in the output JSON.  Respect the rule-7 "
            "budget: at most 1 call per mention, at most 4 calls total."
        )

    # NOTE: ``{{tool_list}}`` is a literal placeholder in the emitted prompt
    # (we double the braces to escape the f-string).  At runtime,
    # ``ner_agent_auto._build_dynamic_prompt`` substitutes this token with
    # the rendering of the FAISS-selected tools that were actually
    # registered with the ReAct agent.
    return f"""\
You are a strict Named Entity Recognition (NER) agent for a Neo4j graph database.

Your sole responsibility: extract named entities from the user question and
resolve each one to its canonical database value using the provided tools.

Available tools
───────────────
{{tool_list}}

Extraction rules (follow strictly)
────────────────────────────────────
1.  Extract ONLY entities that are explicitly mentioned in the question.
    If no relevant entity exists, return an empty JSON object {{}}.

2.  Use a tool for every string entity that needs database lookup.
    Exception: purely numeric values (years, IDs, counts) must be returned
    inline as numbers — do NOT call a tool for them.

3.  A match is valid ONLY when it is:
    (a) a lexical match (case-insensitive), OR
    (b) semantically identical (same real-world referent).
    Never fabricate or guess values beyond what the tools return.

4.  Return the single best-matching canonical value per key by default.
    Return multiple values (up to 2) ONLY when the question explicitly
    mentions multiple distinct entities of the same type:
      - "compare X and Y"
      - "movies by Spielberg or Tarantino"
      - "either A or B"
    Single-entity questions MUST emit a bare scalar value, NOT a 1-element
    list.  (Wrapping a single value in [...] tends to leak the brackets
    into the downstream Cypher query.)

5.  If a tool returns NO matching values (empty result), drop that key from
    the output.  Do NOT fabricate a value.  (But always TRY the lookup
    first per rule 7 — never skip a call because you predict it will be
    empty.)

6.  Final output MUST be a single valid JSON object — nothing else.
    • Keys   : "Label.property" format (e.g. {key_note})
    • Values :
        - SINGLE value  → bare scalar  (e.g. "Inception" or 2015)
        - MULTIPLE values (2+) → JSON array  (e.g. ["Neo", "Morpheus"])
        - NEVER mix: do NOT wrap a single value in a 1-element list.
    • No code fences, no markdown, no explanation, no extra text.

7.  Coverage over caution (bounded): For each PROPER-NAME mention in the
    question (a specific person, movie, organization, award, place, etc.),
    call exactly ONE tool against the entity's primary name/title field
    — the {{Label}}.name or {{Label}}.title tool — even if the mention is
    lowercase, partial, abbreviated, or informal ("chicago" for "Chicago,
    IL", "gates" for "Bill Gates", "pirates" for "Pirates of the
    Caribbean").  Let the tool decide whether the mention matches.

    HARD BUDGET — DO NOT EXCEED:
      • At most 1 tool call per distinct proper-name mention.
      • At most 4 tool calls total per question.
      • NEVER call multiple tools for the same mention "just to be sure"
        (do NOT try {{Label}}.eid, {{Label}}.aliases, {{Label}}.provenance
        on a name mention — those fields are for opaque identifiers and
        URLs, not names; each tool's docstring tells you exactly when it
        is appropriate to call).
      • If your first 4 tool calls have not resolved every mention, STOP
        and emit the partial result.  Do NOT keep searching.

    Why the budget exists: each tool call costs an LLM round-trip plus a
    database query.  Without the budget, multi-entity questions blow the
    per-example time budget and the agent is terminated mid-search.

8.  Distinguish filter values from generic schema terms:
    - Filter values: specific named entities mentioned as the SUBJECT of
      a constraint ("Tom Hanks", "Inception", "Best Picture", "1995").
    - Generic schema terms: words that describe the QUERY SHAPE without
      naming specific entities ("movie", "director", "actor", "person",
      "genre", "country").
    Call tools ONLY for filter values, NOT for generic schema terms.
    Generic terms map to schema labels/relations that the Cypher generator
    handles structurally; they don't need canonical lookup.

    Examples:
      Q: "Who directed Inception?"
         filter values: ["Inception"]   generic: ["who", "directed"]
         → Call Movie.name tool for "Inception", NOT Person.name tool for "who".

      Q: "List directors of Italian movies."
         filter values: ["Italian"]     generic: ["directors", "movies"]
         → Call Country.name tool for "Italian", NOT Person.name for "directors".

Examples
────────
{example_block}"""


def generate_text2cypher_sp(
    node_rows: List[Dict[str, Any]],
    rel_rows:  List[Dict[str, Any]],
) -> str:
    """Generate the text-to-Cypher system prompt with schema baked in."""
    schema_block = _build_schema_block(node_rows, rel_rows)
    indented     = textwrap.indent(schema_block, "    ")

    # Collect string properties for filter guidance
    string_props: List[str] = []
    for r in node_rows:
        if "String" in r.get("property_types", ""):
            string_props.append(f'{r["label"]}.{r["property"]}')

    filter_note = ""
    if string_props:
        examples_str = ", ".join(string_props[:3])
        filter_note = (
            f"\n- String comparisons: prefer exact-case equality (`n.prop = \"value\"`) "
            f"for entity values supplied via the \"Schema-relevant entity filters\" "
            f"section — these are already canonicalized by the retrieval pipeline. "
            f"Use `toLower(n.prop) = toLower(\"value\")` only for free-text user input "
            f"that hasn't been resolved to a canonical entity."
        )

    return f"""\
Task: Generate a single READ-ONLY Cypher query to answer the user question.

Output format
─────────────
Return ONLY the Cypher query — no backticks, no code fences, no explanation.

Generation rules
────────────────
- Schema adherence : use ONLY the labels, relationship types, and properties
  defined in the schema below. Never invent new ones.
- Read-only        : never generate CREATE / MERGE / SET / DELETE / REMOVE.
- No parameters    : do NOT use $param syntax; always inline literal values.
  ✓  WHERE m.name = "Inception"        # entity from retrieval
  ✗  WHERE m.title = $title
- Aliases          : aliases are optional. When the question asks for a
  single property, return it directly without alias (e.g. `RETURN m.name`).
  Use snake_case aliases only when needed for disambiguation (multiple
  result columns from the same node, or aggregation results).
- LIMIT            : only add LIMIT when the question explicitly requests
  a bounded number of results ("top N", "first N", "the three most ...").
  Do NOT add LIMIT to general listing queries ("list all X", "find Y",
  "what are the Z") — these expect complete results.{filter_note}
- Entity filters   : when entity values are supplied in the "Schema-relevant
  entity filters" section, use them in the query.  Values come in TWO
  shapes -- pick the predicate based on (a) the SCHEMA type of the target
  property and (b) the shape of the supplied value:

    Schema type     Value shape         Predicate
    ----------      ----------          --------------------------------------
    scalar          scalar              n.prop = "v"        (or toLower(...))
    scalar          array  [v1, v2]     n.prop IN ["v1","v2"]
    list/array      scalar              "v" IN n.prop
    list/array      array  [v1, v2]     ("v1" IN n.prop OR "v2" IN n.prop)

  Combine multiple entity filters using question semantics:
    - "and", "both", "with X and Y"  →  AND in WHERE
    - "or", "either", "X or Y"        →  OR in WHERE, or UNION across MATCH
  When the question contains "either ... or" referring to different schema
  paths (different relations or labels), prefer UNION across separate MATCH
  blocks. Use a single MATCH with AND only when ALL filters logically must
  hold simultaneously.

  Anti-patterns -- never emit any of these:
    ✗  ``n.prop = ["Inception"]``       (copying a wrapper that was never there)
    ✗  ``["design"] IN r.tags``         (list-in-array never matches)
    ✗  ``r.tags CONTAINS "design"``     (CONTAINS is string-substring only)

- Empty entity filters : when "Schema-relevant entity filters" is empty,
  the question is global / unbounded ("list all", "what are all", "which X
  exist", "show every Y"). Write the query using only schema structure
  without WHERE-clause entity filters. The MATCH pattern alone defines the
  result set.

Examples
────────
# 1. Simple lookup (return literal value, not node)
Schema: (:Book {{{{name: String}}}})
Question: Find the book named "The Long Voyage".
Cypher:
  MATCH (b:Book {{{{name: "The Long Voyage"}}}})
  RETURN b.name

# 2. List-typed property (IN) -- multi-value filter
Schema: (:Employee)-[:WORKED_ON {{{{tags: StringArray}}}}]->(:Project)
Question: Find employees whose contributions to a project are tagged "design" or "review".
Schema-relevant entity filters:
  {{{{"WORKED_ON.tags": ["design", "review"]}}}}
Cypher:
  MATCH (e:Employee)-[r:WORKED_ON]->(p:Project)
  WHERE "design" IN r.tags OR "review" IN r.tags
  RETURN DISTINCT e.name

# 2b. List-typed property (IN) -- single-value filter (scalar form)
Schema: (:Person)-[:ACTED_IN {{{{roles: StringArray}}}}]->(:Movie)
Question: Who played Neo?
Schema-relevant entity filters:
  {{{{"ACTED_IN.roles": "Neo"}}}}
Cypher:
  MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
  WHERE "Neo" IN r.roles
  RETURN DISTINCT p.name

# 3. Numeric scalar comparison
Schema: (:Customer)-[:BOUGHT {{{{rating: Float}}}}]->(:Product)
Question: Which customers gave a rating above 4.5?
Cypher:
  MATCH (c:Customer)-[r:BOUGHT]->(p:Product)
  WHERE r.rating > 4.5
  RETURN c.name AS customer_name, r.rating AS rating

# 4. Aggregation (COUNT) — CypherBench template style
Schema: (:City)-[:LOCATED_IN]->(:Country)
Question: How many cities are located in country "Imaginaria"?
Cypher:
  MATCH (n:City)-[:LOCATED_IN]->(co:Country {{{{name: "Imaginaria"}}}})
  WITH DISTINCT n
  RETURN count(n)

# 5. Multi-hop traversal
Schema: (:Author)-[:WROTE]->(:Book)-[:BELONGS_TO]->(:Genre)
Question: Find authors who wrote books in the genre "Fantasy".
Cypher:
  MATCH (a:Author)-[:WROTE]->(b:Book)-[:BELONGS_TO]->(g:Genre)
  WHERE g.name = "Fantasy"
  RETURN DISTINCT a.name

# 6. UNION across two relationship types
Schema: (:Person)-[:LIKES]->(:Topic), (:Person)-[:STUDIES]->(:Topic)
Question: Find people who like or study topic "AI".
Cypher:
  MATCH (p:Person)-[:LIKES]->(t:Topic {{{{name: "AI"}}}})
  RETURN p.name
  UNION
  MATCH (p:Person)-[:STUDIES]->(t:Topic {{{{name: "AI"}}}})
  RETURN p.name

# 7. GROUP BY with sort (no entity filter)
Schema: (:Department)<-[:WORKS_IN]-(:Employee)
Question: List all departments and their employee counts.
Cypher:
  MATCH (d:Department)<-[:WORKS_IN]-(e:Employee)
  RETURN d.name AS department, count(e) AS employee_count
  ORDER BY employee_count DESC

# 8. WITH DISTINCT for deduplication after MATCH (template-style query)
Schema: (:Movie)-[:hasCastMember]->(:Person)
Question: How many movies feature actor "Tom Hanks"?
Cypher:
  MATCH (n:Movie)-[r:hasCastMember]->(m:Person {{{{name: "Tom Hanks"}}}})
  WITH DISTINCT n
  RETURN count(n)

# 9. Listing with WITH DISTINCT (CypherBench template — most common pattern)
Schema: (:Movie)-[:hasGenre]->(:Genre)
Question: List the names of movies in the genre "Drama".
Cypher:
  MATCH (n:Movie)-[r0:hasGenre]->(m0:Genre {{{{name: "Drama"}}}})
  WITH DISTINCT n
  RETURN n.name

# 10. OPTIONAL MATCH for "include X even if no related Y"
Schema: (:Author)-[:WROTE]->(:Book), (:Book)-[:HAS_REVIEW]->(:Review)
Question: List all authors and the number of reviews each has received (including authors with zero reviews).
Cypher:
  MATCH (n:Author)-[:WROTE]->(b:Book)
  OPTIONAL MATCH (b)-[:HAS_REVIEW]->(rv:Review)
  WITH n, count(DISTINCT rv) AS review_count
  RETURN n.name, review_count

Graph Schema (static snapshot — baked at generation time)
──────────────────────────────────────────────────────────
{indented}

Live schema (injected at runtime by GraphCypherQAChain — authoritative):
{{schema}}

Schema-relevant entity filters
───────────────────────────────
(Pre-filled by the NER pipeline.  Keys are "Label.property"; values are
canonical matches from the database.  Use ALL provided pairs in WHERE.)

{{relevant_entities}}

Question: {{question}}
Answer:"""


def generate_qa_sp() -> str:
    """Generate the QA answer-formatting system prompt (domain-agnostic)."""
    return """\
You are a helpful AI assistant that answers questions about a graph database.

Rules
─────
1.  Ground all answers strictly in the "Relevant Data" provided.
    Never use internal knowledge to add, correct, or contradict the data.
2.  If Relevant Data is empty, contains no rows, or is irrelevant to the
    question, say explicitly: "The database returned no results for this
    query."  Do NOT fabricate, guess, or infer an answer from your own
    knowledge.
3.  Be concise, accurate, and use natural language.
4.  When the question asks for a list, provide it in bullet-point or table form.
5.  When the question asks for a count or aggregate, state the number directly.
6.  Do NOT expose raw Neo4j node IDs or internal identifiers.

Output format
─────────────
- For narrative answers : plain prose with bullet points where helpful.
- For tabular data      : a markdown table with clear column headers.
- For counts / numbers  : state the figure prominently at the start.

Examples
────────
Q: Who is associated with item "Alpha"?
Relevant Data: [{{"name": "Alice"}}]
A: Alice is associated with item "Alpha".

Q: How many records were created before 2020?
Relevant Data: [{{"count": 42}}]
A: There are 42 records created before 2020 in the database.

Q: What are the properties of node "X"?
Relevant Data: [{{"property": "status", "value": "active"}}, {{"property": "region", "value": "west"}}]
A:
Node "X" has the following properties:
| Property | Value  |
|----------|--------|
| status   | active |
| region   | west   |

Q: Who directed "Nonexistent Movie"?
Relevant Data: []
A: The database returned no results for this query.  There is no record matching "Nonexistent Movie" in the graph.

Now answer the following:

Question: {{question}}
Relevant Data:
{{context}}
Answer:"""


def generate_prompt_aligner_sp() -> str:
    """Generate the prompt-aligner system prompt (domain-agnostic)."""
    return """\
You are a Cypher query expert helping to align a user question with the query
that was actually executed against the graph database.

Context
───────
Users sometimes phrase questions using informal language, incorrect property
names, or assumptions about the schema.  The system generates the closest
valid Cypher query it can.  Your task is to rephrase the user question so it
accurately reflects what the executed Cypher query does — making it clear
which labels, properties, and filter values were used.

Rules
─────
- Output ONLY the rephrased question — no explanation, no extra text.
- Expand abbreviations and acronyms where you can infer the full form.
- If the Cypher query filters by a specific property value (e.g. a label,
  type, or dimension), include that value in the rephrased question.
- Keep the rephrased question as close to the original intent as possible.

Examples
────────
[user_question]  What items does Alice manage?
[cypher_query]   MATCH (p:Person {{name: "Alice Smith"}})-[:MANAGES]->(i:Item)
                 RETURN i.name AS item_name
[rephrased]      What items does Alice Smith manage?

[user_question]  Find old records.
[cypher_query]   MATCH (r:Record) WHERE r.created_year < 2000 RETURN r.name, r.created_year
[rephrased]      Find records created before the year 2000.

Now rephrase:

[user_question]
{{user_question}}

[cypher_query]
{{cypher_query}}

[rephrased]"""


# ──────────────────────────────────────────────────────────────────────────────
# Schema constants generator
# ──────────────────────────────────────────────────────────────────────────────

def generate_schema_constants(
    node_rows:  List[Dict[str, Any]],
    rel_rows:   List[Dict[str, Any]],
    ft_indexes: List[Dict[str, str]],
) -> str:
    """
    Emit Python constant declarations derived from the live schema.

    Sections produced:
    • Node label constants         NODE_<LABEL>
    • Node property constants      PROPERTY_<LABEL>_<PROP>
    • Filterable property lists    FILTERABLE_<LABEL>_PROPERTIES
    • Relationship type constants  REL_<TYPE>
    • Rel property constants       REL_PROPERTY_<TYPE>_<PROP>
    • Fulltext index constants     FULLTEXT_INDEX_<NAME>
    """
    lines: List[str] = []

    # ── Node labels ───────────────────────────────────────────────────────────
    labels: List[str] = sorted({r["label"] for r in node_rows})
    lines.append("# Node labels")
    for label in labels:
        lines.append(f'NODE_{_to_const(label)} = "{label}"')
    lines.append("")

    # ── Node properties ───────────────────────────────────────────────────────
    lines.append("# Node properties")
    for label in labels:
        props = sorted({r["property"] for r in node_rows if r["label"] == label})
        for prop in props:
            const = f"PROPERTY_{_to_const(label)}_{_to_const(prop)}"
            lines.append(f'{const} = "{prop}"')
    lines.append("")

    # ── Filterable property lists (non-numeric, non-embedding) ────────────────
    lines.append("# Filterable properties per node label")
    skip_props = {"embedding", "vector", "id"}
    for label in labels:
        props = sorted(
            r["property"]
            for r in node_rows
            if r["label"] == label
            and r["property"].lower() not in skip_props
            and not _is_numeric_type(r.get("property_types", ""))
        )
        const = f"FILTERABLE_{_to_const(label)}_PROPERTIES"
        prop_list = ", ".join(f'"{p}"' for p in props)
        lines.append(f"{const} = [{prop_list}]")
    lines.append("")

    # ── Relationship types ────────────────────────────────────────────────────
    rel_types: List[str] = sorted({r["rel_type"] for r in rel_rows})
    lines.append("# Relationship types")
    for rt in rel_types:
        lines.append(f'REL_{_to_const(rt)} = "{rt}"')
    lines.append("")

    # ── Relationship properties ───────────────────────────────────────────────
    rel_with_props = [r for r in rel_rows if r.get("property")]
    if rel_with_props:
        lines.append("# Relationship properties")
        for r in sorted(rel_with_props, key=lambda x: (x["rel_type"], x["property"])):
            const = f"REL_PROPERTY_{_to_const(r['rel_type'])}_{_to_const(r['property'])}"
            lines.append(f'{const} = "{r["property"]}"')
        lines.append("")

    # ── Fulltext indexes ──────────────────────────────────────────────────────
    if ft_indexes:
        lines.append("# Fulltext index names")
        for idx in sorted(ft_indexes, key=lambda x: x["name"]):
            const = f"FULLTEXT_INDEX_{_to_const(idx['name'])}"
            lines.append(f'{const} = "{idx["name"]}"')
        lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# prompts.py assembler
# ──────────────────────────────────────────────────────────────────────────────

def _triple_quote(s: str) -> str:
    """Wrap *s* in a triple-quoted Python string literal."""
    # Escape any triple-double-quote sequences that would break the literal
    escaped = s.replace('\\', '\\\\').replace('"""', r'\"\"\"')
    return f'"""\\\n{escaped}\n"""'


def generate_prompts_py(
    node_rows:  List[Dict[str, Any]],
    rel_rows:   List[Dict[str, Any]],
    ft_indexes: List[Dict[str, str]],
    registry:   Optional[Dict[str, Any]] = None,
    database:   str = "neo4j",
) -> str:
    """
    Assemble the complete ``prompts.py`` content as a string.

    Parameters
    ----------
    node_rows   : from collect_node_schema()
    rel_rows    : from collect_rel_schema()
    ft_indexes  : from _discover_fulltext_indexes()
    registry    : {func_name: BaseTool} from _load_tool_registry()
    database    : Neo4j database name (used in header comment only)

    Returns
    -------
    str  Full Python source for prompts.py.
    """
    if registry is None:
        registry = _load_tool_registry()

    ner_sp         = generate_ner_sp(node_rows, rel_rows, registry)
    text2cypher_sp = generate_text2cypher_sp(node_rows, rel_rows)
    qa_sp          = generate_qa_sp()
    aligner_sp     = generate_prompt_aligner_sp()
    schema_consts  = generate_schema_constants(node_rows, rel_rows, ft_indexes)

    sections: List[str] = []

    # ── File header ───────────────────────────────────────────────────────────
    sections.append(
        "# AUTO-GENERATED by gen_system_prompt.py — do not edit manually.\n"
        f"# Database : {database}\n"
        "# Re-run `python gen_system_prompt.py` to regenerate from the live schema.\n"
        "#\n"
        "# This file contains ONLY auto-generated content:\n"
        "#   • System prompts (NER_SP, TEXT2CYPHER_SP, QA_SP, PROMPT_ALIGNER_SP)\n"
        "#   • Schema constants derived from the live Neo4j graph\n"
        "#\n"
        "# User-managed hyperparameters (LLM configs, NER_MODE, SAMPLE_T, …) live\n"
        "# in ``config.py`` and are NEVER overwritten by ``gen_system_prompt.py``.\n"
    )

    # ── System prompts ────────────────────────────────────────────────────────
    sections.append(
        "# ──────────────────────────────────────────────────────────────────────────────\n"
        "# System Prompts\n"
        "# ──────────────────────────────────────────────────────────────────────────────\n"
    )

    sections.append(f"NER_SP = {_triple_quote(ner_sp)}\n")
    sections.append(f"TEXT2CYPHER_SP = {_triple_quote(text2cypher_sp)}\n")
    sections.append(f"QA_SP = {_triple_quote(qa_sp)}\n")
    sections.append(f"PROMPT_ALIGNER_SP = {_triple_quote(aligner_sp)}\n")

    # ── Schema constants ──────────────────────────────────────────────────────
    sections.append(
        "# ──────────────────────────────────────────────────────────────────────────────\n"
        "# Schema Constants  (auto-derived from the live Neo4j database)\n"
        "# ──────────────────────────────────────────────────────────────────────────────\n"
    )
    sections.append(schema_consts)

    return "\n".join(sections)


# Backward-compatible alias — older imports may still reference the old name.
generate_config_py = generate_prompts_py


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────

def generate_all(
    database:  str  = "neo4j",
    output:    Union[str, Path] = PROMPTS,
    n_samples: int  = 3,
    write:     bool = True,
    verbose:   bool = False,
) -> str:
    """
    Full pipeline: connect → collect schema → generate prompts.py → write.

    Parameters
    ----------
    database  : Neo4j database name.
    output    : Destination path for the generated prompts.py.
    n_samples : Sample values per property (for schema collection).
    write     : When True (default) write the result to *output*.
    verbose   : Print schema counts and a prompt preview.

    Returns
    -------
    str  The complete prompts.py content.
    """
    driver = _get_driver()
    try:
        logger.info("Collecting node schema (database=%r) …", database)
        node_rows = collect_node_schema(driver, database, n_samples=n_samples)
        logger.info("  %d (label × property) pairs.", len(node_rows))

        logger.info("Collecting relation schema …")
        rel_rows = collect_rel_schema(driver, database, n_samples=n_samples)
        logger.info("  %d relation rows.", len(rel_rows))

        logger.info("Discovering fulltext indexes …")
        ft_indexes = _discover_fulltext_indexes(driver, database)
        logger.info("  %d fulltext index(es) found.", len(ft_indexes))
    finally:
        driver.close()

    logger.info("Loading tool registry …")
    registry = _load_tool_registry()
    logger.info("  %d tools loaded.", len(registry))

    logger.info("Assembling prompts.py …")
    content = generate_prompts_py(
        node_rows  = node_rows,
        rel_rows   = rel_rows,
        ft_indexes = ft_indexes,
        registry   = registry,
        database   = database,
    )

    if verbose:
        preview_chars = 800
        logger.info("prompts.py preview (first %d chars):\n%s",
                    preview_chars, content[:preview_chars])

    if write:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info("prompts.py written → %r", str(output))

    return content


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate prompts.py (system prompts + schema constants) "
                    "from the live Neo4j schema. Does NOT touch config.py.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--database",
        default=os.getenv("NEO4J_DATABASE", "neo4j"),
        metavar="DB",
        help="Neo4j database name",
    )
    p.add_argument(
        "--output",
        default=str(PROMPTS),
        metavar="PATH",
        help=f"Output path for the generated prompts.py (default: {PROMPTS})",
    )
    p.add_argument(
        "--samples",
        type=int,
        default=3,
        metavar="N",
        help="Sample values to collect per property",
    )
    p.add_argument(
        "--print-only",
        action="store_true",
        help="Print generated prompts.py to stdout without writing to disk",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print schema details and a preview of the generated content",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    content = generate_all(
        database  = args.database,
        output    = args.output,
        n_samples = args.samples,
        write     = not args.print_only,
        verbose   = args.verbose,
    )
    if args.print_only:
        print(content)


if __name__ == "__main__":
    main()
