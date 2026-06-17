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
from paths import REPO_ROOT

logger = logging.getLogger("t2c.fcav")

# ── Artifact layout (gitignored, lives under generated/) ──────────────────────
FCAV_DIR:      Path = REPO_ROOT / "generated" / "fcav"
_INDEX_PATH:   Path = FCAV_DIR / "index.faiss"
_META_PATH:    Path = FCAV_DIR / "meta.json"        # [[value, label, key], ...] aligned to index rows
_MANIFEST_PATH: Path = FCAV_DIR / "manifest.json"

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
) -> Dict[str, Any]:
    """
    Build + persist the FCAV VectorDB for the connected graph. Returns the
    manifest dict. Embedding backend is read from ``vector_config``.
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

    index = faiss.IndexFlatIP(dim)   # cosine via normalized inner product
    index.add(vecs)

    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / "index.faiss"))
    (out_dir / "meta.json").write_text(
        json.dumps(triples, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "count":                len(triples),
        "dimensions":           dim,
        "embedding_backend":    vc.EMBEDDING_BACKEND,
        "embedding_model":      vc.EMBEDDING_MODEL_NAME,
        "include_descriptions": include_descriptions,
        "database":             database,
    }
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
    """Load + cache (index, meta, manifest). Raises if the index is absent."""
    key = str(out_dir)
    if key in _CACHE:
        return _CACHE[key]
    import faiss
    if not (out_dir / "index.faiss").is_file():
        raise FileNotFoundError(
            f"FCAV index not found at {out_dir}. Run `python setup_fcav.py` first."
        )
    index = faiss.read_index(str(out_dir / "index.faiss"))
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


def get_fcav_entities(query: str, top_k: int = 15, verbose: bool = False) -> str:
    """
    Embed *query*, search the FCAV VectorDB, and return the top-*top_k*
    ``(value, label, key)`` hits as a JSON string ``{"Label.key": [values]}``
    — the same shape the Cypher prompt's ``{relevant_entities}`` slot expects.
    """
    # FCAV_TOP_K env overrides the caller's top_k (e.g. FCAV_TOP_K=1 to inject
    # only the single best-matching value), so the retrieval depth can be swept
    # without touching the shared NER top_k.
    top_k = int(os.environ.get("FCAV_TOP_K", top_k))
    index, meta, _ = _load()
    qv = np.asarray([embed_query(query)], dtype="float32")
    qv = _normalize(qv)
    _, idxs = index.search(qv, top_k)

    grouped: "defaultdict[str, list]" = defaultdict(list)
    for i in idxs[0]:
        if i < 0 or i >= len(meta):
            continue
        value, label, key = meta[i]
        k = f"{label}.{key}"
        if value not in grouped[k]:
            grouped[k].append(value)

    # Collapse 1-element lists to scalars (matches the NER output convention).
    out: Dict[str, Any] = {
        k: (vs[0] if len(vs) == 1 else vs) for k, vs in grouped.items()
    }
    if verbose:
        print(f"\n── FCAV retrieval (top_k={top_k}) for {query!r} ──")
        print(f"  {out}")
    return json.dumps(out, ensure_ascii=False)
