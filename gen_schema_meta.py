#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_schema_meta.py
==================
Uses an LLM to infer semantic metadata for every node label and relationship
type discovered in the schema CSVs, then writes **schema_meta.json**.

This script bridges raw schema introspection (``gen_schema_csv.py``) and tool
generation (``gen_tools.py``).  It lets ``gen_tools.py`` produce accurate,
domain-agnostic tool descriptions for *any* Neo4j database — no hardcoded
English-language heuristics needed.

What it produces
----------------
``schema_meta.json`` — one entry per node label and relationship type::

    {
      "nodes": {
        "Movie": {
          "id_property": "title",
          "properties": {
            "title":    {"data_type": "title", "topic": "movie title",        "description": "..."},
            "released": {"data_type": "year",  "topic": "movie release year", "description": "..."}
          }
        }
      },
      "relationships": {
        "ACTED_IN": {
          "properties": {
            "roles": {"data_type": "list", "topic": "actor roles", "description": "..."}
          }
        }
      },
      "generated_at_utc": "2026-04-26T...",
      "language": "en"
    }

Usage
-----
  python gen_schema_meta.py
  python gen_schema_meta.py --nodes-csv schema_nodes.csv --rels-csv schema_relations.csv
  python gen_schema_meta.py --output schema_meta.json --language zh

Prerequisites
-------------
  - ``schema_nodes.csv`` and ``schema_relations.csv`` (from ``gen_schema_csv.py``)
  - An OpenAI or Azure OpenAI API key (for LLM inference)

Environment variables  (loaded from .env)
-----------------------------------------
  OPENAI_API_KEY                   (required unless Azure vars are set)
  AZURE_OPENAI_ENDPOINT            Azure OpenAI endpoint URL
  AZURE_OPENAI_API_KEY             Azure OpenAI key
  AZURE_OPENAI_DEPLOYMENT          Azure model deployment name
  OPENAI_MODEL                     default: gpt-4.1
  OPENAI_BASE_URL                  optional proxy / gateway
  TOOL_GEN_LANGUAGE                default language for topic/description (en)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv(".env", override=True)

# Module logger.  Per-label progress lines are logger.info so setup_project.py
# routes them to the file handler only by default; --verbose surfaces them
# back on the console.
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# LLM builder  (mirrors ner_agent.build_llm — supports Azure + public OpenAI)
# ──────────────────────────────────────────────────────────────────────────────

def _build_llm(temperature: float = 0):
    """Build an LLM client.  Prefer Azure OpenAI if env vars are set."""
    import httpx
    from langchain_openai import ChatOpenAI, AzureChatOpenAI

    trust_env = os.getenv("TRUST_ENV", "1") != "0"
    http_client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        trust_env=trust_env,
    )

    azure_endpoint   = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key        = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    if azure_endpoint and azure_key and azure_deployment:
        base_url = azure_endpoint.rstrip("/") + "/openai/v1/"
        try:
            return ChatOpenAI(
                model=azure_deployment,
                api_key=azure_key,
                base_url=base_url,
                temperature=temperature,
                timeout=60,
                max_retries=6,
                http_client=http_client,
            )
        except Exception:
            return AzureChatOpenAI(
                azure_deployment=azure_deployment,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                temperature=temperature,
                timeout=60,
                max_retries=6,
                http_client=http_client,
            )

    # Public OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No LLM credentials found.  Set OPENAI_API_KEY or "
            "AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT."
        )
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1"),
        api_key=api_key,
        temperature=temperature,
        timeout=60,
        max_retries=6,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        http_client=http_client,
    )


# ──────────────────────────────────────────────────────────────────────────────
# CSV readers — group schema rows by label / rel_type
# ──────────────────────────────────────────────────────────────────────────────

