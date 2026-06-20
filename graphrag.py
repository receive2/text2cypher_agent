#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
graphrag.py
===========
Multi-Agent GraphRAG baseline (``VAL_LINK_MODE=graphrag``).

A self-correcting text-to-Cypher loop, after
*Multi-Agent GraphRAG: A Text-to-Cypher Framework for Labeled Property Graphs*.
Unlike the other modes in this repo, GraphRAG does **no value-linking before
generation** — it generates Cypher first, then repairs it from execution +
validation feedback:

    generate Cypher → execute → Evaluator classifies
                       │
                       ├─ Accept                       → format & return answer
                       │
                       ├─ Incorrect / Illogical /      → hand the semantic/logical
                       │  Incomplete                     feedback to the Generator
                       │
                       └─ Error or Empty               → STRUCTURAL repair:
                            • extract node labels, property–value pairs and
                              relationship patterns from the generated Cypher
                            • verify each against the database
                            • for invalid values, retrieve normalized-Levenshtein
                              candidate replacements and let the LLM pick one
                            • aggregate execution + semantic + validation feedback
                            • Generator rewrites the Cypher

    …iterate up to ``GRAPHRAG_MAX_ITER`` rounds, then return the best attempt.

This is a drop-in alternative to the NER step: everything downstream (execution,
scoring, record format) is identical to the other modes, so :func:`run_graphrag`
returns the same dict shape as ``ner_agent_auto.ask_auto`` (``entities`` /
``cypher`` / ``result`` / ``context`` / ``mode``), plus a ``graphrag_trace`` list
for per-round analysis.

Generator reuses ``CYPHER_LLM_CONFIG``; evaluator + replacement-selector reuse
``NER_LLM_CONFIG`` (overridable via the keyword args of :func:`run_graphrag`).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.prompts import PromptTemplate

import config as _config
from agent.prompts import TEXT2CYPHER_SP
from agent.agent_helper import (
    neo4j_graph,
    cypher_llm as _cypher_llm,
    qa_llm as _qa_llm,
    ner_llm as _ner_llm,
)

logger = logging.getLogger("t2c.graphrag")


# ──────────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────────
def _llm_text(resp: Any) -> str:
    """Flatten a LangChain chat response to plain text (content may be a list)."""
    content = getattr(resp, "content", resp)
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _parse_json_obj(text: str) -> Optional[dict]:
    """Best-effort extraction of the first JSON object from an LLM reply."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def _levenshtein(a: str, b: str) -> int:
    """Plain Levenshtein edit distance (insert/delete/substitute = 1)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def normalized_levenshtein(a: str, b: str) -> float:
    """Case-insensitive normalized Levenshtein **similarity** in [0, 1].

    1.0 = identical, 0.0 = no overlap. ``1 - lev(a,b)/max(len(a),len(b))``.
    No third-party dep (rapidfuzz/python-Levenshtein are absent in this env).
    """
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / longest


