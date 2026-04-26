#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Auto-generate and iteratively validate tool descriptions for (node_type, property) pairs
from a Neo4j database, store results in CSV, and index all descriptions into a FAISS vector DB
using OpenAI Ada embeddings.

Validation uses a stability-based stopping criterion: the loop runs until the
tool description is unchanged for STABILITY_K consecutive rounds, or until
MAX_VALIDATION_ROUNDS total rounds are reached (both imported from config.py).

Usage example:
  python tool_gen_node_rd.py --t 20 --output_csv tools.csv --faiss_dir faiss_tools --resume

Environment variables required:
  NEO4J_URI
  NEO4J_USERNAME
  NEO4J_PASSWORD
  (optional) NEO4J_DATABASE (default: neo4j)

OpenAI / LangChain env vars:
  OPENAI_API_KEY
  (optional) OPENAI_MODEL (default: gpt-4o)
  (optional) OPENAI_BASE_URL
  (optional) OPENAI_EMBEDDING_MODEL (default: text-embedding-ada-002)
  (optional) TRUST_ENV (default: 1)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import httpx
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from langchain_community.vectorstores import FAISS

# FAISS import path varies by LangChain version.
try:
    from langchain_community.vectorstores import FAISS
except ImportError:  # pragma: no cover
    from langchain.vectorstores import FAISS  # type: ignore

# Optional: .env support (safe if not installed)
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass


# -----------------------------
# Provided helpers (as requested)
# -----------------------------
def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}. Please set it in .env or system env.")
    return v


def build_llm(temperature: float = 0) -> ChatOpenAI:
    """
    OpenAI-only LLM builder (NO Azure).

    Safe for local / non-Azure environments.
    """
    trust_env = os.getenv("TRUST_ENV", "1") != "0"

    http_client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        trust_env=trust_env,
    )

    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        api_key=_require_env("OPENAI_API_KEY"),
        temperature=temperature,
        timeout=60,
        max_retries=6,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        http_client=http_client,
    )


def build_embeddings() -> OpenAIEmbeddings:
    """
    Build OpenAI embeddings client. Defaults to Ada embedding model.
    You can override by setting OPENAI_EMBEDDING_MODEL env var.
    """
    trust_env = os.getenv("TRUST_ENV", "1") != "0"

    http_client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        trust_env=trust_env,
    )

    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"),
        api_key=_require_env("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        http_client=http_client,
    )


# -----------------------------
# Config / data structures
# -----------------------------
@dataclass(frozen=True)
class Pair:
    node_type: str  # e.g. ":Person" or ":Person:Employee" or label name fallback
    property_name: str


@dataclass
class ResultRow:
    node_type: str
    property_name: str
    tool_description_json: str
    revisions: int
    validations_run: int
    sampled_values_first_n: int
    updated_at_utc: str


# -----------------------------
# Neo4j utilities
# -----------------------------
def _escape_label(label: str) -> str:
    """
    Escape a Neo4j label with backticks.
    """
    # Replace backticks to avoid breaking Cypher. Neo4j uses double backticks to escape.
    safe = label.replace("`", "``")
    return f"`{safe}`"


def node_type_to_match_pattern(node_type: str) -> str:
    """
    Convert a nodeType string like ':Person:Employee' into a Cypher label pattern:
      :`Person`:`Employee`

    If node_type is already a single label without ':' prefix, treat it as a label.
    """
    if node_type.startswith(":"):
        parts = [p for p in node_type.split(":") if p]
    else:
        parts = [node_type]

    if not parts:
        return ""  # No labels (unlikely), match any node.

    return ":" + ":".join(_escape_label(p) for p in parts)


