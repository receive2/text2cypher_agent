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
    PLAN_EXEC_MAX_ITER,
    PLAN_EXEC_SKIP_GROUNDED,
    PLAN_EXEC_PARALLEL_MENTIONS,
    MAX_THREAD,
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
        # First sentence of the docstring, trimmed — a short hint for the field
        # menu the escalation judge chooses from.
        desc = re.split(r"(?<=[.!?])\s", doc.strip())[0] if doc.strip() else ""
        out[node.name] = {
            "label":       label,
            "property":    prop,
            "kind":        kind,
            "rel_pattern": m.group(0).replace(" ", "") if m else "",
            "desc":        desc[:140],
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
    """Deeper retrieval for one (label, property) during escalation. Fuzzy mode
    deepens fuzzy; hybrid deepens **both** fuzzy and vector (vector is the lever
    for aliases that share no characters with the canonical; fuzzy still catches
    deeper abbrev/partial hits). Returns up to *k* per modality; the caller
    de-dups against what it already has."""
    from neo4j_lib.neo4j_search import search_tool  # lazy import
    fuzzy = search_tool(phrase=mention, node_label=label, property_name=prop, k=k, mode="fuzzy")
    if not hybrid:
        return fuzzy
    try:
        vector = search_tool(phrase=mention, node_label=label, property_name=prop, k=k, mode="vector")
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec: vector deepen failed for %s.%s: %s", label, prop, exc)
        vector = []
    out = list(fuzzy)
    for v in vector:
        if v not in out:
            out.append(v)
    return out


def _cheap_grounded(mention: str, values: List[str]) -> bool:
    """The FREE (no-LLM) part of grounding: a candidate exact/substring-matches
    the mention (covers casing / typo / partial). Used to skip escalation for
    mentions that are already cleanly grounded (latency, ~EA-neutral)."""
    nm = _norm(mention)
    return bool(nm) and any(nm in _norm(v) or _norm(v) in nm for v in values)


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


_NAME_LIKE = {"name", "title", "aliases", "alias", "label"}


def _name_like(prop: str) -> bool:
    p = (prop or "").lower()
    return p in _NAME_LIKE or p.endswith("name") or p.endswith("title")


def _field_menu(used: set) -> List[Tuple[str, str, str]]:
    """Available node name-like fields the judge may add, as (label, property,
    desc), excluding the ones already searched for this mention. Entities are
    grounded by name/alias fields, so id / description / numeric fields are
    omitted to keep the menu focused."""
    meta = _tool_meta()
    seen, menu = set(), []
    for info in meta.values():
        if info.get("kind") != "node":
            continue
        l, p = info.get("label", ""), info.get("property", "")
        if not (l and p) or (l, p) in used or (l, p) in seen or not _name_like(p):
            continue
        seen.add((l, p))
        menu.append((l, p, info.get("desc", "")))
    return menu


_STEP_PROMPT = """A question mentions an entity and a value-linking step has \
retrieved candidate database values for it. Decide the single best next action.

Question: {question}
Entity mention: "{mention}"
Retrieved candidates so far (each tagged Label.property):
{candidates}

Other database fields you could search instead (Label.property — description):
{menu}

Choose ONE:
- done  : one candidate already IS the mention's canonical value (allowing for typos, casing, abbreviations, partial names, or aliases), OR no field could plausibly hold it.
- value : the candidates are the RIGHT KIND of thing but none matches — pull MORE values from the SAME field(s).
- <Label.property> : the mention belongs in a DIFFERENT field — copy ONE field name verbatim from the menu above to search it next.

Answer with exactly one token: done, value, or a Label.property from the menu."""


def _judge_step(question: str, mention: str, values: List[str],
                menu: List[Tuple[str, str, str]], llm_obj):
    """Return the next escalation step: ``"done"`` | ``"value"`` | ``(label,
    property)`` (a field the LLM chose to add). Fast path: a normalised
    substring match is ``done`` without an LLM call. Falls back to ``done`` on
    any parse/LLM failure (stop rather than loop)."""
    if not values:
        return (menu[0][0], menu[0][1]) if menu else "done"
    nm = _norm(mention)
    if nm and any(nm in _norm(v) or _norm(v) in nm for v in values):
        return "done"
    if llm_obj is None:
        return "done"
    menu_lines = "\n".join(f"- {l}.{p}  —  {d}" for l, p, d in menu) or "(none)"
    cand_lines = "\n".join(f'- "{v}"' for v in values)
    prompt = _STEP_PROMPT.format(question=question, mention=mention,
                                 candidates=cand_lines, menu=menu_lines)
    try:
        resp = llm_obj.invoke(prompt)
        raw = getattr(resp, "content", resp)
        if isinstance(raw, list):
            raw = " ".join(str(p) for p in raw)
        text = str(raw).strip()
        low = text.lower()
        # A chosen field is the most specific match — check the menu first.
        for l, p, _d in menu:
            if f"{l}.{p}".lower() in low or _norm(f"{l}{p}") in _norm(text):
                return (l, p)
        if "value" in low:
            return "value"
        return "done"
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec: step judge failed for %r: %s", mention, exc)
        return "done"


def execute_entity(entity: Dict[str, str], node_only: bool = False,
                   hybrid: bool = False, escalate: bool = False,
                   question: str = "", llm_obj=None, verbose: bool = False) -> Dict[str, Any]:
    """EXECUTE stage for one mention. Returns the structured evidence:

        {"mention", "kind", "candidates": [{"label","property","values":[...]}],
         "patterns": ["(:A)-[:rel]->(:B)", ...]}

    When *escalate*, after the initial retrieval an LLM judge picks the next step
    each round — done / value (deepen the used field[s]) / a specific
    Label.property field it chooses from a menu to ADD — for up to
    ``PLAN_EXEC_MAX_ITER`` rounds, stopping on ``done``. 'value' deepens fuzzy in
    the fuzzy mode and both fuzzy+vector in hybrid (see :func:`_escalate_fetch`);
    a newly chosen field gets a full initial-style fetch.
    """
    mention    = entity["mention"]
    kind       = entity["kind"]
    descriptor = entity["descriptor"]

    init_tools = _route_tools(descriptor, kind, node_only=node_only,
                              n=PLAN_EXEC_TOOLS_PER_ENTITY)
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

    # ── Corrective escalation: an LLM judge picks the next step each round ─────
    # Each round the judge returns done | value | a specific Label.property field
    # to ADD (chosen from a menu of available name-like node fields). 'value'
    # deepens the already-used field(s) — fuzzy for the fuzzy mode, fuzzy+vector
    # for hybrid; a chosen field gets a full initial-style fetch. Capped at
    # PLAN_EXEC_MAX_ITER rounds.
    n_escalations = 0
    # #4: skip escalation entirely when the mention is already cleanly grounded
    # (a candidate exact/substring-matches it) — escalation wouldn't improve it.
    _already = PLAN_EXEC_SKIP_GROUNDED and _cheap_grounded(mention, _flat())
    if escalate and kind != "relation" and by_target and not _already:
        for i in range(PLAN_EXEC_MAX_ITER):
            budget = PLAN_EXEC_ESCALATE_BUDGET[min(i, len(PLAN_EXEC_ESCALATE_BUDGET) - 1)]
            menu = _field_menu(set(by_target.keys()))
            step = _judge_step(question, mention, _flat(), menu, llm_obj)
            if step == "done":
                break
            if step == "value":                       # deepen the used field(s)
                for (label, prop) in list(by_target.keys()):
                    newk = depth[(label, prop)] + budget
                    try:
                        vals = _escalate_fetch(mention, label, prop, hybrid, k=newk)
                    except Exception:  # noqa: BLE001
                        vals = []
                    depth[(label, prop)] = newk
                    _add(label, prop, vals)            # dedup keeps only the new tail
            else:                                      # (label, prop): add the chosen field
                label, prop = step
                try:
                    vals = _retrieve_values(mention, label, prop, hybrid=hybrid)
                except Exception:  # noqa: BLE001
                    vals = []
                depth[(label, prop)] = PLAN_EXEC_HYBRID_FUZZY_K if hybrid else PLAN_EXEC_VALUES_PER_TOOL
                _add(label, prop, vals)
            n_escalations += 1

    candidates = [{"label": l, "property": p, "values": v}
                  for (l, p), v in by_target.items() if v]

    if verbose:
        print(f"  · {kind:8s} {mention!r}  →  init_tools={init_tools}  "
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
# Method-specific Cypher-generation guidance (plan_exec ONLY)
# ──────────────────────────────────────────────────────────────────────────────
# Appended to the plan_exec injection block, so it reaches ONLY the Cypher prompt
# for VAL_LINK_MODE=val_link/plan_exec. The baselines (no_val_link, fcav, react)
# and the graphrag baseline keep the faithful, unmodified TEXT2CYPHER_SP — they
# never go through get_plan_exec_evidence. This is a STATIC, schema-independent
# improvement, so it lives in code (works on every graph, setup stays one-click,
# no per-graph prompt regeneration). Single braces below; ask_auto brace-escapes
# the whole injection before PromptTemplate.format, so they render as `{` / `}`.
_UNION_GUIDANCE = """

Cypher structure for "either A or B" (disjunction) — get this right:
- COUNT ("how many ... A or B"): put each value's MATCH ... RETURN n INSIDE one
  CALL { ... UNION ... } subquery, then a SINGLE outer WITH DISTINCT n / RETURN
  count(n). NEVER write one count(n) per branch joined by UNION (that returns one
  row per branch and double-counts nodes matching both values). Example:
    CALL {
      MATCH (n:Movie)-[:hasGenre]->(:Genre {name: "Drama"}) RETURN n
      UNION
      MATCH (n:Movie)-[:hasGenre]->(:Genre {name: "Comedy"}) RETURN n
    }
    WITH DISTINCT n
    RETURN count(n)
- LISTING ("list / which / who ... A or B"): parallel MATCH ... RETURN blocks
  joined by top-level UNION, one per value (each block ends RETURN n.<prop>)."""


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

    # #1: mentions are independent — run their EXECUTE/escalation concurrently
    # (same calls, same results, order preserved). Prewarm shared caches first so
    # the threads only read them.
    def _exec(e):
        return execute_entity(e, node_only=node_only, hybrid=hybrid,
                              escalate=escalate, question=query, llm_obj=llm_obj,
                              verbose=verbose)

    workers = min(max(1, len(plan)), MAX_THREAD)
    if not PLAN_EXEC_PARALLEL_MENTIONS or workers <= 1:
        evidence = [_exec(e) for e in plan]
    else:
        _tool_meta()                                   # prewarm tool-meta cache
        try:                                            # prewarm tool vectorstore
            from ner_agent_auto import _get_vectorstore
            _get_vectorstore(mode="react_node_only" if node_only else "react_node_rel")
        except Exception:  # noqa: BLE001
            pass
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=workers) as _ex:
            evidence = list(_ex.map(_exec, plan))      # map preserves input order
    # Append plan_exec-only Cypher-generation guidance (union/disjunction). This
    # stays inside the plan_exec injection so baselines never see it.
    injection = build_injection(evidence) + _UNION_GUIDANCE

    if verbose:
        print(f"── plan_exec: injection block ──\n{injection}\n")
    return (injection, evidence) if return_structured else injection


# ──────────────────────────────────────────────────────────────────────────────
# VALUE-SNAP — post-generation grounding guard for the SELECTION error
# ──────────────────────────────────────────────────────────────────────────────
# The Cypher LLM sometimes copies the question's perturbed surface form into a
# WHERE clause even though the canonical value was retrieved into the candidate
# list. This guard fixes exactly that, safely:
#   1. EXISTENCE GATE — a value that EXISTS in the DB is never touched (so
#      correct/normal queries can't be harmed; they use real values).
#   2. For a value that does NOT exist (predicate provably matches 0 rows), one
#      LLM call picks the matching candidate (from plan_exec's already-retrieved
#      candidates) or NONE — a closed-list discriminative task, far more reliable
#      than Cypher generation. The pick is validated to be in the list.
# ──────────────────────────────────────────────────────────────────────────────

_SNAP_SELECT_PROMPT = """\
A Cypher query used entity values that do NOT exist in the graph database — most
likely because the question's wording was perturbed (typo, abbreviation, alias,
partial name, or casing). For each item, choose the candidate value that refers
to the SAME entity the question means, or "NONE" if none of the candidates is
that entity.

Question: {question}

Items (used value · field · real database candidates to choose from):
{items}

Reply with ONLY a JSON object mapping each used value to your chosen candidate
(verbatim from its candidate list) or "NONE". Example:
{{"Tmo Hooper": "Tom Hooper", "some unknown thing": "NONE"}}"""

# alias.prop = 'val'  — EXACT equality only (not =~, <=, >=, <>).
_SNAP_EQ_RE = re.compile(r"(\w+)\.`?(\w+)`?\s*=\s*(?![~<>=])(['\"])(.*?)\3")
# (:Label {prop: 'val', ...})  inline-map literals.
_SNAP_MAP_RE = re.compile(r"\(\s*\w*\s*:\s*`?(\w+)`?\s*\{([^}]*)\}")
_SNAP_MAP_KV_RE = re.compile(r"`?(\w+)`?\s*:\s*(['\"])(.*?)\2")
_SNAP_ALIAS_RE = re.compile(r"\(\s*(\w+)\s*:\s*`?(\w+)`?")


def _snap_value_targets(cypher: str) -> List[Tuple[str, str, str]]:
    """Extract (label, prop, value) for ``=``/inline-map STRING literals. Skips
    ``=~`` / ``CONTAINS`` / ``STARTS WITH`` (intentional partial matches)."""
    c = cypher or ""
    alias2lab = dict(_SNAP_ALIAS_RE.findall(c))
    out: List[Tuple[str, str, str]] = []
    for al, prop, _q, val in _SNAP_EQ_RE.findall(c):
        out.append((alias2lab.get(al, ""), prop, val))
    for lab, body in _SNAP_MAP_RE.findall(c):
        for prop, _q, val in _SNAP_MAP_KV_RE.findall(body):
            out.append((lab, prop, val))
    return out


def _value_exists(label: str, prop: str, value: str) -> bool:
    """True iff some ``(:label)`` node has ``prop == value`` (exact). On any
    failure returns True (unknown → don't touch — fail safe)."""
    from neo4j_lib.neo4j_search import get_neo4j_graph  # lazy import
    try:
        rows = get_neo4j_graph().query(
            f"MATCH (n:`{label}`) WHERE n.`{prop}` = $v RETURN count(n) > 0 AS ok LIMIT 1",
            params={"v": value},
        )
        return bool(rows and rows[0].get("ok"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec snap: existence check failed %s.%s: %s", label, prop, exc)
        return True


def snap_values_to_candidates(cypher: str, evidence: List[Dict[str, Any]],
                              llm_obj, question: str, verbose: bool = False
                              ) -> Tuple[str, List[Tuple[str, str, str]]]:
    """Existence-gated candidate snapping (the SELECTION-error fix).

    For each ``=``/inline-map entity value in *cypher* that does NOT exist in the
    DB but has retrieved candidates for its ``(label, property)``, one LLM call
    picks the matching candidate (or NONE); a validated pick is substituted.
    Returns ``(new_cypher, snaps)`` where ``snaps`` is ``[(old, new, "L.p"), …]``
    (empty list ⇒ nothing changed).
    """
    if not cypher:
        return cypher, []

    # Candidate pool per (label, property), from plan_exec's retrieval (optional —
    # snap also does a fresh retrieval keyed on the generator's value+field).
    pool: Dict[Tuple[str, str], List[str]] = {}
    for ev in (evidence or []):
        for c in ev.get("candidates", []):
            key = (c.get("label", ""), c.get("property", ""))
            lst = pool.setdefault(key, [])
            for v in c.get("values", []):
                if v not in lst:
                    lst.append(v)

    from neo4j_lib.neo4j_search import search_tool  # lazy import

    # Broken values: don't exist in the DB. Candidates are keyed on the value AND
    # field the GENERATOR actually used (robust to plan_exec routing the mention
    # to a different field), via a fresh fuzzy retrieval, unioned with plan_exec's
    # already-retrieved candidates for that field.
    broken: List[Tuple[str, str, str, List[str]]] = []
    seen = set()
    for label, prop, val in _snap_value_targets(cypher):
        if not (label and prop) or (label, prop, val) in seen:
            continue
        seen.add((label, prop, val))
        if _value_exists(label, prop, val):
            continue                              # value exists → never touch (safety)
        try:
            cands = list(search_tool(val, node_label=label, property_name=prop,
                                     k=10, mode="fuzzy"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan_exec snap: retrieval failed %s.%s: %s", label, prop, exc)
            cands = []
        for v in pool.get((label, prop), []):
            if v not in cands:
                cands.append(v)
        if not cands:
            continue                              # nothing similar exists → leave it
        broken.append((val, label, prop, cands))

    if not broken:
        return cypher, []

    items = "\n".join(
        f'- "{v}"  ·  {l}.{p}  ·  {cands}' for (v, l, p, cands) in broken
    )
    try:
        resp = llm_obj.invoke(_SNAP_SELECT_PROMPT.format(question=question, items=items))
        raw = getattr(resp, "content", resp)
        if isinstance(raw, list):
            raw = "".join(str(x) for x in raw)
        m = re.search(r"\{.*\}", str(raw), re.DOTALL)
        picks = json.loads(m.group(0)) if m else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_exec snap: selector call failed: %s", exc)
        return cypher, []

    new_cypher = cypher
    snaps: List[Tuple[str, str, str]] = []
    for (v, l, p, cands) in broken:
        chosen = picks.get(v)
        # Validate: must be a real candidate (guards hallucination), not NONE/same.
        if not chosen or chosen == "NONE" or chosen == v or chosen not in cands:
            continue
        for qch in ('"', "'"):
            new_cypher = new_cypher.replace(f"{qch}{v}{qch}", f"{qch}{chosen}{qch}")
        snaps.append((v, chosen, f"{l}.{p}"))

    if verbose and snaps:
        print("── plan_exec value-snap ──")
        for o, n, fld in snaps:
            print(f"  {fld}: {o!r} → {n!r}")
    return new_cypher, snaps
