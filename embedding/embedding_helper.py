# -*- coding: utf-8 -*-
"""
embedding_helper.py
===================
Write-path utilities for the hybrid retrieval layer:

    • Backend-agnostic embedding (`embed_texts`, `embed_query`)
    • Schema introspection-driven discovery (`discover_embeddable_properties`)
    • Idempotent corpus backfill (`backfill_embeddings`)
    • Vector index creation (`create_vector_indexes`)
    • Startup safety probes (`verify_backend`, `check_neo4j_version`)

Generic across labels and properties. NEVER hardcode a label or property
name here — all schema-derived values come from
`vector_config.EMBEDDABLE_PROPERTIES` (populated by auto-discovery from
`schema_meta.json`).

V1 scope: nodes only. Relationship and v2 paths are clearly marked.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import vector_config as vc
from paths import SCHEMA_META


# Stage-2 explicit-name whitelist used by :func:`is_embeddable`.  A
# property whose lowercased name CONTAINS any of these substrings is
# embedded UNCONDITIONALLY (no length check).  Historically this lived
# in ``vector_config.DISCOVERY_PROPERTY_NAME_HINTS`` but the helper now
# carries its own fallback so it stays robust when ``vector_config.py``
# is mid-rewrite (e.g. between ``setup_project.py`` runs that strip the
# auto-discovery rules block).  Callers may still override by defining
# the constant in ``vector_config`` — :func:`_discovery_name_hints`
# prefers ``vector_config`` when present.
_DEFAULT_DISCOVERY_NAME_HINTS: List[str] = [
    "title", "name", "description", "summary", "content",
    "body", "text", "label", "caption", "headline", "abstract",
]


def _discovery_name_hints() -> List[str]:
    """Return Stage-2 substring hints — vector_config override OR default."""
    return list(getattr(vc, "DISCOVERY_PROPERTY_NAME_HINTS",
                        _DEFAULT_DISCOVERY_NAME_HINTS))

logger = logging.getLogger("embedding_helper")
if not logger.handlers:
    # Default to INFO; callers can silence via logger.setLevel(logging.WARNING).
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[embedding_helper] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ──────────────────────────────────────────────────────────────────────────────
# Backend dispatch — module-level singletons cache the model/client.
# ──────────────────────────────────────────────────────────────────────────────

_openai_client = None          # openai.OpenAI instance
_st_model      = None          # sentence_transformers.SentenceTransformer instance
_st_device     = None


def reset_caches() -> None:
    """
    Clear cached backend instances (OpenAI client, ST model, device).

    MUST be called after `vector_config.EMBEDDING_BACKEND` (or the model
    inside `EMBEDDING_MODELS`) is changed at runtime — e.g. by reloading
    `vector_config` between ablation runs. Without this, a stale
    `_openai_client` built with a previous `OPENAI_BASE_URL`, or an
    `_st_model` of a different dimensionality, is silently reused and
    `verify_backend()` fails in confusing ways.

    Cheap and idempotent. Safe to call any number of times.
    """
    global _openai_client, _st_model, _st_device, _openai_retry_decorator
    _openai_client = None
    _st_model = None
    _st_device = None
    # Tenacity decorator captured a snapshot of the openai exception classes
    # at build time — also rebuilt next call.
    _openai_retry_decorator = None


def _get_openai_client():
    """Lazy-build and cache the OpenAI embeddings client."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        kwargs: Dict[str, Any] = {"api_key": os.getenv("OPENAI_API_KEY")}
        org = os.getenv("OPENAI_ORG_ID")
        if org:
            kwargs["organization"] = org
        base = os.getenv("OPENAI_BASE_URL")
        if base:
            kwargs["base_url"] = base
        _openai_client = OpenAI(**kwargs)
    return _openai_client


