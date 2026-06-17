#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_exec.py
============
Plan-and-execute grounding — a deterministic, non-agentic alternative to the
ReAct NER agent (``ner_agent_auto.get_ner_auto``).

Where the ``full`` mode lets a LangGraph ReAct agent freely pick tools from a
top-k tool shortlist and synthesise a single ``{Label.prop: value}`` dict
(which empirically drops groundings in the final-JSON synthesis step), this
module makes every stage explicit and hands the *candidates* to the Cypher LLM:

  1. PLAN     :func:`plan_entities` — one LLM call decomposes the question into
                a list of entity mentions, each tagged ``node`` | ``relation``
                with a short type ``descriptor`` (used for tool routing).
  2. EXECUTE  :func:`execute_entity` — for each mention, route to the matching
                tool(s) via the tool-VectorDB (searching by ``descriptor``,
                filtered by kind), then:
                  • node mention     → ``search_tool(mention)`` → top-K values
                  • relation mention → emit the ``(:A)-[:rel]->(:B)`` pattern
                No per-tool ``get_entity`` re-extraction: the mention is the
                search phrase directly (one fewer lossy LLM layer than ``full``).
  3. GENERATE :func:`build_injection` formats the per-mention candidate lists
                into the ``{relevant_entities}`` block; the Cypher LLM does the
                value-linking while writing Cypher.

Retrieval stays fuzzy (``search_tool(..., mode="fuzzy")``), so this needs no
per-graph value-embedding index; the only vector index is the small
one-doc-per-tool routing index that ``full`` already builds.

The public entry point is :func:`get_plan_exec_evidence`, which returns the
ready-to-inject ``{relevant_entities}`` string (and, optionally, the structured
evidence for tracing).
"""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import PLAN_EXEC_TOOLS_PER_ENTITY, PLAN_EXEC_VALUES_PER_TOOL
from paths import REPO_ROOT

logger = logging.getLogger("t2c.plan_exec")

_NODE_TOOLS_SRC = REPO_ROOT / "generated" / "generated_node_tools.py"
_REL_TOOLS_SRC  = REPO_ROOT / "generated" / "generated_rel_tools.py"


# ──────────────────────────────────────────────────────────────────────────────
# Tool metadata map: func_name -> (label, property, kind, rel_pattern)
#
# The tool-VectorDB stores only func_name/description, so (label, property) for
# a routed tool is recovered by parsing the generated source's fixed
# ``search_tool(node_label=..., property_name=...)`` call. Built once, cached.
# ──────────────────────────────────────────────────────────────────────────────

_TOOL_META: Optional[Dict[str, Dict[str, str]]] = None

# (:A)-[:relType]->(:B)  pattern inside a relation tool's docstring.
_REL_PATTERN_RE = re.compile(r"\(:\w+\)\s*-\s*\[:\s*\w+\s*\]\s*->\s*\(:\w+\)")


def _search_tool_args(fn: ast.FunctionDef) -> Tuple[str, str]:
    """Pull ``node_label`` / ``property_name`` from the ``search_tool(...)`` call
    inside *fn*'s body. Returns ``("", "")`` if not found."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if fname != "search_tool":
                continue
            label = prop = ""
            for kw in node.keywords:
                if kw.arg == "node_label" and isinstance(kw.value, ast.Constant):
                    label = str(kw.value.value)
                elif kw.arg == "property_name" and isinstance(kw.value, ast.Constant):
                    prop = str(kw.value.value)
            return label, prop
    return "", ""


def _parse_module(path: Path, kind: str, out: Dict[str, Dict[str, str]]) -> None:
    if not path.is_file():
        logger.warning("plan_exec: generated tool file missing: %s", path)
        return
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        label, prop = _search_tool_args(node)
        doc = ast.get_docstring(node) or ""
        m = _REL_PATTERN_RE.search(doc)
        out[node.name] = {
            "label":       label,
            "property":    prop,
            "kind":        kind,
            "rel_pattern": m.group(0).replace(" ", "") if m else "",
        }


