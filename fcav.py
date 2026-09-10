#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fcav.py
=======
FCAV baseline — Full-query Content-Aware Value retrieval.

Instead of the per-(label, property) tool-based NER agent, FCAV:

  1.  (setup, ``setup_fcav.py``) extracts real property **values** + their
      ``(label, key)`` from the graph for the identifying / name-like string
      properties, embeds each value, and stores them in a local FAISS
      VectorDB (``generated/fcav/``).
  2.  (query, :func:`get_fcav_entities`) embeds the **whole user question**,
      runs one similarity search over that VectorDB, and returns the top-k
      ``(value, label, key)`` hits formatted as the same ``{"Label.key":
      [values]}`` entity dict the Cypher prompt already consumes.

So FCAV is a drop-in alternative to the NER step: everything downstream
(Cypher prompt → GraphCypherQAChain → execution → scoring → record format)
is identical to the ``full`` / ``node_only`` / ``no_ner`` modes, which means
its result tables come out in exactly the same shape.

The embedding backend is whatever ``vector_config`` is set to (default
``text-embedding-3-small``); ``setup_fcav.py`` records it in the manifest and
:func:`get_fcav_entities` embeds the query with the same backend.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import vector_config as vc
from embedding.embedding_helper import embed_texts, embed_query
from eval.artifact_identity import (
    IDENTITY_KEY,
    current_pair,
    make_identity,
    verify_dir,
)
from paths import REPO_ROOT

logger = logging.getLogger("t2c.fcav")

# ── Artifact layout (gitignored, lives under generated/) ──────────────────────
FCAV_DIR:      Path = REPO_ROOT / "generated" / "fcav"
_INDEX_PATH:   Path = FCAV_DIR / "index.faiss"
_META_PATH:    Path = FCAV_DIR / "meta.json"        # [[value, label, key], ...] aligned to index rows
_MANIFEST_PATH: Path = FCAV_DIR / "manifest.json"

# Index type: exact (IndexFlatIP) up to FCAV_EXACT_MAX values, then approximate
# HNSW (high recall, fast query) for graphs too large for exact retrieval.
FCAV_EXACT_MAX            = int(os.getenv("FCAV_EXACT_MAX", "1000000"))
FCAV_HNSW_M               = 32
FCAV_HNSW_EF_CONSTRUCTION = 200
FCAV_HNSW_EF_SEARCH       = 64

# Default value-selection policy: keep identifying / name-like string
# properties (the values a user actually mentions), drop free-text
# descriptions and structured identifiers. Mirrors the cost/coverage
# trade-off discussed in docs — descriptions are long and never used as a
# WHERE-clause value, so they are excluded unless explicitly requested.
_NAME_LIKE_EXACT = {"name", "title", "aliases", "alias", "label", "place_of_birth"}
_SKIP_SUBSTR     = ("embedding", "vector", "eid", "uuid", "url", "uri")


def _is_name_like(prop: str) -> bool:
    p = prop.lower()
    return p in _NAME_LIKE_EXACT or p.endswith("name") or p.endswith("title")


def _is_skippable(prop: str) -> bool:
    p = prop.lower()
    return p == "id" or any(s in p for s in _SKIP_SUBSTR)


# ──────────────────────────────────────────────────────────────────────────────
# Setup — extract values, embed, build the FAISS VectorDB
# ──────────────────────────────────────────────────────────────────────────────

def extract_value_triples(
    driver,
    database: str,
    *,
    include_descriptions: bool = False,
) -> List[Tuple[str, str, str]]:
    """
    Return distinct ``(value, label, key)`` triples for the graph's
    identifying string properties. ``value`` is the canonical DB string.

    By default only name-like properties are kept (see module docstring);
    pass ``include_descriptions=True`` to also embed ``*description*`` /
    every string property (much larger index).
    """
    triples: List[Tuple[str, str, str]] = []
    with driver.session(database=database) as s:
        schema = list(s.run(
            "CALL db.schema.nodeTypeProperties() "
            "YIELD nodeLabels, propertyName, propertyTypes "
            "RETURN nodeLabels, propertyName, propertyTypes"
        ))
        pairs: List[Tuple[str, str, bool]] = []   # (label, prop, is_list)
        for r in schema:
            pn = r["propertyName"]
            pts = r["propertyTypes"] or []
            if not pn or not any("String" in t for t in pts):
                continue
            if _is_skippable(pn):
                continue
            if not include_descriptions and not _is_name_like(pn):
                continue
            is_list = any(("LIST" in t.upper()) or ("ARRAY" in t.upper()) for t in pts)
            for lab in (r["nodeLabels"] or []):
                pairs.append((lab, pn, is_list))

        for lab, pn, is_list in pairs:
            # StringArray properties (e.g. aliases) must be UNWOUND to one
            # value per row; scalar strings are read directly.
            if is_list:
                q = (f"MATCH (n:`{lab}`) WHERE n.`{pn}` IS NOT NULL "
                     f"UNWIND n.`{pn}` AS v RETURN DISTINCT toString(v) AS v")
            else:
                q = (f"MATCH (n:`{lab}`) WHERE n.`{pn}` IS NOT NULL "
                     f"RETURN DISTINCT toString(n.`{pn}`) AS v")
            try:
                for row in s.run(q):
                    v = (row["v"] or "").strip()
                    if v:
                        triples.append((v, lab, pn))
            except Exception as exc:  # noqa: BLE001
                logger.warning("FCAV extract skipped %s.%s: %s", lab, pn, exc)
    return triples