def _get_st_model():
    """Lazy-build and cache the sentence-transformers model."""
    global _st_model, _st_device
    if _st_model is not None:
        return _st_model

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ImportError(
            "sentence-transformers is not installed. Install with:\n"
            "    pip install sentence-transformers torch\n"
            "or set EMBEDDING_BACKEND='openai' in vector_config.py."
        ) from exc

    cfg = vc.EMBEDDING_MODELS["sentence_transformers"]
    device = cfg.get("device")
    if device is None:
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        except ImportError:
            device = "cpu"
    _st_device = device

    # First-time load downloads the model weights (~400MB for BGE base).
    # Without these logs the process looks hung for 30-90s on a fresh box.
    logger.info(
        "loading sentence-transformers model %r on device=%s "
        "(first-time runs may download ~hundreds of MB) ...",
        cfg["model_name"], device,
    )
    t0 = time.time()
    _st_model = SentenceTransformer(cfg["model_name"], device=device)
    logger.info(
        "sentence-transformers model %r loaded on %s in %.2fs",
        cfg["model_name"], device, time.time() - t0,
    )
    return _st_model


def _st_active_device() -> str:
    """Return the device the ST model is (or will be) loaded on."""
    if _st_device is not None:
        return _st_device
    # Trigger lazy load to populate _st_device
    _get_st_model()
    return _st_device or "cpu"


# ──────────────────────────────────────────────────────────────────────────────
# Embedding API
# ──────────────────────────────────────────────────────────────────────────────