def _tool_meta() -> Dict[str, Dict[str, str]]:
    """Lazily build + cache the ``func_name -> {label, property, kind,
    rel_pattern}`` map from the generated tool sources."""
    global _TOOL_META
    if _TOOL_META is None:
        meta: Dict[str, Dict[str, str]] = {}
        _parse_module(_NODE_TOOLS_SRC, "node", meta)
        _parse_module(_REL_TOOLS_SRC, "relation", meta)
        _TOOL_META = meta
        logger.info("plan_exec: tool meta map built (%d tools)", len(meta))
    return _TOOL_META


# ──────────────────────────────────────────────────────────────────────────────
# PLAN — decompose the question into entity mentions
# ──────────────────────────────────────────────────────────────────────────────

_PLAN_PROMPT = """You are decomposing a natural-language question into the \
concrete entities it mentions, so each can be grounded against a graph database.

Return a JSON array. Each element is an object:
  {{"mention": <verbatim span from the question>,
    "kind": "node" | "relation",
    "descriptor": <2-5 word type description, e.g. "aircraft model name",
                   "airport name", "manufactured-by relation">}}

Rules:
- "node": a thing referred to by a name/value (a model, person, place, title,
  identifier, ...). Use the question's surface form verbatim as `mention`
  (keep typos, casing, abbreviations — they will be fuzzy-matched).
- "relation": a verb/preposition phrase describing how two things connect
  (e.g. "manufactured by", "departed from", "directed"). `mention` is that phrase.
- Keep a complete proper name as ONE node mention — never split a single named
  entity into several. e.g. "FlyMontserrat Flight 107" is ONE node (a flight /
  accident named that), NOT "FlyMontserrat" + "107"; "South African Airways
  Flight 201" is ONE node. A trailing flight number is part of the name, not a
  separate entity. Prefer the longest contiguous proper-name span.
- Extract EVERY named entity. Do not extract pure numbers, dates, or counts
  (a flight number that is PART of a proper name stays inside that name).
- `descriptor` should describe the TYPE so it matches a retrieval tool; include
  the likely entity category word (model/airport/manufacturer/flight/accident/
  person/...).
- Output ONLY the JSON array, nothing else.

Question: {question}

JSON:"""


def _parse_plan(raw: str) -> List[Dict[str, str]]:
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.MULTILINE).strip()
    arr: Any = None
    try:
        arr = json.loads(s)
    except Exception:  # noqa: BLE001
        m = re.search(r"\[.*\]", s, re.DOTALL)
        if m:
            try:
                arr = json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                arr = None
    if not isinstance(arr, list):
        return []
    out: List[Dict[str, str]] = []
    for el in arr:
        if not isinstance(el, dict):
            continue
        mention = str(el.get("mention", "")).strip()
        if not mention:
            continue
        kind = str(el.get("kind", "node")).strip().lower()
        if kind not in ("node", "relation"):
            kind = "node"
        out.append({
            "mention":    mention,
            "kind":       kind,
            "descriptor": str(el.get("descriptor", "")).strip() or mention,
        })
    return out


def plan_entities(query: str, llm_obj) -> List[Dict[str, str]]:
    """PLAN stage: one LLM call → list of ``{mention, kind, descriptor}``."""
    prompt = _PLAN_PROMPT.format(question=query)
    try:
        resp = llm_obj.invoke(prompt)
        raw = getattr(resp, "content", resp)
        if isinstance(raw, list):
            raw = " ".join(str(p) for p in raw)
        return _parse_plan(str(raw))
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec: PLAN stage failed: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# EXECUTE — route each mention to tool(s), retrieve candidate values
# ──────────────────────────────────────────────────────────────────────────────

def _route_tools(descriptor: str, kind: str, fetch: int = 8) -> List[str]:
    """Return up to ``PLAN_EXEC_TOOLS_PER_ENTITY`` ``func_name``s for *descriptor*,
    preferring tools whose kind matches *kind*. Falls back to any kind if the
    preferred kind yields nothing."""
    # Lazy import: ner_agent_auto pulls in the live Neo4j graph at import time.
    from ner_agent_auto import _get_vectorstore
    from tools.tool_search import search_tools

    vs = _get_vectorstore(mode="full")
    hits = search_tools(vs, user_query=descriptor, top_l=fetch)
    meta = _tool_meta()

    preferred, other = [], []
    for h in hits:
        fn = h.func_name
        if fn not in meta:
            continue
        (preferred if meta[fn]["kind"] == kind else other).append(fn)

    chosen = preferred or other
    return chosen[:PLAN_EXEC_TOOLS_PER_ENTITY]


