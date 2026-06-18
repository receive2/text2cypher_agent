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
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    PLAN_EXEC_TOOLS_PER_ENTITY,
    PLAN_EXEC_VALUES_PER_TOOL,
    PLAN_EXEC_HYBRID_FUZZY_K,
    PLAN_EXEC_HYBRID_VECTOR_K,
    PLAN_EXEC_ESCALATE_BUDGET,
    PLAN_EXEC_ROUTE_FETCH,
)
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

def _route_tools(descriptor: str, kind: str, node_only: bool = False,
                 n: int = PLAN_EXEC_TOOLS_PER_ENTITY, fetch: int = 10) -> List[str]:
    """Return up to *n* ranked ``func_name``s for *descriptor*, preferring tools
    whose kind matches *kind* (falls back to any kind if the preferred kind
    yields nothing). The returned list is rank-ordered so callers can use the
    first few for the initial retrieval and keep the rest for escalation. When
    *node_only*, routing uses the node-only tool index (relation tools are out
    of scope)."""
    # Lazy import: ner_agent_auto pulls in the live Neo4j graph at import time.
    from ner_agent_auto import _get_vectorstore
    from tools.tool_search import search_tools

    vs = _get_vectorstore(mode="react_node_only" if node_only else "react_node_rel")
    hits = search_tools(vs, user_query=descriptor, top_l=max(fetch, n))
    meta = _tool_meta()

    preferred, other = [], []
    for h in hits:
        fn = h.func_name
        if fn not in meta:
            continue
        (preferred if meta[fn]["kind"] == kind else other).append(fn)

    chosen = preferred or other
    return chosen[:n]


def _retrieve_values(mention: str, label: str, prop: str, hybrid: bool,
                     k: Optional[int] = None) -> List[str]:
    """Canonical-value lookup for one (label, property) target.

    Fuzzy modes: a single fuzzy ``search_tool`` of size *k* (default
    ``PLAN_EXEC_VALUES_PER_TOOL``). Hybrid mode: union fuzzy
    top-``PLAN_EXEC_HYBRID_FUZZY_K`` with vector top-``PLAN_EXEC_HYBRID_VECTOR_K``
    (fuzzy first, vector fills the tail, de-duplicated) so in-graph embedding
    recall can surface alias/abbrev hits that BM25 fuzzy misses. Escalation
    passes an explicit *k* for a deeper fuzzy fetch (hybrid is ignored there)."""
    from neo4j_lib.neo4j_search import search_tool  # lazy import

    if not hybrid or k is not None:
        return search_tool(phrase=mention, node_label=label, property_name=prop,
                           k=k or PLAN_EXEC_VALUES_PER_TOOL, mode="fuzzy")

    fuzzy = search_tool(phrase=mention, node_label=label, property_name=prop,
                        k=PLAN_EXEC_HYBRID_FUZZY_K, mode="fuzzy")
    try:
        vector = search_tool(phrase=mention, node_label=label, property_name=prop,
                             k=PLAN_EXEC_HYBRID_VECTOR_K, mode="vector")
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec: vector search failed for %s.%s: %s", label, prop, exc)
        vector = []
    merged = list(fuzzy)
    for v in vector:
        if v not in merged:
            merged.append(v)
    return merged


_JUDGE_PROMPT = """A question mentions an entity, and a value-linking step has \
retrieved candidate database values for it. Decide whether the mentioned entity \
is GROUNDED — i.e. whether one of the candidates is the canonical database value \
for that mention, allowing for typos, casing, abbreviations, partial names, or \
aliases.

Question: {question}
Entity mention: "{mention}"
Retrieved candidates:
{candidates}

Is the mention grounded in one of these candidates? Answer with exactly YES or NO."""


def _norm(s) -> str:
    if isinstance(s, (list, tuple)):
        s = " ".join(str(x) for x in s)
    return re.sub(r"\W+", "", str(s or "").lower())


def _escalate_fetch(mention: str, label: str, prop: str, hybrid: bool, k: int) -> List[str]:
    """Escalation retrieval for one (label, property): deepen the modality that
    is this mode's recall edge — **vector** for hybrid (the lever for aliases /
    abbreviations that share no characters with the canonical), **fuzzy**
    otherwise. Returns up to *k* candidates (dedup against existing is done by
    the caller)."""
    from neo4j_lib.neo4j_search import search_tool  # lazy import
    mode = "vector" if hybrid else "fuzzy"
    return search_tool(phrase=mention, node_label=label, property_name=prop, k=k, mode=mode)