def _clean_cypher(text: str) -> str:
    """Strip code fences / leading 'cypher:' chatter from a generated query."""
    t = text.strip()
    # Prefer a fenced block if present.
    fence = re.search(r"```(?:cypher|sql)?\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    # Drop a leading 'cypher' / 'query:' label line some models emit.
    t = re.sub(r"^\s*(cypher|query)\s*:?\s*", "", t, flags=re.IGNORECASE)
    return t.strip()


# ──────────────────────────────────────────────────────────────────────────────
# Schema introspection (cached) — valid labels / relationship types
# ──────────────────────────────────────────────────────────────────────────────
_LABELS_CACHE: Optional[set] = None
_RELTYPES_CACHE: Optional[set] = None


def _db_labels() -> set:
    global _LABELS_CACHE
    if _LABELS_CACHE is None:
        try:
            rows = neo4j_graph.query("CALL db.labels() YIELD label RETURN label")
            _LABELS_CACHE = {r["label"] for r in rows}
        except Exception as exc:  # noqa: BLE001
            logger.warning("graphrag: db.labels() failed: %s", exc)
            _LABELS_CACHE = set()
    return _LABELS_CACHE


def _db_rel_types() -> set:
    global _RELTYPES_CACHE
    if _RELTYPES_CACHE is None:
        try:
            rows = neo4j_graph.query(
                "CALL db.relationshipTypes() YIELD relationshipType "
                "RETURN relationshipType"
            )
            _RELTYPES_CACHE = {r["relationshipType"] for r in rows}
        except Exception as exc:  # noqa: BLE001
            logger.warning("graphrag: db.relationshipTypes() failed: %s", exc)
            _RELTYPES_CACHE = set()
    return _RELTYPES_CACHE


# ──────────────────────────────────────────────────────────────────────────────
# Component extraction from a generated Cypher query
# ──────────────────────────────────────────────────────────────────────────────
_NODE_RE = re.compile(r"\(\s*(\w+)?\s*:\s*`?(\w+)`?")            # (alias:Label) / (:Label)
_REL_RE = re.compile(r"\[\s*\w*\s*:\s*`?(\w+)`?")               # [r:TYPE] / [:TYPE]
# Property–value equality predicates. Only exact '=' (fragments under
# =~/CONTAINS/STARTS WITH can't be existence-checked against a full value).
# Tolerant of function wrappers on EITHER side, e.g. ``toLower(m.name) =
# toLower("the matrix")`` or ``trim(m.name) = "x"`` — without this the
# perturbed-mention value (the thing we must ground) is never extracted.
_PROP_RE = re.compile(
    r"(?:\b\w+\s*\(\s*)?"          # optional wrapper fn on lhs  e.g. toLower(
    r"(\w+)\.`?(\w+)`?"            # alias.prop
    r"\s*\)?\s*=\s*"              # optional ')' then exact '=' (not =~/<=/>=)
    r"(?:\b\w+\s*\(\s*)?"          # optional wrapper fn on rhs
    r"(['\"])(.*?)\3"             # quoted value
)
# Inline map properties in a node pattern: (x:Label {name: 'v', year: "w"}).
_MAP_RE = re.compile(r"\(\s*\w*\s*:\s*`?(\w+)`?\s*\{([^{}]*)\}")
_KV_RE = re.compile(r"`?(\w+)`?\s*:\s*(['\"])(.*?)\2")


def _extract_components(cypher: str) -> Dict[str, Any]:
    """Pull node labels, relationship types, and (label, prop, value) equality
    predicates out of a Cypher query — covering both ``alias.prop = 'v'``
    (incl. ``toLower(...)``-wrapped) predicates and inline-map node properties
    ``(:Label {prop: 'v'})``. Property aliases are resolved to labels via the
    MATCH node patterns."""
    alias_to_label: Dict[str, str] = {}
    labels: List[str] = []
    for alias, label in _NODE_RE.findall(cypher):
        labels.append(label)
        if alias:
            alias_to_label[alias] = label

    rel_types = _REL_RE.findall(cypher)

    props: List[Tuple[Optional[str], str, str]] = []
    # (a) alias.prop = 'value'  (function-wrapper tolerant)
    for alias, prop, _q, value in _PROP_RE.findall(cypher):
        props.append((alias_to_label.get(alias), prop, value))
    # (b) inline map: (x:Label {prop: 'value', ...}) — label is known directly
    for label, body in _MAP_RE.findall(cypher):
        for prop, _q, value in _KV_RE.findall(body):
            props.append((label, prop, value))

    # de-duplicate while preserving order
    seen: set = set()
    uniq: List[Tuple[Optional[str], str, str]] = []
    for p in props:
        if p not in seen:
            seen.add(p)
            uniq.append(p)

    return {
        "labels": sorted(set(labels)),
        "rel_types": sorted(set(rel_types)),
        "props": uniq,                        # [(label|None, prop, value), ...]
        "alias_to_label": alias_to_label,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Database validation
# ──────────────────────────────────────────────────────────────────────────────
def _value_exists(label: str, prop: str, value: str) -> bool:
    """True iff some ``(:label)`` node has ``prop == value`` (string-equality)."""
    cypher = (
        f"MATCH (n:`{label}`) WHERE n.`{prop}` = $v "
        f"RETURN count(n) > 0 AS ok LIMIT 1"
    )
    try:
        rows = neo4j_graph.query(cypher, params={"v": value})
        return bool(rows and rows[0].get("ok"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag: existence check failed (%s.%s): %s", label, prop, exc)
        # Unknown → don't claim it's invalid (avoid spurious "replace" feedback).
        return True


def _candidate_replacements(label: str, prop: str, value: str) -> List[str]:
    """Candidate replacement values for a missing value, ranked by **normalized
    Levenshtein similarity** over the full ``(label, property)`` value set.

    Primary path is a server-side APOC scan (``apoc.text.levenshteinSimilarity``)
    which ranks every distinct value in one query — this is what actually
    surfaces e.g. "The Matrix" for "the matriks" (Lucene fuzzy fulltext does
    not). Falls back to a Python scan (capped at ``GRAPHRAG_SCAN_CAP``) when
    APOC is unavailable."""
    k = _config.GRAPHRAG_CANDIDATE_K
    thr = float(_config.GRAPHRAG_LEV_THRESHOLD)

    # ── Primary: APOC normalized-Levenshtein ranking (server-side) ────────────
    apoc_q = (
        f"MATCH (n:`{label}`) WHERE n.`{prop}` IS NOT NULL "
        f"WITH DISTINCT toString(n.`{prop}`) AS value "
        f"WITH value, apoc.text.levenshteinSimilarity(toLower(value), toLower($m)) AS sim "
        f"WHERE sim >= $thr "
        f"RETURN value ORDER BY sim DESC LIMIT $k"
    )
    try:
        rows = neo4j_graph.query(apoc_q, params={"m": value, "thr": thr, "k": k})
        cands = [str(r["value"]) for r in rows if r.get("value") is not None]
        if cands:
            return cands
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag: APOC levenshtein scan failed (%s.%s): %s — "
                       "falling back to Python scan", label, prop, exc)

    # ── Fallback: capped Python scan ranked by normalized Levenshtein ─────────
    try:
        rows = neo4j_graph.query(
            f"MATCH (n:`{label}`) WHERE n.`{prop}` IS NOT NULL "
            f"RETURN DISTINCT toString(n.`{prop}`) AS value LIMIT $cap",
            params={"cap": int(_config.GRAPHRAG_SCAN_CAP)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag: candidate value scan failed (%s.%s): %s", label, prop, exc)
        return []
    scored = [(str(r["value"]), normalized_levenshtein(value, str(r["value"])))
              for r in rows if r.get("value") is not None]
    scored = [(c, s) for c, s in scored if s >= thr]
    scored.sort(key=lambda cs: cs[1], reverse=True)
    return [c for c, _ in scored][:k]


def _validate(components: Dict[str, Any]) -> Dict[str, Any]:
    """Validate extracted labels / rel-types / values against the DB.

    Returns a dict with the invalid items and, for invalid values, ranked
    candidate replacements (best-first)."""
    valid_labels, valid_rels = _db_labels(), _db_rel_types()

    bad_labels = [l for l in components["labels"] if valid_labels and l not in valid_labels]
    bad_rels = [r for r in components["rel_types"] if valid_rels and r not in valid_rels]

    bad_values: List[Dict[str, Any]] = []
    for label, prop, value in components["props"]:
        if not label:            # alias we couldn't resolve to a label → skip
            continue
        if valid_labels and label not in valid_labels:
            continue             # already reported as a bad label
        if _value_exists(label, prop, value):
            continue
        bad_values.append({
            "label": label, "prop": prop, "value": value,
            "candidates": _candidate_replacements(label, prop, value),
        })

    return {
        "bad_labels": bad_labels,
        "bad_rels": bad_rels,
        "bad_values": bad_values,
        "valid_labels": sorted(valid_labels),
        "valid_rels": sorted(valid_rels),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Replacement selection (one batched LLM call) + feedback assembly
# ──────────────────────────────────────────────────────────────────────────────
_SELECTOR_SP = """\
A Cypher query referenced property values that do NOT exist in the graph.
For each, choose the single best replacement from its candidate list (the
candidates are real database values, ranked by string similarity), or null if
none is a plausible match for the intended entity.

Invalid values and candidates (JSON):
{payload}

Respond with ONLY a JSON object mapping each original value to your chosen
replacement (a string from its candidate list) or null. Example:
{{"the matriks": "The Matrix", "unknown thing": null}}
"""


def _select_replacements(bad_values: List[Dict[str, Any]], llm) -> Dict[str, Optional[str]]:
    """LLM picks the best replacement per invalid value. Falls back to the top
    Levenshtein candidate if the LLM is unavailable / unparseable."""
    have_cands = [bv for bv in bad_values if bv["candidates"]]
    if not have_cands:
        return {}

    fallback = {bv["value"]: bv["candidates"][0] for bv in have_cands}
    payload = {bv["value"]: bv["candidates"] for bv in have_cands}
    try:
        prompt = _SELECTOR_SP.format(payload=json.dumps(payload, ensure_ascii=False))
        chosen = _parse_json_obj(_llm_text(llm.invoke(prompt)))
        if not isinstance(chosen, dict):
            return fallback
        out: Dict[str, Optional[str]] = {}
        for bv in have_cands:
            v = bv["value"]
            pick = chosen.get(v, fallback[v])
            # Only honour picks that are actually in the candidate list.
            out[v] = pick if pick in bv["candidates"] else fallback[v]
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag: replacement selection failed: %s", exc)
        return fallback


def _build_structural_feedback(
    cypher: str, error: Optional[str], validation: Dict[str, Any],
    replacements: Dict[str, Optional[str]],
) -> str:
    """Aggregate execution + validation feedback for the error/empty branch."""
    lines: List[str] = []
    why = error if error else "executed successfully but returned NO rows"
    lines.append(f"The previous Cypher FAILED ({why}).")
    lines.append("Previous Cypher:")
    lines.append(cypher)
    lines.append("")
    lines.append("Validation against the live database:")

    reported = False
    for label in validation["bad_labels"]:
        reported = True
        lines.append(
            f"- Node label `{label}` is not in the schema. "
            f"Valid labels: {validation['valid_labels']}."
        )
    for rel in validation["bad_rels"]:
        reported = True
        lines.append(
            f"- Relationship type `{rel}` is not in the schema. "
            f"Valid relationship types: {validation['valid_rels']}."
        )
    for bv in validation["bad_values"]:
        reported = True
        repl = replacements.get(bv["value"])
        loc = f"{bv['label']}.{bv['prop']}"
        if repl:
            lines.append(
                f'- Property value "{bv["value"]}" for {loc} does not exist. '
                f'Closest valid values: {bv["candidates"][:5]}. Use "{repl}".'
            )
        elif bv["candidates"]:
            lines.append(
                f'- Property value "{bv["value"]}" for {loc} does not exist. '
                f'Closest valid values: {bv["candidates"][:5]}.'
            )
        else:
            lines.append(
                f'- Property value "{bv["value"]}" for {loc} does not exist and '
                f'no similar value was found — reconsider the field or filter.'
            )

    if not reported:
        lines.append(
            "- No invalid labels/relationships/values detected; the failure is "
            "likely in the query structure or pattern. Re-examine the MATCH "
            "clause and relationship directions."
        )

    lines.append("")
    lines.append(
        "Rewrite the Cypher to fix ALL issues above. Use only schema labels and "
        "relationship types, and the suggested canonical values."
    )
    return "\n".join(lines)


def _build_semantic_feedback(cypher: str, category: str, feedback: str) -> str:
    """Feedback for the incorrect/illogical/incomplete branch (no DB validation)."""
    return (
        f"The previous Cypher executed but the result was judged {category.upper()}.\n"
        f"Previous Cypher:\n{cypher}\n\n"
        f"Evaluator feedback: {feedback}\n\n"
        f"Rewrite the Cypher to address this."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Generator / Executor / Evaluator
# ──────────────────────────────────────────────────────────────────────────────
def _generate_cypher(question: str, schema: str, feedback: str, llm) -> str:
    """Generator agent: fill TEXT2CYPHER_SP and ask the Cypher LLM for a query.
    On round 1 ``feedback`` is empty (no entity hints); later rounds inject the
    aggregated repair feedback into the ``{relevant_entities}`` slot."""
    safe_feedback = (feedback or "{}").replace("{", "{{").replace("}", "}}")
    filled = TEXT2CYPHER_SP.replace("{relevant_entities}", safe_feedback)
    tmpl = PromptTemplate(input_variables=["schema", "question"], template=filled)
    prompt_text = tmpl.format(schema=schema, question=question)
    return _clean_cypher(_llm_text(llm.invoke(prompt_text)))


def _execute(cypher: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Run the query via the same executor the eval harness uses (timeout +
    (rows, error) classification: rows==[] is empty, rows is None on error)."""
    from eval.metrics_CypherBench import execute_cypher
    return execute_cypher(cypher)


_EVALUATOR_SP = """\
You are judging whether a Cypher query correctly answers a question over a
Neo4j graph. Classify the outcome into EXACTLY one category:
  - accept     : the query is correct and the result answers the question.
  - incorrect  : the query runs but returns wrong data (wrong entities,
                 relationships, or filters).
  - illogical  : the query's structure/logic does not match the question intent.
  - incomplete : the query misses part of what the question asks.

Question: {question}
Cypher:
{cypher}
Execution result (sample): {rows}

Respond with ONLY a JSON object:
{{"category": "accept|incorrect|illogical|incomplete",
  "feedback": "one or two sentences of actionable guidance; empty if accept"}}
"""


def _evaluate_semantics(question: str, cypher: str, rows: List[Dict[str, Any]], llm) -> Tuple[str, str]:
    """Evaluator agent for the non-empty case: accept vs a semantic defect."""
    sample = json.dumps(rows[:10], ensure_ascii=False, default=str)
    if len(sample) > 2000:
        sample = sample[:2000] + " …(truncated)"
    try:
        obj = _parse_json_obj(_llm_text(llm.invoke(
            _EVALUATOR_SP.format(question=question, cypher=cypher, rows=sample)
        )))
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag: evaluator call failed: %s", exc)
        return "accept", ""
    if not isinstance(obj, dict):
        return "accept", ""
    category = str(obj.get("category", "accept")).strip().lower()
    if category not in ("accept", "incorrect", "illogical", "incomplete"):
        category = "accept"
    return category, str(obj.get("feedback", "")).strip()


_QA_SP = """\
Answer the question using ONLY the query results below. Be concise.

Question: {question}
Query results: {rows}
Answer:"""


def _format_answer(question: str, rows: List[Dict[str, Any]], llm) -> str:
    sample = json.dumps(rows[:50], ensure_ascii=False, default=str)
    if len(sample) > 4000:
        sample = sample[:4000] + " …(truncated)"
    try:
        return _llm_text(llm.invoke(_QA_SP.format(question=question, rows=sample))).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag: answer formatting failed: %s", exc)
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────────
def run_graphrag(
    question: str,
    *,
    verbose: bool = False,
    cypher_llm=None,
    qa_llm=None,
    eval_llm=None,
) -> Dict[str, Any]:
    """Run the Multi-Agent GraphRAG self-correction loop for one question.

    Returns the same dict shape as ``ner_agent_auto.ask_auto`` (``entities`` /
    ``cypher`` / ``result`` / ``context`` / ``mode``) plus ``graphrag_trace``.
    """
    gen_llm = cypher_llm if cypher_llm is not None else _cypher_llm
    ans_llm = qa_llm if qa_llm is not None else _qa_llm
    judge_llm = eval_llm if eval_llm is not None else _ner_llm

    schema = neo4j_graph.schema
    max_iter = max(1, int(_config.GRAPHRAG_MAX_ITER))

    feedback = ""                      # round 1: no entity hints
    trace: List[Dict[str, Any]] = []
    best_cypher, best_rows = "", []
    accepted = False

    for rnd in range(1, max_iter + 1):
        cypher = _generate_cypher(question, schema, feedback, gen_llm)
        rows, error = _execute(cypher)
        # Faithful to the paper: the current attempt is what we carry forward;
        # the final returned query is simply the last (or accepted) one.
        best_cypher = cypher
        best_rows = rows if rows is not None else []

        # ── classify the outcome ──────────────────────────────────────────────
        sem_feedback = ""
        if error is not None:
            category = "error"
        elif rows == []:
            category = "empty" if _config.GRAPHRAG_EMPTY_IS_WRONG else "accept"
        elif _config.GRAPHRAG_LLM_EVALUATOR:
            category, sem_feedback = _evaluate_semantics(question, cypher, rows, judge_llm)
        else:
            category = "accept"

        step = {"round": rnd, "cypher": cypher, "error": error,
                "n_rows": len(rows) if rows is not None else 0, "category": category}
        trace.append(step)
        if verbose:
            print(f"\n── GraphRAG round {rnd} ──────────────────────────────────────────────")
            print(f"  cypher   : {cypher}")
            print(f"  outcome  : {category}  (rows={step['n_rows']}, error={error})")

        if category == "accept":
            accepted = True
            break
        if rnd == max_iter:
            break

        # ── build feedback for the next round ─────────────────────────────────
        if category in ("error", "empty"):
            components = _extract_components(cypher)
            validation = _validate(components)
            replacements = _select_replacements(validation["bad_values"], judge_llm)
            feedback = _build_structural_feedback(cypher, error, validation, replacements)
            step["validation"] = {
                "bad_labels": validation["bad_labels"],
                "bad_rels": validation["bad_rels"],
                "bad_values": [
                    {"loc": f"{bv['label']}.{bv['prop']}", "value": bv["value"],
                     "replacement": replacements.get(bv["value"])}
                    for bv in validation["bad_values"]
                ],
            }
        else:  # incorrect | illogical | incomplete
            feedback = _build_semantic_feedback(cypher, category, sem_feedback)
        if verbose:
            print(f"  feedback → next round:\n{feedback}")

    result = _format_answer(question, best_rows, ans_llm)
    if verbose:
        print(f"\n── GraphRAG done ({'accepted' if accepted else 'exhausted'} after "
              f"{len(trace)} round(s)) ──")
        print(f"  cypher : {best_cypher}")
        print(f"  answer : {result}")

    return {
        "entities": "{}",                 # graphrag does no pre-grounding
        "cypher": best_cypher,
        "result": result,
        "context": best_rows,
        "mode": "graphrag",
        "graphrag_trace": trace,
        "graphrag_accepted": accepted,
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Multi-Agent GraphRAG baseline (single question)")
    ap.add_argument("question")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    out = run_graphrag(args.question, verbose=args.verbose)
    print("\n=== RESULT ===")
    print("cypher:", out["cypher"])
    print("answer:", out["result"])
    print("rounds:", len(out["graphrag_trace"]), "accepted:", out["graphrag_accepted"])