def execute_entity(entity: Dict[str, str], verbose: bool = False) -> Dict[str, Any]:
    """EXECUTE stage for one mention. Returns the structured evidence:

        {"mention", "kind", "candidates": [{"label","property","values":[...]}],
         "patterns": ["(:A)-[:rel]->(:B)", ...]}
    """
    from neo4j_lib.neo4j_search import search_tool  # lazy import

    mention    = entity["mention"]
    kind       = entity["kind"]
    descriptor = entity["descriptor"]

    func_names = _route_tools(descriptor, kind)
    candidates: List[Dict[str, Any]] = []
    patterns: List[str] = []
    meta = _tool_meta()
    seen_lp: set = set()

    for fn in func_names:
        info = meta.get(fn, {})
        label, prop = info.get("label", ""), info.get("property", "")
        if info.get("kind") == "relation" and info.get("rel_pattern"):
            if info["rel_pattern"] not in patterns:
                patterns.append(info["rel_pattern"])
        # Value lookup: skip for relation mentions (the phrase is not a value),
        # and de-dup repeated (label, property) targets.
        if kind == "relation" or not (label and prop):
            continue
        if (label, prop) in seen_lp:
            continue
        seen_lp.add((label, prop))
        try:
            values = search_tool(
                phrase=mention, node_label=label, property_name=prop,
                k=PLAN_EXEC_VALUES_PER_TOOL, mode="fuzzy",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan_exec: search_tool failed for %s.%s: %s", label, prop, exc)
            values = []
        if values:
            candidates.append({"label": label, "property": prop, "values": values})

    if verbose:
        print(f"  · {kind:8s} {mention!r}  →  tools={func_names}  "
              f"candidates={[(c['label']+'.'+c['property'], len(c['values'])) for c in candidates]}"
              f"{'  patterns='+str(patterns) if patterns else ''}")
    return {"mention": mention, "kind": kind, "candidates": candidates, "patterns": patterns}


# ──────────────────────────────────────────────────────────────────────────────
# GENERATE — format the candidate block for the Cypher prompt
# ──────────────────────────────────────────────────────────────────────────────

def build_injection(evidence: List[Dict[str, Any]]) -> str:
    """Format the per-mention evidence into the ``{relevant_entities}`` block.

    Option B: mention-grouped, candidates kept as a best-first list so the
    Cypher LLM does the final value-linking. A self-contained instruction
    overrides the template's default "use ALL pairs" framing (which assumes a
    single resolved value per key)."""
    lines: List[str] = []
    for ev in evidence:
        m = ev["mention"]
        for c in ev["candidates"]:
            vals = " | ".join(f'"{v}"' for v in c["values"])
            lines.append(f'- "{m}"  →  {c["label"]}.{c["property"]}: {vals}')
        for p in ev["patterns"]:
            lines.append(f'- "{m}"  →  relationship pattern: {p}')

    if not lines:
        return "{}"

    header = (
        "Retrieved candidate values for each entity mention in the question "
        "(best-first; copied verbatim from the database). For each mention, "
        "choose the SINGLE best-matching canonical value for the WHERE clause "
        "(or use the given relationship pattern for a relation) — these lists "
        "are retrieval candidates to pick from, NOT filters to all apply:"
    )
    return header + "\n" + "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────

def get_plan_exec_evidence(
    query: str,
    llm_obj,
    verbose: bool = False,
    return_structured: bool = False,
):
    """Run PLAN → EXECUTE → format and return the ``{relevant_entities}`` block.

    With ``return_structured=True`` returns ``(injection_str, evidence_list)``.
    """
    if verbose:
        print(f"\n── plan_exec: PLAN ──\n  query={query!r}")
    plan = plan_entities(query, llm_obj)
    if verbose:
        print(f"  extracted {len(plan)} mentions: "
              f"{[(p['mention'], p['kind']) for p in plan]}")
        print("── plan_exec: EXECUTE ──")

    evidence = [execute_entity(e, verbose=verbose) for e in plan]
    injection = build_injection(evidence)

    if verbose:
        print(f"── plan_exec: injection block ──\n{injection}\n")
    return (injection, evidence) if return_structured else injection