def _judge_grounded(question: str, mention: str, values: List[str], llm_obj) -> bool:
    """True if *mention* is grounded in *values*. Fast path: a normalised
    substring match counts as grounded without an LLM call (covers casing /
    typo / partial). Otherwise an LLM judge decides (covers abbreviations /
    aliases, where the surface form shares no characters with the canonical)."""
    if not values:
        return False
    nm = _norm(mention)
    if nm and any(nm in _norm(v) or _norm(v) in nm for v in values):
        return True
    if llm_obj is None:
        return False
    cand_lines = "\n".join(f'- "{v}"' for v in values)
    prompt = _JUDGE_PROMPT.format(question=question, mention=mention, candidates=cand_lines)
    try:
        resp = llm_obj.invoke(prompt)
        raw = getattr(resp, "content", resp)
        if isinstance(raw, list):
            raw = " ".join(str(p) for p in raw)
        return str(raw).strip().upper().startswith("YES")
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec: judge failed for %r: %s", mention, exc)
        return False


_ACTION_PROMPT = """A question mentions an entity, and a value-linking step has \
retrieved candidate database values for it. Decide the next retrieval action.

Question: {question}
Entity mention: "{mention}"
Retrieved candidates (each tagged Label.property):
{candidates}

Choose ONE action:
- done       : the mention is already grounded — one candidate is its canonical value (allowing for typos, casing, abbreviations, partial names, or aliases), OR no further retrieval could plausibly help.
- value      : the candidates are the RIGHT KIND of thing for the mention but none matches — retrieve MORE values from the same field.
- tool       : the candidates are the WRONG KIND for the mention — search a DIFFERENT field/tool.
- tool_value : do both — broaden to other fields AND pull more values.

Answer with exactly one word: done, value, tool, or tool_value."""

_ACTIONS = ("tool_value", "done", "value", "tool")   # order matters: check 'tool_value' before 'tool'/'value'


def _judge_action(question: str, mention: str, values: List[str], llm_obj) -> str:
    """Return the next escalation action — one of ``done`` / ``value`` / ``tool``
    / ``tool_value``. Fast path: a normalised substring match is treated as
    ``done`` without an LLM call. Falls back to ``done`` on any parse/LLM failure
    (safe: stop rather than loop)."""
    if not values:
        return "tool"          # nothing retrieved yet → try a different tool
    nm = _norm(mention)
    if nm and any(nm in _norm(v) or _norm(v) in nm for v in values):
        return "done"
    if llm_obj is None:
        return "done"
    cand_lines = "\n".join(f'- "{v}"' for v in values)
    prompt = _ACTION_PROMPT.format(question=question, mention=mention, candidates=cand_lines)
    try:
        resp = llm_obj.invoke(prompt)
        raw = getattr(resp, "content", resp)
        if isinstance(raw, list):
            raw = " ".join(str(p) for p in raw)
        text = re.sub(r"[^a-z_]", "", str(raw).strip().lower())
        for a in _ACTIONS:
            if a in text:
                return a
        return "done"
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec: action judge failed for %r: %s", mention, exc)
        return "done"