def _build_openai_retry():
    """
    Build the tenacity decorator for OpenAI embeddings calls.

    Built lazily so importing this module without the openai package
    installed does not crash.

    RETRY POLICY — whitelist of truly transient errors only.

    The OpenAI SDK's class hierarchy is:

        APIError  (root)
        ├── APIConnectionError      ← transient (network)
        │   └── APITimeoutError     ← transient (network)
        ├── APIStatusError          ← HTTP status errors
        │   ├── BadRequestError              (400) — PERMANENT
        │   ├── AuthenticationError          (401) — PERMANENT
        │   ├── PermissionDeniedError        (403) — PERMANENT
        │   ├── NotFoundError                (404) — PERMANENT
        │   ├── ConflictError                (409) — PERMANENT
        │   ├── UnprocessableEntityError     (422) — PERMANENT
        │   ├── RateLimitError               (429) — TRANSIENT
        │   └── InternalServerError          (5xx) — TRANSIENT

    Retrying APIError or APIStatusError as a whole would happily burn 5
    attempts on a wrong API key. So we list ONLY the four transient
    leaves below — anything else (AuthenticationError, BadRequestError,
    etc.) raises on the first attempt.

    Note: InternalServerError is imported defensively because some older
    `openai` SDK versions did not expose it; we fall back to skipping
    that branch rather than crashing the import.
    """
    from openai import (
        APIConnectionError,
        APITimeoutError,
        RateLimitError,
    )
    transient = [RateLimitError, APIConnectionError, APITimeoutError]
    try:
        from openai import InternalServerError  # type: ignore
        transient.append(InternalServerError)
    except ImportError:
        # Older openai SDK — InternalServerError 5xx will be raised as the
        # generic APIStatusError parent and will simply not be retried.
        # That's a safer default than retrying every APIStatusError.
        pass

    return retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        retry=retry_if_exception_type(tuple(transient)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


_openai_retry_decorator = None


def _embed_openai_chunk(chunk: List[str]) -> List[List[float]]:
    """One retried OpenAI embeddings request. Decorator is built once and cached."""
    global _openai_retry_decorator
    if _openai_retry_decorator is None:
        _openai_retry_decorator = _build_openai_retry()

    @_openai_retry_decorator
    def _call() -> List[List[float]]:
        client = _get_openai_client()
        resp = client.embeddings.create(
            model=vc.EMBEDDING_MODEL_NAME,
            input=chunk,
        )
        return [d.embedding for d in resp.data]

    return _call()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Batch-embed a list of corpus strings. Routes to the active backend.

    Corpus path — does NOT apply any query-side instruction prefix.

    OpenAI calls retry transient errors with exponential backoff
    (5 attempts, 1s..60s). sentence-transformers runs locally and needs
    no retry layer.
    """
    if not texts:
        return []

    backend = vc.EMBEDDING_BACKEND

    if backend == "openai":
        out: List[List[float]] = []
        # OpenAI supports up to ~2048 inputs per request, but we keep the
        # batch tied to vector_config.EMBEDDING_BATCH_SIZE so cost / log
        # cadence is the operator-controlled knob.
        bs = vc.EMBEDDING_BATCH_SIZE
        for i in range(0, len(texts), bs):
            chunk = texts[i:i + bs]
            out.extend(_embed_openai_chunk(chunk))
        return out

    if backend == "sentence_transformers":
        model = _get_st_model()
        cfg   = vc.EMBEDDING_MODELS["sentence_transformers"]
        vecs  = model.encode(
            texts,
            batch_size=vc.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=cfg.get("normalize", True),
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vecs]

    raise ValueError(f"Unknown EMBEDDING_BACKEND: {backend!r}")


def embed_query(text: str) -> List[float]:
    """
    Embed a single query string. For asymmetric ST models (BGE/E5) this
    applies the configured `query_instruction` prefix; the OpenAI path
    is symmetric and applies nothing.
    """
    backend = vc.EMBEDDING_BACKEND
    if backend == "sentence_transformers":
        cfg = vc.EMBEDDING_MODELS["sentence_transformers"]
        prefix = cfg.get("query_instruction", "") or ""
        return embed_texts([prefix + text])[0]
    return embed_texts([text])[0]


# ──────────────────────────────────────────────────────────────────────────────
# Startup safety probes
# ──────────────────────────────────────────────────────────────────────────────

def verify_backend() -> None:
    """
    Embed "hello world" and assert the returned vector length matches
    `EMBEDDING_DIMENSIONS`. Fail fast on mismatch — this is the most
    common bug when swapping models.
    """
    vec = embed_query("hello world")
    if len(vec) != vc.EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"Embedding dimension mismatch: backend={vc.EMBEDDING_BACKEND!r} "
            f"model={vc.EMBEDDING_MODEL_NAME!r} returned dim={len(vec)}, "
            f"but vector_config.EMBEDDING_DIMENSIONS={vc.EMBEDDING_DIMENSIONS}. "
            f"Update EMBEDDING_MODELS[{vc.EMBEDDING_BACKEND!r}]['dimensions'] "
            f"to match the model, then re-run setup with --reset-embeddings."
        )
    logger.info(
        f"verify_backend OK  backend={vc.EMBEDDING_BACKEND} "
        f"model={vc.EMBEDDING_MODEL_NAME} dim={len(vec)}"
    )


_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def _parse_version(s: str) -> Tuple[int, int, int]:
    m = _VERSION_RE.search(s)
    if not m:
        raise RuntimeError(f"Could not parse Neo4j version from {s!r}")
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    return major, minor, patch


def check_neo4j_version(driver, database: Optional[str] = None) -> Tuple[int, int, int]:
    """
    Query `dbms.components()`, parse the version, and fail fast if < 5.18.
    Returns the parsed (major, minor, patch).
    """
    required = (5, 18, 0)
    sess_kwargs = {"database": database} if database else {}
    with driver.session(**sess_kwargs) as session:
        rows = list(session.run(
            "CALL dbms.components() YIELD name, versions, edition "
            "WHERE name = 'Neo4j Kernel' RETURN versions[0] AS version"
        ))
    if not rows:
        raise RuntimeError("dbms.components() returned no Neo4j Kernel entry.")
    version_str = rows[0]["version"]
    actual = _parse_version(version_str)
    if actual < required:
        raise RuntimeError(
            f"Neo4j {version_str} is too old for native vector indexes. "
            f"Required: >= 5.18.0. Upgrade your Neo4j deployment, or run "
            f"setup_project.py with --skip-embeddings to stay on the legacy "
            f"fuzzy-only path."
        )
    logger.info(f"Neo4j version OK: {version_str} (>= 5.18 required)")
    return actual


# ──────────────────────────────────────────────────────────────────────────────
# Auto-discovery
# ──────────────────────────────────────────────────────────────────────────────

def is_embeddable(prop_meta: Dict[str, Any]) -> bool:
    """
    Decide whether to embed a property's distinct values.

    Three-stage logic:
      1. Hard exclusions — opaque IDs, numeric/temporal/boolean/list types.
         These are never embeddable regardless of other signals.
      2. Explicit signals — name matches a curated hint OR data_type is
         a known text type. These are trusted UNCONDITIONALLY. No length
         check, because a curator already labeled this as a text field;
         short values (e.g. one-word names) are still semantically
         meaningful for retrieval.
      3. Length fallback — only for properties whose name gives no signal
         AND whose data_type is not in the explicit text set. Captures
         domain-specific text fields (e.g. "synopsis", "abstract") on
         databases we haven't seen yet.

    DO NOT change stage 2 to require length. Doing so silently filters
    out short-but-meaningful canonical fields like Movie.title and
    Person.name, which is exactly what value linking needs to embed.

    `prop_meta` is a dict of:
        {
          "property":   "<prop name>",
          "data_type":  "<from schema_meta>",   # may be missing
          "avg_length": <float>,                 # may be missing -> 0.0
        }
    """
    prop_lower = (prop_meta.get("property") or "").lower().strip()
    data_type  = (prop_meta.get("data_type") or "").lower().strip()
    avg_len    = float(prop_meta.get("avg_length") or 0.0)

    # ── Stage 1: hard exclusions ──────────────────────────────────────────
    if not prop_lower:
        return False
    if prop_lower in vc.DISCOVERY_PROPERTY_BLACKLIST:
        return False
    if data_type in vc.DISCOVERY_NON_TEXT_DATA_TYPES:
        return False

    # ── Stage 2: explicit signals (UNCONDITIONAL, no length check) ────────
    if any(h in prop_lower for h in _discovery_name_hints()):
        return True
    if data_type in vc.DISCOVERY_TEXT_DATA_TYPES:
        return True

    # ── Stage 3: length fallback ──────────────────────────────────────────
    return avg_len >= vc.DISCOVERY_MIN_AVG_LENGTH


def discover_embeddable_properties(
    schema_meta_path: Union[str, Path] = SCHEMA_META,
    *,
    driver=None,
    database: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Read `schema_meta.json` and return the list of (label, property) entries
    that pass `is_embeddable`.

    If `driver` is supplied, augments the metadata with sample-derived
    `avg_length` per property (used only by Stage 3 fallback). Without
    a driver, properties relying on length fallback are skipped — which
    is fine for v1 because the test database hits Stage 2 for everything
    that should be embedded.
    """
    try:
        with open(schema_meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not load schema_meta.json from {schema_meta_path!r}: {exc}. "
            f"Run setup_project.py through Step 4 first."
        ) from exc

    nodes = meta.get("nodes", {}) or {}
    avg_lengths: Dict[Tuple[str, str], float] = {}
    if driver is not None:
        avg_lengths = sample_avg_lengths(driver, database, list(nodes.keys()))

    discovered: List[Dict[str, str]] = []
    for label, label_meta in nodes.items():
        props_meta = (label_meta or {}).get("properties", {}) or {}
        for prop, pm in props_meta.items():
            prop_meta = {
                "property":   prop,
                "data_type":  (pm or {}).get("data_type"),
                "avg_length": avg_lengths.get((label, prop), 0.0),
            }
            if is_embeddable(prop_meta):
                discovered.append({
                    "entity_type":        "node",
                    "label":              label,
                    "property":           prop,
                    "embedding_property": f"{prop}_embedding",
                })

    return discovered


def sample_avg_lengths(
    driver,
    database: Optional[str],
    labels: Iterable[str],
) -> Dict[Tuple[str, str], float]:
    """
    Return mean string length per (label, property) sampled from the live DB.

    Uses the native `valueType()` function (Neo4j 5.13+) to filter to STRING
    values only — non-string values are EXCLUDED from the average instead of
    being toString()'d to their numeric/bool representation, which would
    pollute the length signal that Stage 3 of `is_embeddable` reads.

    No APOC dependency.

    Public API: also consumed by `setup_project.step_backfill_embeddings`'s
    cost estimator (replaces the previous hand-picked 30-char constant).
    """
    out: Dict[Tuple[str, str], float] = {}
    sess_kwargs = {"database": database} if database else {}
    with driver.session(**sess_kwargs) as session:
        for label in labels:
            safe = label.replace("`", "``")
            try:
                rows = list(session.run(
                    f"MATCH (n:`{safe}`) WITH n LIMIT 200 "
                    f"UNWIND keys(n) AS k "
                    f"WITH k, n[k] AS v "
                    f"WITH k, "
                    f"     CASE WHEN valueType(v) STARTS WITH 'STRING' "
                    f"          THEN size(v) ELSE NULL END AS slen "
                    f"WHERE slen IS NOT NULL "
                    f"RETURN k AS prop, avg(slen) AS avg_len"
                ))
            except Exception as e:
                # valueType() requires Neo4j 5.13+. Step 2's version probe
                # already enforces >= 5.18, but we log and skip rather than
                # crash the discovery prompt if a deployment slips through.
                logger.warning(
                    "avg-length sampling unavailable on label %r: %s. "
                    "Stage-3 length fallback will see avg_length=0 for this label.",
                    label, e,
                )
                rows = []
            for r in rows:
                out[(label, r["prop"])] = float(r["avg_len"] or 0.0)
    return out


# Backward-compat alias — the function used to be private (single-leading-
# underscore). It's now part of the public API (consumed by setup_project)
# so we keep the old name pointing at the new symbol for any in-tree callers
# we might have missed.
_sample_avg_lengths = sample_avg_lengths


# ──────────────────────────────────────────────────────────────────────────────
# Index name helper — single source of truth used by index creation AND
# the query-time tool code, so they always agree.
# ──────────────────────────────────────────────────────────────────────────────

def index_name_for(label: str, prop: str) -> str:
    """Deterministic vector-index name for a (label, property) pair."""
    return f"{vc.VECTOR_INDEX_PREFIX}_{label.lower()}_{prop.lower()}"


def value_range_index_name_for(label: str, prop: str) -> str:
    """Deterministic name for the RANGE index backing backfill value lookups."""
    return f"t2c_valrange_{label.lower()}_{prop.lower()}"


def ensure_value_range_indexes(
    driver,
    database: Optional[str],
    spec: List[Dict[str, str]],
) -> List[str]:
    """
    Create a RANGE index on every embeddable ``(label, property)`` before
    backfill, returning the index names ensured.

    Why this matters: the backfill write matches nodes by VALUE
    (``MATCH (n:Label) WHERE n.prop = $value``). Without a range index on
    ``prop`` that equality is an *all-nodes scan per value* — on a ~450k-node
    graph that is ~230 ms/value (measured), i.e. tens of hours for a large
    graph like ``movie``. A range index turns each lookup into a
    ``NodeIndexSeek`` (~2 dbHits), making the backfill embedding-API-bound
    instead of Neo4j-scan-bound. The ``.name`` properties in particular carry
    only a FULLTEXT index (for BM25 fuzzy), which an equality predicate cannot
    use — so this step is what makes hybrid setup feasible on big graphs.

    Idempotent (``IF NOT EXISTS``); blocks until the indexes are online.
    """
    sess_kwargs = {"database": database} if database else {}
    names: List[str] = []
    with driver.session(**sess_kwargs) as session:
        for entry in spec:
            if entry.get("entity_type", "node") != "node":
                continue  # relationship-property embedding is deferred (v2)
            label = entry["label"]
            prop  = entry["property"]
            iname = value_range_index_name_for(label, prop)
            safe_label = label.replace("`", "``")
            safe_prop  = prop.replace("`", "``")
            session.run(
                f"CREATE RANGE INDEX `{iname}` IF NOT EXISTS "
                f"FOR (n:`{safe_label}`) ON (n.`{safe_prop}`)"
            ).consume()
            names.append(iname)
        if names:
            session.run("CALL db.awaitIndexes(600)").consume()
    return names


# ──────────────────────────────────────────────────────────────────────────────
# Backfill
# ──────────────────────────────────────────────────────────────────────────────

def backfill_embeddings(
    driver,
    database: Optional[str],
    spec: List[Dict[str, str]],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    For every entry in `spec`, embed all distinct property values that
    do not yet have an embedding, and write the embedding to ALL nodes
    holding each value.

    Returns per-(label, property) summary stats:
        {(label, prop): {"distinct_values": N, "embedded": M, "skipped": K,
                         "elapsed_s": float}}

    Idempotent: nodes with `<embedding_property>` already set are skipped.
    """
    summary: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for entry in spec:
        et = entry.get("entity_type", "node")
        if et == "relationship":
            # TODO(v2): relationship-property embedding. Defer until target
            # database with rel-property semantics is finalized.
            raise NotImplementedError(
                "Relationship embedding not implemented in v1. "
                "Re-evaluated when target database is finalized. See TODO."
            )
        if et != "node":
            raise ValueError(f"Unknown entity_type {et!r} in EMBEDDABLE_PROPERTIES")

        label    = entry["label"]
        prop     = entry["property"]
        emb_prop = entry["embedding_property"]
        stats    = _backfill_node_property(driver, database, label, prop, emb_prop)
        summary[(label, prop)] = stats

    return summary


def _stream_distinct_unembedded_values(
    driver,
    sess_kwargs: Dict[str, Any],
    safe_label: str,
    safe_prop: str,
    safe_emb: str,
    page_size: int,
) -> Iterator[Any]:
    """
    Yield distinct values of `<label>.<prop>` where at least one node carrying
    that value still has `<emb_prop>` IS NULL.

    Implementation:
      • Per-page query uses DISTINCT (NEVER collect(n)) so memory is bounded
        by the number of distinct values in one page, not the number of nodes
        carrying them.
      • Each page is fetched in its own session/transaction, leaving the
        write-side session free to issue UNWIND writes between pages.
      • Stable ordering is REQUIRED for correct SKIP semantics — `ORDER BY value`.

    Caveat: SKIP on a DISTINCT plan re-evaluates the distinct set per page.
    Acceptable for the v1 paper-scale databases; v2 can switch to a cursor
    bookmark (last-seen value pagination) if a deployment hits this.
    """
    cypher = (
        f"MATCH (n:`{safe_label}`) "
        f"WHERE n.`{safe_prop}` IS NOT NULL AND n.`{safe_emb}` IS NULL "
        f"RETURN DISTINCT n.`{safe_prop}` AS value "
        f"ORDER BY value "
        f"SKIP $skip LIMIT $limit"
    )
    skip = 0
    while True:
        with driver.session(**sess_kwargs) as session:
            rows = list(session.run(cypher, skip=skip, limit=page_size))
        if not rows:
            return
        for r in rows:
            yield r["value"]
        if len(rows) < page_size:
            return
        skip += page_size


def _count_distinct_unembedded(
    driver,
    sess_kwargs: Dict[str, Any],
    safe_label: str,
    safe_prop: str,
    safe_emb: str,
) -> int:
    """One scan to learn the total so the per-batch logger has an honest ETA."""
    cypher = (
        f"MATCH (n:`{safe_label}`) "
        f"WHERE n.`{safe_prop}` IS NOT NULL AND n.`{safe_emb}` IS NULL "
        f"RETURN count(DISTINCT n.`{safe_prop}`) AS n"
    )
    with driver.session(**sess_kwargs) as session:
        row = session.run(cypher).single()
    return int(row["n"]) if row else 0


def _backfill_node_property(
    driver,
    database: Optional[str],
    label: str,
    prop: str,
    emb_prop: str,
) -> Dict[str, Any]:
    """
    Embed and write a single (label, property)'s distinct un-embedded values.

    Read path:  paginated DISTINCT (no collect(n) — see #1 in review).
    Embed path: chunks of EMBEDDING_BATCH_SIZE (driven by config; OpenAI
                throughput knob).
    Write path: chunks of WRITE_BATCH_SIZE (decoupled from embed batch so
                bumping EMBEDDING_BATCH_SIZE never bloats the Neo4j tx).

    Idempotent: rows whose `<emb_prop>` is already populated are filtered
    out at the read layer, so re-running is cheap.
    """
    sess_kwargs = {"database": database} if database else {}
    safe_label  = label.replace("`", "``")
    safe_prop   = prop.replace("`", "``")
    safe_emb    = emb_prop.replace("`", "``")

    embed_batch = vc.EMBEDDING_BATCH_SIZE
    write_batch = vc.WRITE_BATCH_SIZE

    t0 = time.time()
    total = _count_distinct_unembedded(
        driver, sess_kwargs, safe_label, safe_prop, safe_emb,
    )
    if total == 0:
        elapsed = time.time() - t0
        logger.info(
            f"backfill {label}.{prop}: 0 values to embed (already up-to-date) "
            f"elapsed={elapsed:.2f}s"
        )
        return {"distinct_values": 0, "embedded": 0, "skipped_existing": 0,
                "elapsed_s": elapsed}

    embedded = 0
    buf: List[Any] = []

    def _flush(values: List[Any]) -> None:
        """Embed `values` (one OpenAI/ST call) and write in WRITE_BATCH_SIZE sub-chunks."""
        nonlocal embedded
        if not values:
            return
        # Cast every value to its string form for the embedding API. Non-string
        # values are theoretically excluded by Stage 1 of `is_embeddable`, but
        # we cast defensively here — embeddings always receive strings.
        str_values = [str(v) for v in values]
        t_b  = time.time()
        vecs = embed_texts(str_values)

        # Write in sub-chunks bounded by WRITE_BATCH_SIZE so the UNWIND
        # payload stays small even if the embed batch is large.
        for j in range(0, len(values), write_batch):
            sub_vals = values[j:j + write_batch]
            sub_vecs = vecs[j:j + write_batch]
            with driver.session(**sess_kwargs) as session:
                session.run(
                    f"UNWIND $rows AS row "
                    f"MATCH (n:`{safe_label}`) "
                    f"WHERE n.`{safe_prop}` = row.value "
                    f"  AND n.`{safe_emb}` IS NULL "
                    f"CALL db.create.setNodeVectorProperty(n, '{safe_emb}', row.vec) "
                    f"RETURN count(*) AS written",
                    rows=[{"value": v, "vec": vec}
                          for v, vec in zip(sub_vals, sub_vecs)],
                )

        embedded += len(values)
        elapsed_b = time.time() - t_b
        rate      = elapsed_b / max(1, len(values))
        eta       = max(0, total - embedded) * rate
        logger.info(
            f"backfill {label}.{prop}: {embedded}/{total} "
            f"batch={len(values)} (write_chunks={(len(values) + write_batch - 1) // write_batch}) "
            f"elapsed={elapsed_b:.2f}s eta={eta:.1f}s"
        )

    # Stream the distinct values; flush every EMBEDDING_BATCH_SIZE-sized buffer.
    for value in _stream_distinct_unembedded_values(
        driver, sess_kwargs, safe_label, safe_prop, safe_emb,
        page_size=write_batch,  # read page size = write batch size; small + bounded
    ):
        buf.append(value)
        if len(buf) >= embed_batch:
            _flush(buf)
            buf = []
    _flush(buf)

    elapsed = time.time() - t0
    return {"distinct_values": total, "embedded": embedded,
            "skipped_existing": 0, "elapsed_s": elapsed}


# ──────────────────────────────────────────────────────────────────────────────
# Vector index creation
# ──────────────────────────────────────────────────────────────────────────────

def create_vector_indexes(
    driver,
    database: Optional[str],
    spec: List[Dict[str, str]],
) -> Dict[str, str]:
    """
    Create one vector index per spec entry. Skip if it already exists.

    Returns {index_name: "created" | "exists"}.

    MUST be called AFTER `backfill_embeddings` — bulk HNSW build on a
    populated graph is much faster than incremental insertion.
    """
    sess_kwargs = {"database": database} if database else {}
    results: Dict[str, str] = {}

    with driver.session(**sess_kwargs) as session:
        existing = {r["name"] for r in session.run(
            "SHOW VECTOR INDEXES YIELD name RETURN name"
        )}

        for entry in spec:
            et = entry.get("entity_type", "node")
            if et != "node":
                # TODO(v2): relationship vector indexes.
                continue

            label  = entry["label"]
            prop   = entry["property"]
            emb    = entry["embedding_property"]
            iname  = index_name_for(label, prop)
            if iname in existing:
                logger.info(f"vector index {iname} already exists — skipping")
                results[iname] = "exists"
                continue

            safe_label = label.replace("`", "``")
            safe_emb   = emb.replace("`", "``")
            cypher = (
                f"CREATE VECTOR INDEX `{iname}` IF NOT EXISTS "
                f"FOR (n:`{safe_label}`) ON (n.`{safe_emb}`) "
                f"OPTIONS {{ indexConfig: {{ "
                f"  `vector.dimensions`: $dim, "
                f"  `vector.similarity_function`: $sim "
                f"}} }}"
            )
            session.run(cypher, dim=vc.EMBEDDING_DIMENSIONS, sim=vc.VECTOR_SIMILARITY)
            logger.info(
                f"vector index {iname} created  "
                f"(dim={vc.EMBEDDING_DIMENSIONS}, sim={vc.VECTOR_SIMILARITY})"
            )
            results[iname] = "created"

    return results


def drop_vector_indexes(
    driver,
    database: Optional[str],
    spec: List[Dict[str, str]],
) -> List[str]:
    """Drop the vector indexes for `spec` entries (used by --reset-embeddings)."""
    sess_kwargs = {"database": database} if database else {}
    dropped: List[str] = []
    with driver.session(**sess_kwargs) as session:
        for entry in spec:
            if entry.get("entity_type", "node") != "node":
                continue
            iname = index_name_for(entry["label"], entry["property"])
            try:
                session.run(f"DROP INDEX `{iname}` IF EXISTS")
                dropped.append(iname)
            except Exception as e:
                logger.warning(f"failed to drop index {iname}: {e}")
    return dropped


def null_embedding_properties(
    driver,
    database: Optional[str],
    spec: List[Dict[str, str]],
) -> int:
    """
    Remove the embedding property from all nodes (used by --reset-embeddings).

    Uses `CALL { ... } IN TRANSACTIONS OF N ROWS` so a reset on a database
    with millions of nodes does not hit Neo4j's single-transaction limits.
    The chunk size comes from `vector_config.RESET_TX_BATCH_SIZE`.

    `CALL ... IN TRANSACTIONS` requires implicit-transaction context — i.e.
    `session.run()` directly, not inside `session.execute_write(...)`. That
    matches what we're doing here.
    """
    sess_kwargs = {"database": database} if database else {}
    total = 0
    chunk = int(vc.RESET_TX_BATCH_SIZE)

    for entry in spec:
        if entry.get("entity_type", "node") != "node":
            continue
        label    = entry["label"]
        emb_prop = entry["embedding_property"]
        safe_label = label.replace("`", "``")
        safe_emb   = emb_prop.replace("`", "``")

        # First count what we'll remove — a single small read tx.
        with driver.session(**sess_kwargs) as session:
            res = session.run(
                f"MATCH (n:`{safe_label}`) WHERE n.`{safe_emb}` IS NOT NULL "
                f"RETURN count(*) AS n"
            ).single()
            n = int(res["n"]) if res else 0
        if n == 0:
            continue

        # Then remove in chunked implicit transactions.
        with driver.session(**sess_kwargs) as session:
            session.run(
                f"MATCH (n:`{safe_label}`) WHERE n.`{safe_emb}` IS NOT NULL "
                f"CALL {{ WITH n REMOVE n.`{safe_emb}` }} "
                f"IN TRANSACTIONS OF {chunk} ROWS"
            ).consume()

        logger.info(
            f"null_embedding_properties: cleared {n} {label}.{emb_prop} "
            f"in chunks of {chunk}"
        )
        total += n
    return total


# ──────────────────────────────────────────────────────────────────────────────
# Cost / time estimation (used by setup_project.py step 6)
# ──────────────────────────────────────────────────────────────────────────────

def estimate_distinct_values(
    driver,
    database: Optional[str],
    spec: List[Dict[str, str]],
) -> Dict[Tuple[str, str], int]:
    """Return distinct-value counts per (label, property)."""
    sess_kwargs = {"database": database} if database else {}
    out: Dict[Tuple[str, str], int] = {}
    with driver.session(**sess_kwargs) as session:
        for entry in spec:
            if entry.get("entity_type", "node") != "node":
                continue
            label = entry["label"]
            prop  = entry["property"]
            safe_label = label.replace("`", "``")
            safe_prop  = prop.replace("`", "``")
            row = session.run(
                f"MATCH (n:`{safe_label}`) WHERE n.`{safe_prop}` IS NOT NULL "
                f"RETURN count(DISTINCT n.`{safe_prop}`) AS n"
            ).single()
            out[(label, prop)] = int(row["n"]) if row else 0
    return out