def _normalize(mat: np.ndarray) -> np.ndarray:
    """L2-normalize rows so an inner-product index gives cosine similarity."""
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def build_fcav_index(
    driver,
    database: str,
    *,
    include_descriptions: bool = False,
    out_dir: Path = FCAV_DIR,
    dataset: Optional[str] = None,
    graph: Optional[str] = None,
    uri: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build + persist the FCAV VectorDB for the connected graph. Returns the
    manifest dict. Embedding backend is read from ``vector_config``.

    Pass ``dataset``/``graph`` (and ideally ``uri``, the bolt URI actually
    connected to) so the manifest carries an identity stamp — archive and
    load boundaries verify it and refuse a foreign-graph index (see
    :mod:`eval.artifact_identity`). Building without an identity is allowed
    only for ad-hoc experiments; such an index cannot be archived or served
    during an eval run.
    """
    import faiss  # local import: heavy native dep, only needed at build time

    triples = extract_value_triples(
        driver, database, include_descriptions=include_descriptions
    )
    if not triples:
        raise RuntimeError(
            "FCAV: no value triples extracted — check the graph has string "
            "properties and the connection targets the right database."
        )
    values = [t[0] for t in triples]
    logger.info("FCAV: embedding %d distinct values (backend=%s, model=%s) ...",
                len(values), vc.EMBEDDING_BACKEND, vc.EMBEDDING_MODEL_NAME)

    vecs = np.asarray(embed_texts(values), dtype="float32")
    if vecs.ndim != 2 or vecs.shape[0] != len(values):
        raise RuntimeError(f"FCAV: embedding shape mismatch {vecs.shape} vs {len(values)} values")
    dim = vecs.shape[1]
    vecs = _normalize(vecs)

    # Exact (IndexFlatIP) search is O(N) per query and stores full vectors; past
    # FCAV_EXACT_MAX values that becomes impractical, so fall back to an
    # approximate HNSW index (high recall, O(log N) query). Both use normalized
    # inner product (= cosine).
    n = vecs.shape[0]
    if n > FCAV_EXACT_MAX:
        index = faiss.IndexHNSWFlat(dim, FCAV_HNSW_M, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = FCAV_HNSW_EF_CONSTRUCTION
        index_type = "hnsw"
        logger.info("FCAV: %d > %d values → approximate HNSW index", n, FCAV_EXACT_MAX)
    else:
        index = faiss.IndexFlatIP(dim)
        index_type = "flat"
    index.add(vecs)

    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / "index.faiss"))
    (out_dir / "meta.json").write_text(
        json.dumps(triples, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "count":                len(triples),
        "dimensions":           dim,
        "index_type":           index_type,
        "embedding_backend":    vc.EMBEDDING_BACKEND,
        "embedding_model":      vc.EMBEDDING_MODEL_NAME,
        "include_descriptions": include_descriptions,
        "database":             database,
    }
    if dataset and graph:
        manifest[IDENTITY_KEY] = make_identity(
            dataset, graph, uri=uri, database=database
        )
    else:
        logger.warning(
            "FCAV: building WITHOUT an identity stamp (dataset/graph not "
            "given) — this index cannot be archived or used in an eval run."
        )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("FCAV: wrote index (%d vectors, dim=%d) → %s", len(triples), dim, out_dir)
    return manifest


# ──────────────────────────────────────────────────────────────────────────────
# Query — load index, embed question, return top-k entity dict
# ──────────────────────────────────────────────────────────────────────────────

_CACHE: Dict[str, Any] = {}


def _load(out_dir: Path = FCAV_DIR):
    """
    Load + cache (index, meta, manifest). Raises if the index is absent, or
    if its identity stamp does not match the live ``.current_setup`` graph
    (fail closed — a mismatched index silently degrades FCAV to No-Val-Link,
    which is exactly the 2026-07 pollution incident).
    """
    # The sentinel is part of the cache key: after a swap_in within the same
    # process the stale cached index must not be served.
    expected = current_pair(REPO_ROOT)
    key = (str(out_dir), expected)
    if key in _CACHE:
        return _CACHE[key]
    import faiss
    if not (out_dir / "index.faiss").is_file():
        raise FileNotFoundError(
            f"FCAV index not found at {out_dir}. Run `python setup_fcav.py` first."
        )
    if expected is not None:
        verify_dir(out_dir, expected, context="FCAV load", missing="raise")
    else:
        logger.warning(
            "FCAV: no %s sentinel — cannot verify which graph this index "
            "belongs to. Proceeding (ad-hoc use only).", ".current_setup",
        )
    index = faiss.read_index(str(out_dir / "index.faiss"))
    # HNSW indexes need efSearch set at query time to control recall.
    if hasattr(index, "hnsw"):
        index.hnsw.efSearch = FCAV_HNSW_EF_SEARCH
    meta  = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("embedding_model") and manifest["embedding_model"] != vc.EMBEDDING_MODEL_NAME:
        logger.warning(
            "FCAV: index built with embedding model %r but vector_config is now %r — "
            "query/index embeddings will be inconsistent.",
            manifest["embedding_model"], vc.EMBEDDING_MODEL_NAME,
        )
    _CACHE[key] = (index, meta, manifest)
    return _CACHE[key]


_FCAV_GEN_PROMPT = """You are given a natural-language question and a list of candidate database \
values retrieved for it (each tagged with its `Label.property`). Decide which \
candidates correspond to the entities EXPLICITLY mentioned in the question and \
output them as a JSON object mapping "Label.property" -> canonical value.

Rules:
- Use ONLY values copied verbatim from the candidate list; never invent a value.
- Include every entity the question mentions; drop candidates not mentioned.
- One match per key -> a bare string; multiple matches for one key -> a JSON list.
- Output ONLY the JSON object, nothing else.

Question: {query}

Candidates:
{candidates}

JSON:"""


def _parse_json_obj(raw: str) -> Dict[str, Any]:
    """Best-effort parse of an LLM reply into a dict (strips code fences, then
    falls back to the first ``{...}`` span). Returns ``{}`` on failure."""
    import re as _re
    s = (raw or "").strip()
    s = _re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=_re.MULTILINE).strip()
    try:
        o = json.loads(s)
        return o if isinstance(o, dict) else {}
    except Exception:  # noqa: BLE001
        m = _re.search(r"\{.*\}", s, _re.DOTALL)
        if m:
            try:
                o = json.loads(m.group(0))
                return o if isinstance(o, dict) else {}
            except Exception:  # noqa: BLE001
                return {}
        return {}


def get_fcav_entities(query: str, top_k: int = 15, verbose: bool = False) -> str:
    """
    Standard retrieve-then-generate RAG grounding: embed *query*, retrieve the
    top-*top_k* ``(value, label, key)`` candidates from the FCAV VectorDB, then
    have an LLM read the candidate list and **generate** the entity JSON
    ``{"Label.property": value, ...}`` (selecting only candidates matching the
    entities mentioned in the question). Returns ``"{}"`` if the index is empty
    or the LLM produced nothing usable.

    This is the non-agentic counterpart to the NER ReAct agent: a single LLM
    read over retrieved context, no tool loop. (An earlier variant dumped the
    top-k candidates deterministically, skipping the LLM read; this generates,
    matching the standard RAG formulation.)
    """
    index, meta, _ = _load()
    qv = np.asarray([embed_query(query)], dtype="float32")
    qv = _normalize(qv)
    _, idxs = index.search(qv, top_k)

    cands: List[Tuple[str, str, str]] = []
    seen: set = set()
    for i in idxs[0]:
        if 0 <= i < len(meta):
            value, label, key = meta[i]
            if (value, label, key) in seen:
                continue
            seen.add((value, label, key))
            cands.append((value, label, key))
    if not cands:
        return "{}"

    cand_lines = "\n".join(f'- "{v}"  ({l}.{k})' for v, l, k in cands)
    prompt = _FCAV_GEN_PROMPT.format(query=query, candidates=cand_lines)

    from agent.agent_helper import ner_llm as _llm   # lazy import
    out: Dict[str, Any] = {}
    try:
        resp = _llm.invoke(prompt)
        raw = getattr(resp, "content", resp)
        if isinstance(raw, list):                    # some chat models return parts
            raw = " ".join(str(p) for p in raw)
        out = _parse_json_obj(str(raw))
    except Exception as exc:  # noqa: BLE001
        logger.warning("FCAV LLM-generate failed: %s", exc)
        out = {}

    if verbose:
        print(f"\n── FCAV retrieve→LLM-generate (top_k={top_k}) for {query!r} ──")
        print(f"  {len(cands)} candidates → {out}")
    return json.dumps(out, ensure_ascii=False)