def execute_entity(entity: Dict[str, str], node_only: bool = False,
                   hybrid: bool = False, escalate: bool = False,
                   question: str = "", llm_obj=None, verbose: bool = False) -> Dict[str, Any]:
    """EXECUTE stage for one mention. Returns the structured evidence:

        {"mention", "kind", "candidates": [{"label","property","values":[...]}],
         "patterns": ["(:A)-[:rel]->(:B)", ...]}

    When *escalate*, after the initial retrieval an LLM judge picks the next
    action each round — done / value (deepen the used tool[s]) / tool (bring in
    the next-ranked tool) / tool_value (both) — applying a diminishing budget
    (``PLAN_EXEC_ESCALATE_BUDGET``, e.g. 5→3→1, which also caps the rounds) and
    stopping on ``done`` or budget exhaustion. 'value' deepens fuzzy in the fuzzy
    mode and vector in hybrid (see :func:`_escalate_fetch`).
    """
    mention    = entity["mention"]
    kind       = entity["kind"]
    descriptor = entity["descriptor"]

    n_route = PLAN_EXEC_ROUTE_FETCH if escalate else PLAN_EXEC_TOOLS_PER_ENTITY
    func_names = _route_tools(descriptor, kind, node_only=node_only, n=n_route)
    init_tools = func_names[:PLAN_EXEC_TOOLS_PER_ENTITY]
    rest_tools = func_names[PLAN_EXEC_TOOLS_PER_ENTITY:]
    meta = _tool_meta()
    patterns: List[str] = []

    # Candidate values grouped by (label, property), insertion-ordered, deduped.
    by_target: "OrderedDict[Tuple[str, str], List[str]]" = OrderedDict()
    depth: Dict[Tuple[str, str], int] = {}

    def _add(label: str, prop: str, vals: List[str]) -> None:
        lst = by_target.setdefault((label, prop), [])
        for v in vals:
            # StringArray properties (e.g. aliases) can come back as a nested
            # list — flatten to individual string values so candidates are
            # always plain strings (for the judge and the injection block).
            items = v if isinstance(v, (list, tuple)) else [v]
            for item in items:
                sv = str(item).strip()
                if sv and sv not in lst:
                    lst.append(sv)

    # ── Initial retrieval over the first PLAN_EXEC_TOOLS_PER_ENTITY tools ──────
    for fn in init_tools:
        info = meta.get(fn, {})
        label, prop = info.get("label", ""), info.get("property", "")
        if info.get("kind") == "relation" and info.get("rel_pattern"):
            if info["rel_pattern"] not in patterns:
                patterns.append(info["rel_pattern"])
        if kind == "relation" or not (label and prop) or (label, prop) in depth:
            continue
        try:
            vals = _retrieve_values(mention, label, prop, hybrid=hybrid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan_exec: value lookup failed for %s.%s: %s", label, prop, exc)
            vals = []
        depth[(label, prop)] = PLAN_EXEC_HYBRID_FUZZY_K if hybrid else PLAN_EXEC_VALUES_PER_TOOL
        _add(label, prop, vals)

    def _flat() -> List[str]:
        return [v for vals in by_target.values() for v in vals]

    # ── Corrective escalation: an LLM judge picks the next action each round ───
    # Each round the judge returns done | value | tool | tool_value (one word,
    # no JSON). 'value' deepens the already-used tool(s) — fuzzy for the fuzzy
    # mode, vector for hybrid; 'tool' brings in the next-ranked tool; 'tool_value'
    # does both. The diminishing budget (5→3→1) also caps the loop at 3 rounds.
    n_escalations = 0
    if escalate and kind != "relation" and by_target:
        rest = list(rest_tools)
        for budget in PLAN_EXEC_ESCALATE_BUDGET:
            action = _judge_action(question, mention, _flat(), llm_obj)
            if action == "done":
                break
            if action in ("value", "tool_value"):
                for (label, prop) in list(by_target.keys()):
                    newk = depth[(label, prop)] + budget
                    try:
                        vals = _escalate_fetch(mention, label, prop, hybrid, k=newk)
                    except Exception:  # noqa: BLE001
                        vals = []
                    depth[(label, prop)] = newk
                    _add(label, prop, vals)       # dedup keeps only the new tail
            if action in ("tool", "tool_value") and rest:
                fn = rest.pop(0)
                info = meta.get(fn, {})
                label, prop = info.get("label", ""), info.get("property", "")
                if label and prop:
                    try:
                        vals = _escalate_fetch(mention, label, prop, hybrid, k=budget)
                    except Exception:  # noqa: BLE001
                        vals = []
                    depth[(label, prop)] = max(depth.get((label, prop), 0), budget)
                    _add(label, prop, vals)
            n_escalations += 1

    candidates = [{"label": l, "property": p, "values": v}
                  for (l, p), v in by_target.items() if v]

    if verbose:
        print(f"  · {kind:8s} {mention!r}  →  tools={func_names}  "
              f"candidates={[(c['label']+'.'+c['property'], len(c['values'])) for c in candidates]}"
              f"{f'  escalations={n_escalations}' if escalate else ''}"
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
    node_only: bool = False,
    hybrid: bool = False,
    escalate: bool = False,
    verbose: bool = False,
    return_structured: bool = False,
):
    """Run PLAN → EXECUTE → format and return the ``{relevant_entities}`` block.

    *node_only* restricts tool routing to node-property tools (the
    ``plan_exec_node_only`` mode); relation mentions then route to node tools
    or contribute nothing, so no relationship patterns are emitted.

    *hybrid* unions fuzzy + vector candidates per tool (the
    ``plan_exec_node_rel_hybrid`` mode).

    *escalate* enables the corrective LLM-judge retrieval loop (see
    :func:`execute_entity`); *llm_obj* is reused as the judge.

    With ``return_structured=True`` returns ``(injection_str, evidence_list)``.
    """
    if verbose:
        print(f"\n── plan_exec: PLAN ── (node_only={node_only}, hybrid={hybrid}, "
              f"escalate={escalate})\n  query={query!r}")
    plan = plan_entities(query, llm_obj)
    if verbose:
        print(f"  extracted {len(plan)} mentions: "
              f"{[(p['mention'], p['kind']) for p in plan]}")
        print("── plan_exec: EXECUTE ──")

    evidence = [execute_entity(e, node_only=node_only, hybrid=hybrid,
                               escalate=escalate, question=query, llm_obj=llm_obj,
                               verbose=verbose)
                for e in plan]
    injection = build_injection(evidence)

    if verbose:
        print(f"── plan_exec: injection block ──\n{injection}\n")
    return (injection, evidence) if return_structured else injection