def list_node_type_property_pairs(driver, database: str) -> List[Pair]:
    """
    Prefer db.schema.nodeTypeProperties() to enumerate (nodeType, propertyName).
    Fall back to scanning labels + keys(n) if the procedure is not available.
    """
    pairs: List[Pair] = []
    with driver.session(database=database) as session:
        # 1) Try nodeTypeProperties (fast and comprehensive for schema-discoverable props).
        try:
            cypher = """
            CALL db.schema.nodeTypeProperties()
            YIELD nodeType, propertyName
            RETURN nodeType, propertyName
            """
            records = list(session.run(cypher))
            for r in records:
                nt = r.get("nodeType")
                pn = r.get("propertyName")
                if nt and pn:
                    pairs.append(Pair(str(nt), str(pn)))

            # Deduplicate while preserving order.
            seen: Set[Tuple[str, str]] = set()
            deduped: List[Pair] = []
            for p in pairs:
                key = (p.node_type, p.property_name)
                if key not in seen:
                    seen.add(key)
                    deduped.append(p)
            return deduped

        except Neo4jError:
            # Continue to fallback
            pass
        except Exception:
            # Continue to fallback
            pass

        # 2) Fallback: scan each label and its observed property keys.
        label_records = list(session.run("CALL db.labels() YIELD label RETURN label"))
        labels = [str(r["label"]) for r in label_records if r.get("label")]

        for label in labels:
            label_pattern = ":" + _escape_label(label)
            cypher_keys = f"""
            MATCH (n{label_pattern})
            UNWIND keys(n) AS k
            RETURN DISTINCT k AS propertyName
            """
            for r in session.run(cypher_keys):
                pn = r.get("propertyName")
                if pn:
                    pairs.append(Pair(label, str(pn)))

        # Deduplicate
        seen2: Set[Tuple[str, str]] = set()
        deduped2: List[Pair] = []
        for p in pairs:
            key = (p.node_type, p.property_name)
            if key not in seen2:
                seen2.add(key)
                deduped2.append(p)
        return deduped2


CAP_MULTIPLIER = 5  # scan cap = t * CAP_MULTIPLIER (cheap over-fetch for random sampling)


def sample_property_values(
    session,
    node_type: str,
    property_name: str,
    t: int,
) -> List[Any]:
    """
    Sample up to *t* property values using a cheap capped scan + Python ``random.sample()``.

    Instead of the expensive ``ORDER BY rand()`` (which forces a full-graph sort),
    we over-fetch ``t * CAP_MULTIPLIER`` rows with a plain ``LIMIT`` and then
    randomly down-sample in Python.  This keeps the Neo4j query O(cap) rather
    than O(N log N).
    """
    label_pattern = node_type_to_match_pattern(node_type)
    cap = t * CAP_MULTIPLIER

    cypher = f"""
    MATCH (n{label_pattern})
    WHERE n[$prop] IS NOT NULL
    RETURN n[$prop] AS value
    LIMIT $cap
    """
    values = []
    for r in session.run(cypher, prop=property_name, cap=cap):
        values.append(r.get("value"))

    if len(values) <= t:
        return values
    return random.sample(values, t)


# -----------------------------
# LLM prompts + parsing
# -----------------------------
GEN_SYS = """You generate tool documentation for an agent that queries a Neo4j knowledge graph.
You will be given a node type (Neo4j labels), a property name, and example values.
You must output ONLY valid JSON (no markdown fences, no extra text)."""

GEN_HUMAN_TEMPLATE = """Create a concise tool description for a hypothetical tool that helps an agent filter/search nodes.

Inputs:
- node_type: {node_type}
- property_name: {property_name}
- sample_values (JSON): {sample_values_json}

Requirements:
- Output MUST be valid JSON and nothing else.
- JSON schema:
  {{
    "tool_name": string,
    "description": string,
    "when_to_use": string,
    "inputs": object,
    "outputs": string,
    "examples": [string, ...],
    "notes": string
  }}
- Infer likely data type/shape from sample_values (string/number/date/list/bool) and reflect it.
- Do not hallucinate domain facts not supported by sample_values and the property name.
- Keep the description field under 1200 characters.
"""

VAL_SYS = """You are a strict reviewer of a tool description. You must output ONLY valid JSON (no markdown fences, no extra text)."""