def _read_node_schema(csv_path: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Read ``schema_nodes.csv`` and group rows by label.

    Returns ``{label: [row_dict, ...]}``.
    """
    by_label: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                label = (row.get("label") or "").strip()
                if label:
                    by_label[label].append(row)
    except FileNotFoundError:
        logger.warning("%s not found.  Run gen_schema_csv.py first.", csv_path)
    return dict(by_label)


def _read_rel_schema(csv_path: str) -> Tuple[
    Dict[str, List[Dict[str, str]]],
    Dict[str, List[Tuple[str, str]]],
]:
    """
    Read ``schema_relations.csv``.

    Returns
    -------
    props_by_rel : ``{rel_type: [row_dict, ...]}``  (only rows with a property)
    topology     : ``{rel_type: [(from_label, to_label), ...]}``
    """
    props_by_rel: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    topology:     Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rt   = (row.get("rel_type")   or "").strip()
                fl   = (row.get("from_label") or "").strip()
                tl   = (row.get("to_label")   or "").strip()
                prop = (row.get("property")   or "").strip()
                if not rt:
                    continue
                if fl and tl:
                    pair = (fl, tl)
                    if pair not in topology[rt]:
                        topology[rt].append(pair)
                if prop:
                    props_by_rel[rt].append(row)
    except FileNotFoundError:
        logger.warning("%s not found.  Run gen_schema_csv.py first.", csv_path)
    return dict(props_by_rel), dict(topology)


# ──────────────────────────────────────────────────────────────────────────────
# LLM prompts
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEM_MSG = (
    "You are a database schema analyst.  Given a Neo4j node label or "
    "relationship type with its properties, property types, and sample values, "
    "you infer semantic metadata.  "
    "Output ONLY valid JSON — no markdown fences, no explanation."
)

_NODE_HUMAN_TEMPLATE = """\
Analyze the Neo4j node label and its properties below.

Node label: {label}
Total nodes: {node_count}

Properties:
{properties_block}

For each property, infer:
  data_type   : one of: name, title, text, year, date, number, boolean, id,
                list, enum, other
  topic       : a short phrase (2-5 words) for NER extraction
                (e.g. "movie release year", "person name", "job title"){language_note}
  description : one sentence describing what this property stores

Also determine:
  id_property : which ONE property best identifies individual nodes of this
                label (the most human-readable, unique-ish identifier — usually
                a name or title).  If no property qualifies, use null.

Output ONLY valid JSON:
{{
  "id_property": "<property_name or null>",
  "properties": {{
    "<prop_name>": {{
      "data_type": "...",
      "topic": "...",
      "description": "..."
    }}
  }}
}}"""

_REL_HUMAN_TEMPLATE = """\
Analyze the Neo4j relationship type and its properties below.

Relationship type: {rel_type}
Connects: {connections}
Total relationships: {rel_count}

Properties:
{properties_block}

For each property, infer:
  data_type   : one of: name, title, text, year, date, number, boolean, id,
                list, enum, other
  topic       : a short phrase (2-5 words) for NER extraction{language_note}
  description : one sentence describing what this property stores

Output ONLY valid JSON:
{{
  "properties": {{
    "<prop_name>": {{
      "data_type": "...",
      "topic": "...",
      "description": "..."
    }}
  }}
}}"""


def _fmt_properties_block(rows: List[Dict[str, str]]) -> str:
    """Format property rows into a readable block for the LLM prompt."""
    lines: List[str] = []
    for row in rows:
        prop    = row.get("property", "")
        types   = row.get("property_types", "")
        samples = row.get("sample_values", "")
        fill    = row.get("fill_pct", "")
        line = f"  - {prop}"
        if types:
            line += f"  (type: {types})"
        if fill:
            line += f"  (fill: {fill})"
        if samples:
            line += f"\n    sample values: {samples}"
        lines.append(line)
    return "\n".join(lines) if lines else "  (no properties)"


# ──────────────────────────────────────────────────────────────────────────────
# JSON parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    """Remove optional markdown code fences."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON from LLM output, stripping fences if needed."""
    text = _strip_fences(text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Fallback: extract first {...} block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# LLM inference — one call per label / rel_type
# ──────────────────────────────────────────────────────────────────────────────

def infer_node_meta(
    llm,
    label: str,
    rows: List[Dict[str, str]],
    language: str = "en",
) -> Dict[str, Any]:
    """
    Call the LLM once to infer metadata for all properties of a node label.

    Returns ``{"id_property": ..., "properties": {...}}``.
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    node_count  = rows[0].get("node_count", "?") if rows else "?"
    props_block = _fmt_properties_block(rows)

    language_note = ""
    if language and language.lower() != "en":
        language_note = (
            f"\n  NOTE: Write topic and description in language code: {language}"
        )

    human = _NODE_HUMAN_TEMPLATE.format(
        label=label,
        node_count=node_count,
        properties_block=props_block,
        language_note=language_note,
    )

    msg = llm.invoke([
        SystemMessage(content=_SYSTEM_MSG),
        HumanMessage(content=human),
    ])

    parsed = _parse_json(msg.content or "")
    if parsed is None:
        logger.warning("LLM output for label %r was not valid JSON. "
                       "Using empty metadata.", label)
        return {"id_property": None, "properties": {}}

    return parsed


def infer_rel_meta(
    llm,
    rel_type: str,
    rows: List[Dict[str, str]],
    connections: List[Tuple[str, str]],
    language: str = "en",
) -> Dict[str, Any]:
    """
    Call the LLM once to infer metadata for all properties of a relationship type.

    Returns ``{"properties": {...}}``.
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    conn_str  = ", ".join(
        f"(:{fl})-[:{rel_type}]->(:{tl})" for fl, tl in connections
    )
    rel_count   = rows[0].get("rel_count", "?") if rows else "?"
    props_block = _fmt_properties_block(rows)

    language_note = ""
    if language and language.lower() != "en":
        language_note = (
            f"\n  NOTE: Write topic and description in language code: {language}"
        )

    human = _REL_HUMAN_TEMPLATE.format(
        rel_type=rel_type,
        connections=conn_str or "(topology unknown)",
        rel_count=rel_count,
        properties_block=props_block,
        language_note=language_note,
    )

    msg = llm.invoke([
        SystemMessage(content=_SYSTEM_MSG),
        HumanMessage(content=human),
    ])

    parsed = _parse_json(msg.content or "")
    if parsed is None:
        logger.warning("LLM output for rel %r was not valid JSON. "
                       "Using empty metadata.", rel_type)
        return {"properties": {}}

    return parsed


# ──────────────────────────────────────────────────────────────────────────────
# Main generation function  (called by setup_project.py or CLI)
# ──────────────────────────────────────────────────────────────────────────────

def generate_schema_meta(
    nodes_csv: str  = "schema_nodes.csv",
    rels_csv:  str  = "schema_relations.csv",
    output:    str  = "schema_meta.json",
    language:  str  = "en",
    verbose:   bool = False,
) -> Dict[str, Any]:
    """
    Read schema CSVs, call the LLM to infer metadata, write schema_meta.json.

    Parameters
    ----------
    nodes_csv : Path to schema_nodes.csv.
    rels_csv  : Path to schema_relations.csv.
    output    : Destination path for schema_meta.json.
    language  : Language code for topic/description fields (default ``"en"``).
    verbose   : Print per-property details.

    Returns
    -------
    dict  The complete schema_meta structure (also written to *output*).
    """
    logger.info("Reading schema CSVs …")
    node_groups              = _read_node_schema(nodes_csv)
    rel_groups, topology_map = _read_rel_schema(rels_csv)

    if not node_groups and not rel_groups:
        logger.warning("No schema data found in CSVs. Cannot generate metadata.")
        return {}

    n_rel_with_props = len(rel_groups)
    logger.info("%d node label(s), %d relationship type(s) with properties",
                len(node_groups), n_rel_with_props)

    # Build LLM
    logger.info("Initializing LLM …")
    llm = _build_llm(temperature=0)

    meta: Dict[str, Any] = {"nodes": {}, "relationships": {}}

    # ── Infer node metadata ──────────────────────────────────────────────────
    for i, (label, rows) in enumerate(sorted(node_groups.items()), 1):
        prop_names = [r.get("property", "") for r in rows]
        logger.info("[%d/%d] %s (%d props: %s)",
                    i, len(node_groups), label, len(rows), prop_names)
        try:
            result = infer_node_meta(llm, label, rows, language=language)
            meta["nodes"][label] = result
            id_prop = result.get("id_property")
            logger.info("  id_property = %r", id_prop)
            if verbose:
                for pn, pm in result.get("properties", {}).items():
                    logger.debug("    %s: type=%s, topic=%r",
                                 pn, pm.get("data_type"), pm.get("topic"))
        except Exception as e:
            logger.error("LLM call failed for label %r: %s", label, e)
            meta["nodes"][label] = {"id_property": None, "properties": {}}

    # ── Infer relationship metadata ──────────────────────────────────────────
    all_rel_types = sorted(set(rel_groups.keys()) | set(topology_map.keys()))
    for i, rt in enumerate(all_rel_types, 1):
        rows  = rel_groups.get(rt, [])
        conns = topology_map.get(rt, [])
        if rows:
            prop_names = sorted({r.get("property", "") for r in rows})
            logger.info("[%d/%d] %s (%d props: %s)",
                        i, len(all_rel_types), rt, len(prop_names), prop_names)
            try:
                result = infer_rel_meta(llm, rt, rows, conns, language=language)
                meta["relationships"][rt] = result
                logger.info("  done")
            except Exception as e:
                logger.error("LLM call failed for rel %r: %s", rt, e)
                meta["relationships"][rt] = {"properties": {}}
        else:
            # Structural (property-less) relationship — no LLM call needed.
            meta["relationships"][rt] = {"properties": {}}

    # ── Timestamp + language ─────────────────────────────────────────────────
    meta["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    meta["language"]         = language

    # ── Write output ─────────────────────────────────────────────────────────
    with open(output, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    n_labels = len(meta["nodes"])
    n_rels   = len(meta["relationships"])
    logger.info("schema_meta.json written → %r (%d labels, %d rel types)",
                output, n_labels, n_rels)
    return meta


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generate schema_meta.json by using an LLM to infer semantic "
            "metadata from schema CSVs."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--nodes-csv", default="schema_nodes.csv", metavar="PATH",
        help="Path to schema_nodes.csv",
    )
    p.add_argument(
        "--rels-csv", default="schema_relations.csv", metavar="PATH",
        help="Path to schema_relations.csv",
    )
    p.add_argument(
        "--output", default="schema_meta.json", metavar="PATH",
        help="Output path for schema_meta.json",
    )
    p.add_argument(
        "--language",
        default=os.getenv("TOOL_GEN_LANGUAGE", "en"),
        metavar="LANG",
        help="Language for topic/description (default: en, or TOOL_GEN_LANGUAGE)",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Print per-property details during inference",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    generate_schema_meta(
        nodes_csv = args.nodes_csv,
        rels_csv  = args.rels_csv,
        output    = args.output,
        language  = args.language,
        verbose   = args.verbose,
    )


if __name__ == "__main__":
    main()