VAL_HUMAN_TEMPLATE = """Review whether the current tool description is reasonable for the given node type/property and NEW example values.

Inputs:
- node_type: {node_type}
- property_name: {property_name}
- NEW sample_values (JSON): {sample_values_json}
- current_tool_description (JSON): {current_tool_description_json}

Decision:
- If reasonable: output {{"is_reasonable": true, "issues": [], "revised_tool_description": null}}
- If not reasonable: output {{"is_reasonable": false, "issues": [..], "revised_tool_description": <FULL revised JSON tool description>}}
Rules:
- revised_tool_description must follow the same schema as the generation step.
- Prefer minimal edits that fix the mismatch.
"""


def _strip_code_fences(text: str) -> str:
    """
    Remove ```json ... ``` fences if the model accidentally returns them.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_first_json_object(text: str) -> str:
    """
    Extract the first top-level JSON object from a string.
    If the string is already pure JSON, returns it.
    """
    text = _strip_code_fences(text)

    # Fast path: direct JSON
    try:
        json.loads(text)
        return text
    except Exception:
        pass

    # Fallback: find first {...} block
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output.")
    candidate = m.group(0)
    json.loads(candidate)  # validate
    return candidate


def llm_generate_tool_description(
    llm: ChatOpenAI,
    node_type: str,
    property_name: str,
    sample_values: Sequence[Any],
) -> Dict[str, Any]:
    """
    Ask LLM to create the initial tool description (as JSON dict).
    """
    sample_values_json = json.dumps(sample_values, ensure_ascii=False)
    human = GEN_HUMAN_TEMPLATE.format(
        node_type=node_type,
        property_name=property_name,
        sample_values_json=sample_values_json,
    )
    msg = llm.invoke([SystemMessage(content=GEN_SYS), HumanMessage(content=human)])
    content = getattr(msg, "content", "") or ""
    obj_str = _extract_first_json_object(content)
    return json.loads(obj_str)


def llm_validate_and_maybe_revise(
    llm: ChatOpenAI,
    node_type: str,
    property_name: str,
    new_sample_values: Sequence[Any],
    current_tool_description: Dict[str, Any],
) -> Tuple[bool, List[str], Optional[Dict[str, Any]]]:
    """
    Ask LLM to validate current tool description with new samples.
    Return (is_reasonable, issues, revised_description_or_none).
    """
    sample_values_json = json.dumps(new_sample_values, ensure_ascii=False)
    current_json = json.dumps(current_tool_description, ensure_ascii=False)

    human = VAL_HUMAN_TEMPLATE.format(
        node_type=node_type,
        property_name=property_name,
        sample_values_json=sample_values_json,
        current_tool_description_json=current_json,
    )
    msg = llm.invoke([SystemMessage(content=VAL_SYS), HumanMessage(content=human)])
    content = getattr(msg, "content", "") or ""
    obj_str = _extract_first_json_object(content)
    parsed = json.loads(obj_str)

    is_ok = bool(parsed.get("is_reasonable", False))
    issues = parsed.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]

    revised = parsed.get("revised_tool_description")
    if revised is None:
        return is_ok, [str(x) for x in issues], None
    if isinstance(revised, dict):
        return is_ok, [str(x) for x in issues], revised

    # If revised is returned as a string accidentally, try parsing it.
    if isinstance(revised, str):
        revised_str = _extract_first_json_object(revised)
        return is_ok, [str(x) for x in issues], json.loads(revised_str)

    return is_ok, [str(x) for x in issues], None


# -----------------------------
# CSV + FAISS utilities
# -----------------------------
CSV_HEADER = [
    "node_type",
    "property_name",
    "tool_description_json",
    "revisions",
    "validations_run",
    "sampled_values_first_n",
    "updated_at_utc",
]


def load_processed_pairs(csv_path: str) -> Set[Tuple[str, str]]:
    """
    Read existing CSV and return a set of processed (node_type, property_name).
    """
    processed: Set[Tuple[str, str]] = set()
    if not os.path.exists(csv_path):
        return processed

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nt = row.get("node_type")
            pn = row.get("property_name")
            if nt and pn:
                processed.add((nt, pn))
    return processed


def append_result_row(csv_path: str, row: ResultRow) -> None:
    """
    Append a row to CSV. Create file + header if needed.
    """
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER, quoting=csv.QUOTE_MINIMAL)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "node_type": row.node_type,
                "property_name": row.property_name,
                "tool_description_json": row.tool_description_json,
                "revisions": row.revisions,
                "validations_run": row.validations_run,
                "sampled_values_first_n": row.sampled_values_first_n,
                "updated_at_utc": row.updated_at_utc,
            }
        )


def tool_json_to_search_text(tool_obj: Dict[str, Any]) -> str:
    """
    Build a compact text for embedding-based retrieval.
    Keep it short and high-signal.
    """
    tool_name = str(tool_obj.get("tool_name", ""))
    desc = str(tool_obj.get("description", ""))
    when = str(tool_obj.get("when_to_use", ""))
    examples = tool_obj.get("examples") or []

    if not isinstance(examples, list):
        examples = [str(examples)]

    # Only keep a few examples to reduce noise
    examples = [str(x) for x in examples[:3]]

    parts = [
        f"tool_name: {tool_name}".strip(),
        f"description: {desc}".strip(),
        f"when_to_use: {when}".strip(),
        "examples: " + " | ".join(examples) if examples else "",
    ]
    # Remove empty lines
    return "\n".join([p for p in parts if p])


def build_faiss_from_csv(csv_path: str, faiss_dir: str, embeddings) -> None:
    """
    Load tool descriptions from CSV and index them into FAISS.
    Embedding text is compact search_text, while full JSON is stored in metadata.
    """
    texts: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_json = row.get("tool_description_json")
            nt = row.get("node_type")
            pn = row.get("property_name")
            if not raw_json or not nt or not pn:
                continue

            try:
                tool_obj = json.loads(raw_json)
            except Exception:
                # If JSON is broken, still index the raw text
                tool_obj = {"tool_name": "", "description": raw_json}

            search_text = tool_json_to_search_text(tool_obj)

            texts.append(search_text)
            metadatas.append(
                {
                    "node_type": nt,
                    "property_name": pn,
                    # Store full tool JSON for downstream usage
                    "tool_json": json.dumps(tool_obj, ensure_ascii=False),
                }
            )

    if not texts:
        raise RuntimeError("No tool descriptions found in CSV to index.")

    os.makedirs(faiss_dir, exist_ok=True)
    vectorstore = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas)
    vectorstore.save_local(faiss_dir)



# -----------------------------
# Main pipeline
# -----------------------------
def run_pipeline(
    t: int,
    output_csv: str,
    faiss_dir: str,
    resume: bool,
    temperature: float,
    sleep_seconds: float,
    limit_pairs: Optional[int],
) -> None:
    """
    End-to-end pipeline:
      1) scan pairs
      2) generate + validate descriptions (stability-based stopping)
      3) write CSV incrementally
      4) build FAISS at the end

    Validation uses ``STABILITY_K`` (consecutive stable rounds to stop) and
    ``MAX_VALIDATION_ROUNDS`` (hard cap) from ``config.py``.
    """
    from config import MAX_VALIDATION_ROUNDS, STABILITY_K

    neo4j_uri = _require_env("NEO4J_URI")
    neo4j_user = _require_env("NEO4J_USERNAME")
    neo4j_pass = _require_env("NEO4J_PASSWORD")
    neo4j_db = os.getenv("NEO4J_DATABASE", "neo4j")

    llm = build_llm(temperature=temperature)

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))

    try:
        pairs = list_node_type_property_pairs(driver, neo4j_db)
        if limit_pairs is not None:
            pairs = pairs[: max(0, limit_pairs)]

        processed: Set[Tuple[str, str]] = set()
        if resume:
            processed = load_processed_pairs(output_csv)

        with driver.session(database=neo4j_db) as session:
            for idx, pair in enumerate(pairs, start=1):
                key = (pair.node_type, pair.property_name)
                if resume and key in processed:
                    continue

                # 1) First sampling for initial generation
                first_values = sample_property_values(session, pair.node_type, pair.property_name, t=t)
                if not first_values:
                    # Skip pairs that have no non-null values (rare, but possible)
                    continue

                tool_desc = llm_generate_tool_description(
                    llm=llm,
                    node_type=pair.node_type,
                    property_name=pair.property_name,
                    sample_values=first_values,
                )

                revisions = 0
                validations_run = 0

                # 2) Iterative validation: stop after STABILITY_K consecutive
                #    stable rounds OR after MAX_VALIDATION_ROUNDS total.
                consecutive_stable = 0
                for round_i in range(1, MAX_VALIDATION_ROUNDS + 1):
                    new_values = sample_property_values(session, pair.node_type, pair.property_name, t=t)
                    if not new_values:
                        # If we cannot sample new values, stop early.
                        break

                    is_ok, issues, revised = llm_validate_and_maybe_revise(
                        llm=llm,
                        node_type=pair.node_type,
                        property_name=pair.property_name,
                        new_sample_values=new_values,
                        current_tool_description=tool_desc,
                    )
                    validations_run += 1

                    if not is_ok and revised is not None:
                        tool_desc = revised
                        revisions += 1
                        consecutive_stable = 0  # reset on revision
                    else:
                        consecutive_stable += 1

                    if consecutive_stable >= STABILITY_K:
                        break

                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)

                # 3) Write result to CSV
                row = ResultRow(
                    node_type=pair.node_type,
                    property_name=pair.property_name,
                    tool_description_json=json.dumps(tool_desc, ensure_ascii=False),
                    revisions=revisions,
                    validations_run=validations_run,
                    sampled_values_first_n=len(first_values),
                    updated_at_utc=dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                )
                append_result_row(output_csv, row)

                # Simple progress log to stderr (so it won't pollute CSV piping if needed).
                print(
                    f"[{idx}/{len(pairs)}] Saved: ({pair.node_type}, {pair.property_name}) "
                    f"revisions={revisions}, validations={validations_run}, "
                    f"stable={consecutive_stable}",
                    file=sys.stderr,
                )

    finally:
        try:
            driver.close()
        except Exception:
            pass

    # 4) Build FAISS from CSV at the end
    embeddings = build_embeddings()
    os.makedirs(faiss_dir, exist_ok=True)
    build_faiss_from_csv(output_csv, faiss_dir, embeddings)
    print(f"FAISS index saved to: {faiss_dir}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate tool descriptions from Neo4j and index into FAISS.")
    parser.add_argument("--t", type=int, default=int(os.getenv("SAMPLE_T", "20")), help="Sample size t per round.")
    parser.add_argument("--output_csv", type=str, default="tool_descriptions.csv", help="Output CSV path.")
    parser.add_argument("--faiss_dir", type=str, default="faiss_tools", help="Output FAISS directory.")
    parser.add_argument("--resume", action="store_true", help="Skip pairs already present in output CSV.")
    parser.add_argument("--temperature", type=float, default=0.0, help="LLM temperature.")
    parser.add_argument(
        "--sleep_seconds",
        type=float,
        default=float(os.getenv("SLEEP_SECONDS", "0")),
        help="Optional sleep between LLM calls (rate limiting).",
    )
    parser.add_argument(
        "--limit_pairs",
        type=int,
        default=None,
        help="For debugging: limit number of (node_type, property) pairs processed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.t <= 0:
        raise ValueError("--t must be > 0")

    run_pipeline(
        t=args.t,
        output_csv=args.output_csv,
        faiss_dir=args.faiss_dir,
        resume=args.resume,
        temperature=args.temperature,
        sleep_seconds=args.sleep_seconds,
        limit_pairs=args.limit_pairs,
    )


if __name__ == "__main__":
    main()
