# -*- coding: utf-8 -*-
"""
tool_search.py
==============
FAISS-based tool search engine.

Provides two distinct workflows:

Workflow A — search an LLM-generated FAISS index (built by tool_gen_node_rd.py)
--------------------------------------------------------------------------------
  vs   = load_faiss_vectorstore("faiss_tools")
  hits = search_tools(vs, user_query="find movies by title", top_l=5)
  print_search_results(user_query, hits)

  Each ``ToolSearchHit`` carries: node_type, property_name, tool_name,
  description, score, and the raw tool JSON from metadata.

Workflow B — search a registry-based FAISS index (built from @tool docstrings)
--------------------------------------------------------------------------------
  from generated.generated_node_tools import *
  from generated.generated_rel_tools   import *

  registry = build_tool_registry_from_modules(
      [generated_node_tools, generated_rel_tools]
  )
  vs = get_or_build_tools_faiss(registry, faiss_dir="faiss_tools_auto")

  hits  = search_tools(vs, user_query="find movies by title", top_l=5)
  tools = hits_to_callables(hits, registry)   # → List[BaseTool]

  ``ToolSearchHit.func_name`` is populated in this workflow.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from paths import FAISS_AUTO_DIR

import httpx
from loguru import logger
from langchain_core.tools import BaseTool
from langchain_openai import OpenAIEmbeddings

try:
    from langchain_community.vectorstores import FAISS
except ImportError:                        # pragma: no cover
    from langchain.vectorstores import FAISS  # type: ignore

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Fingerprint guard
#
# Each FAISS index directory carries a sibling ``fingerprint.json`` that
# captures the live environment at build time. ``load_faiss_vectorstore()``
# verifies the fingerprint against the current environment BEFORE loading,
# and raises :class:`StaleFaissIndexError` on any mismatch.
#
# This is the safety net for the CypherBench workflow where users switch
# between graph databases (Movies → Soccer → NBA → …) and may forget to
# rerun ``setup_project.py``. Without the guard, querying a stale index
# silently returns wrong tools. With the guard, the user gets a clear,
# actionable error message and is forced to rerun setup.
#
# Design rule: the guard NEVER auto-rebuilds. Auto-rebuild would mask the
# user's mistake and re-introduce the exact bug class this guard exists to
# catch. Mismatch ⇒ raise ⇒ user reruns setup explicitly.
# ──────────────────────────────────────────────────────────────────────────────

#: Filename written next to ``index.faiss`` / ``index.pkl``.
FINGERPRINT_FILENAME = "fingerprint.json"

#: Schema version of the fingerprint file itself. Bump when fields change
#: in a backward-incompatible way (renaming, removing, semantic changes).
FINGERPRINT_SCHEMA_VERSION = 1


class StaleFaissIndexError(RuntimeError):
    """Raised when an on-disk FAISS index does not match the live env.

    Two scenarios surface this:
      • The index has no ``fingerprint.json`` — built by an older version
        of the code that predates the guard.
      • At least one fingerprint field disagrees with the live env
        (database, NEO4J_URI host, tool set hash, embedding model, etc.).

    The error message lists every mismatched field with expected vs. found
    values so the user can diagnose without re-reading the JSON manually.
    """


def _neo4j_uri_host(uri: Optional[str]) -> str:
    """
    Extract the host portion of a Neo4j URI, stripping scheme/port/credentials.

    Examples::

        'neo4j+s://user:pw@93075fe8.databases.neo4j.io:7687' → '93075fe8.databases.neo4j.io'
        'bolt://localhost:7687'                              → 'localhost'
        ''                                                   → ''
    """
    if not uri:
        return ""
    try:
        parsed = urlparse(uri)
        # urlparse on bolt://... yields netloc 'user:pw@host:port'; hostname strips all that.
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def _hash_tool_names(tool_names: List[str]) -> str:
    """
    Stable SHA-256 hex digest of a sorted list of tool ``func_name``s.

    Sorting is essential — registry iteration order is implementation-defined,
    so the hash must be order-invariant.
    """
    payload = "\n".join(sorted(tool_names)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _live_fingerprint(
    tool_names: List[str],
    *,
    ner_mode: str = "full",
) -> Dict[str, Any]:
    """
    Build the fingerprint dict from the LIVE environment + the registry.

    Reads:
      • ``NEO4J_DATABASE``    env var (defaults to ``"default"``)
      • ``NEO4J_URI``         env var (host portion only)
      • ``vector_config.EMBEDDING_MODEL_NAME``
      • ``vector_config.EMBEDDING_BACKEND``

    ``vector_config`` is imported lazily so this module stays importable
    even before the project is fully configured.
    """
    try:
        import vector_config as vc  # noqa: WPS433
        embedding_model   = getattr(vc, "EMBEDDING_MODEL_NAME", "")
        embedding_backend = getattr(vc, "EMBEDDING_BACKEND",   "")
    except Exception:
        embedding_model = ""
        embedding_backend = ""

    return {
        "database":          os.getenv("NEO4J_DATABASE") or "default",
        "neo4j_uri_host":    _neo4j_uri_host(os.getenv("NEO4J_URI")),
        "tool_names_hash":   _hash_tool_names(tool_names),
        "tool_count":        len(tool_names),
        "embedding_model":   str(embedding_model),
        "embedding_backend": str(embedding_backend),
        "ner_mode":          ner_mode,
        "built_at":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema_version":    FINGERPRINT_SCHEMA_VERSION,
    }


def _write_fingerprint(faiss_dir: Union[str, Path], fingerprint: Dict[str, Any]) -> Path:
    """
    Persist *fingerprint* to ``<faiss_dir>/fingerprint.json``.

    Uses ``Path.write_text()`` for an atomic single-write — no streaming so
    a crash during ``json.dump`` cannot leave a half-written fingerprint.
    """
    fp_path = Path(faiss_dir) / FINGERPRINT_FILENAME
    fp_path.write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")
    return fp_path


def _verify_fingerprint(
    faiss_dir: Union[str, Path],
    *,
    expected_tool_names: Optional[List[str]] = None,
    expected_ner_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare the on-disk fingerprint against the live environment.

    Parameters
    ----------
    faiss_dir
        Directory holding ``index.faiss`` + ``fingerprint.json``.
    expected_tool_names
        Optional list of ``func_name``s the live caller is about to query
        with. When provided, ``tool_names_hash`` and ``tool_count`` are
        also checked. Pass ``None`` to skip those two fields (e.g. when
        the caller does not have a registry on hand — only the database
        / model checks fire).
    expected_ner_mode
        Optional NER mode the caller intends to use. When provided, the
        fingerprint's ``ner_mode`` is checked too.

    Returns
    -------
    dict
        The on-disk fingerprint (parsed). Only returned on success.

    Raises
    ------
    StaleFaissIndexError
        When the file is missing, unreadable, or any field mismatches.
    """
    fp_path = Path(faiss_dir) / FINGERPRINT_FILENAME

    if not fp_path.is_file():
        raise StaleFaissIndexError(
            f"FAISS index at {os.fspath(faiss_dir)!r} has no fingerprint file. "
            "This index was built by an older version of the code. "
            "Rerun setup_project.py to regenerate."
        )

    try:
        on_disk = json.loads(fp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StaleFaissIndexError(
            f"FAISS fingerprint at {fp_path!r} is unreadable ({exc!r}). "
            "Rerun setup_project.py to regenerate."
        ) from exc

    live = _live_fingerprint(
        expected_tool_names if expected_tool_names is not None else [],
        ner_mode=expected_ner_mode or on_disk.get("ner_mode", "full"),
    )

    # Fields that ALWAYS get compared.
    compare_fields: List[str] = [
        "database",
        "neo4j_uri_host",
        "embedding_model",
        "embedding_backend",
        "schema_version",
    ]
    # Tool-set fields only fire when the caller passed a registry.
    if expected_tool_names is not None:
        compare_fields += ["tool_names_hash", "tool_count"]
    # NER mode only fires when the caller pinned one explicitly.
    if expected_ner_mode is not None:
        compare_fields += ["ner_mode"]

    mismatches: List[str] = []
    for field_name in compare_fields:
        expected = live.get(field_name)
        found    = on_disk.get(field_name)
        if expected != found:
            mismatches.append(f"  - {field_name}: expected {expected!r}, found {found!r}")

    if mismatches:
        raise StaleFaissIndexError(
            f"FAISS index at {os.fspath(faiss_dir)!r} is stale:\n"
            + "\n".join(mismatches)
            + "\nRerun setup_project.py against the current database."
        )

    logger.debug(
        f"[tool_search] FAISS fingerprint OK at {fp_path} "
        f"(db={on_disk.get('database')!r}, tools={on_disk.get('tool_count')}, "
        f"model={on_disk.get('embedding_model')!r})"
    )
    return on_disk


# ──────────────────────────────────────────────────────────────────────────────
# Environment helpers
# ──────────────────────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"Missing required env var: {name}. Set it in .env or system environment."
        )
    return v


# ──────────────────────────────────────────────────────────────────────────────
# Embeddings
# ──────────────────────────────────────────────────────────────────────────────

def build_embeddings() -> OpenAIEmbeddings:
    """
    Build an OpenAI embeddings client.

    Model defaults to ``text-embedding-3-small``; override with
    ``OPENAI_EMBEDDING_MODEL`` env var.

    NOTE: switching the embedding model invalidates any FAISS index built
    with a different model — even when dimensions match (3-small and ada-002
    are both 1536-dim, but live in different vector spaces).  Rebuild the
    index after changing this default::

        python ner_agent_auto.py --rebuild "test"
    """
    trust_env = os.getenv("TRUST_ENV", "1") != "0"
    http_client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
        trust_env=trust_env,
    )
    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        api_key=_require_env("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        http_client=http_client,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolSearchHit:
    """
    A single ranked search result.

    Fields
    ------
    rank          Rank starting at 1 (most relevant first).
    score         FAISS L2 distance (lower = more similar).
    func_name     Python identifier in the generated module, e.g. ``get_movie_title``.
                  Empty string when using a legacy LLM-description index.
    tool_name     Tool name from the @tool / tool_json metadata.
    description   Short human-readable description.
    node_type     Neo4j node type (e.g. ``:Movie``). Empty for relation tools.
    property_name Neo4j property name (e.g. ``title``).
    tool_json     Full tool JSON object (from LLM-description index only).
    raw_text      Raw page_content stored in the vectorstore doc.
    """
    rank:          int
    score:         float
    func_name:     str             = ""
    tool_name:     str             = ""
    description:   str             = ""
    node_type:     str             = ""
    property_name: str             = ""
    tool_json:     Dict[str, Any]  = field(default_factory=dict)
    raw_text:      str             = ""


# ──────────────────────────────────────────────────────────────────────────────
# Workflow A — load & search an existing FAISS index
# ──────────────────────────────────────────────────────────────────────────────

def load_faiss_vectorstore(
    faiss_dir: Union[str, Path],
    embeddings: Optional[OpenAIEmbeddings] = None,
    *,
    expected_tool_names: Optional[List[str]] = None,
    expected_ner_mode:   Optional[str]       = None,
    skip_fingerprint:    bool                = False,
) -> FAISS:
    """
    Load a FAISS vectorstore from a directory produced by ``FAISS.save_local()``.

    Handles both old (no ``allow_dangerous_deserialization``) and new
    LangChain API signatures transparently.

    Fingerprint guard (default behaviour)
    -------------------------------------
    Before delegating to ``FAISS.load_local()``, the on-disk
    ``fingerprint.json`` is verified against the live environment. Any
    mismatch raises :class:`StaleFaissIndexError`; the error is NEVER
    swallowed here — the user must rerun ``setup_project.py``.

    Parameters
    ----------
    faiss_dir
        Directory holding the index files + fingerprint.
    embeddings
        Embedding client used for queries (not validated against the
        fingerprint — the embedding *model name* is, via the fingerprint
        ``embedding_model`` field).
    expected_tool_names
        Optional list of ``func_name``s the caller will query with. When
        provided, the fingerprint's ``tool_names_hash`` + ``tool_count``
        are also verified. Pass ``None`` (the default) to skip those two
        fields when the caller does not have a registry on hand.
    expected_ner_mode
        Optional NER mode for an extra defensive check.
    skip_fingerprint
        Escape hatch for tests / migrations that need to bypass the guard
        deliberately. **Never** pass ``True`` from production code.
    """
    if not os.path.isdir(faiss_dir):
        raise FileNotFoundError(
            f"FAISS directory not found: {faiss_dir!r}. "
            "Run the appropriate build step first."
        )

    # ── Fingerprint check fires BEFORE any expensive load work. ───────────
    # We deliberately do not catch StaleFaissIndexError here — see the
    # module docstring above StaleFaissIndexError for the rationale.
    if not skip_fingerprint:
        _verify_fingerprint(
            faiss_dir,
            expected_tool_names=expected_tool_names,
            expected_ner_mode=expected_ner_mode,
        )

    if embeddings is None:
        embeddings = build_embeddings()
    try:
        return FAISS.load_local(
            faiss_dir, embeddings, allow_dangerous_deserialization=True
        )
    except TypeError:
        return FAISS.load_local(faiss_dir, embeddings)


def search_tools(
    vectorstore: FAISS,
    user_query: str,
    top_l: int = 5,
) -> List[ToolSearchHit]:
    """
    Search *vectorstore* with *user_query* and return up to *top_l* hits.

    Works with both Workflow A (LLM-description index) and Workflow B
    (registry-based index).  The returned ``ToolSearchHit`` objects are
    populated from whatever metadata is available in the stored documents.
    """
    if top_l <= 0:
        raise ValueError("top_l must be > 0")

    results = vectorstore.similarity_search_with_score(user_query, k=top_l)
    hits: List[ToolSearchHit] = []

    for i, (doc, score) in enumerate(results, start=1):
        meta     = doc.metadata or {}
        raw_text = doc.page_content or ""

        # ── Try to read tool JSON from metadata (Workflow A) ─────────────────
        tool_json: Dict[str, Any] = {}
        raw_json = meta.get("tool_json", "")
        if raw_json:
            try:
                tool_json = json.loads(raw_json)
            except Exception:
                pass

        # ── Populate fields from whatever is available ────────────────────────
        tool_name   = (meta.get("tool_name") or
                       tool_json.get("tool_name") or "")
        description = (meta.get("description") or
                       tool_json.get("description") or "")

        hits.append(ToolSearchHit(
            rank          = i,
            score         = float(score),
            func_name     = str(meta.get("func_name",     "")),
            tool_name     = str(tool_name),
            description   = str(description),
            node_type     = str(meta.get("node_type",     "")),
            property_name = str(meta.get("property_name", "")),
            tool_json     = tool_json,
            raw_text      = raw_text,
        ))

    return hits


def print_search_results(
    user_query: str,
    hits: List[ToolSearchHit],
    max_desc_chars: int = 300,
) -> None:
    """Pretty-print search results to stdout."""
    print("=" * 80)
    print(f"Query  : {user_query}")
    print(f"Hits   : {len(hits)}")
    print("=" * 80)
    if not hits:
        print("No results found.")
        return
    for h in hits:
        preview = (h.description or "").strip().replace("\n", " ")
        if max_desc_chars > 0 and len(preview) > max_desc_chars:
            preview = preview[:max_desc_chars] + "…"
        print(f"\n[{h.rank}]  score={h.score:.4f}")
        if h.func_name:
            print(f"  func_name     : {h.func_name}")
        if h.node_type:
            print(f"  node_type     : {h.node_type}")
        if h.property_name:
            print(f"  property_name : {h.property_name}")
        print(f"  tool_name     : {h.tool_name}")
        print(f"  description   : {preview}")


# ──────────────────────────────────────────────────────────────────────────────
# Workflow B — build FAISS from a @tool function registry
# ──────────────────────────────────────────────────────────────────────────────

def build_tool_registry_from_modules(modules: list) -> Dict[str, BaseTool]:
    """
    Scan a list of Python modules and collect every LangChain ``@tool``
    (``BaseTool``) instance found at module level.

    Returns
    -------
    dict
        ``{python_func_name: BaseTool_instance}``

    Example
    -------
    >>> import generated_node_tools, generated_rel_tools
    >>> registry = build_tool_registry_from_modules(
    ...     [generated_node_tools, generated_rel_tools]
    ... )
    """
    registry: Dict[str, BaseTool] = {}
    for mod in modules:
        for name, obj in inspect.getmembers(mod):
            if isinstance(obj, BaseTool):
                registry[name] = obj
    return registry


def build_tools_faiss(
    registry:   Dict[str, BaseTool],
    faiss_dir:  Union[str, Path],
    embeddings: Optional[OpenAIEmbeddings] = None,
    *,
    ner_mode:   str = "full",
) -> FAISS:
    """
    Build and persist a FAISS vectorstore from a tool registry.

    Each tool contributes one document whose embedding text is::

        "<func_name>: <tool.description>"

    and whose metadata stores ``func_name``, ``tool_name``, and ``description``
    for retrieval without re-parsing.

    Parameters
    ----------
    registry  : Output of :func:`build_tool_registry_from_modules`.
    faiss_dir : Directory where the index is saved (created if absent).
    embeddings: If *None*, :func:`build_embeddings` is called automatically.

    Returns
    -------
    FAISS  The in-memory vectorstore (also persisted to *faiss_dir*).
    """
    if not registry:
        raise ValueError(
            "Tool registry is empty. "
            "Run `python gen_tools.py` first to generate the tool files."
        )
    if embeddings is None:
        embeddings = build_embeddings()

    texts: List[str]           = []
    metadatas: List[Dict[str, Any]] = []

    for func_name, tool_obj in registry.items():
        desc  = (tool_obj.description or "").strip()
        tname = (tool_obj.name        or func_name).strip()
        # Embedding text: rich enough to match diverse user phrasings
        text  = f"{func_name}: {tname}: {desc}"
        texts.append(text)
        metadatas.append({
            "func_name":   func_name,
            "tool_name":   tname,
            "description": desc,
        })

    Path(faiss_dir).mkdir(parents=True, exist_ok=True)
    vs = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas)
    vs.save_local(os.fspath(faiss_dir))

    # Write the fingerprint AFTER save_local() succeeds so a build that
    # crashes mid-write never leaves a fingerprint pointing at a partial
    # index. See the module-level docstring on StaleFaissIndexError for
    # the design rationale.
    fingerprint = _live_fingerprint(
        list(registry.keys()),
        ner_mode=ner_mode,
    )
    fp_path = _write_fingerprint(faiss_dir, fingerprint)
    logger.info(
        f"[tool_search] Wrote FAISS fingerprint: {fp_path} "
        f"(db={fingerprint['database']!r}, "
        f"tools={fingerprint['tool_count']}, "
        f"model={fingerprint['embedding_model']!r})"
    )
    return vs


def get_or_build_tools_faiss(
    registry:   Dict[str, BaseTool],
    faiss_dir:  Union[str, Path] = FAISS_AUTO_DIR,
    rebuild:    bool = False,
    embeddings: Optional[OpenAIEmbeddings] = None,
    *,
    ner_mode:   str = "full",
) -> FAISS:
    """
    Load the FAISS index from *faiss_dir* if it exists, otherwise build it.

    Parameters
    ----------
    registry  : Tool registry; only used when building (not loading).
    faiss_dir : Directory of the FAISS index.
    rebuild   : If *True*, always rebuild even if the directory exists.
                ``rebuild_tools_faiss`` always passes ``True`` so the
                fingerprint check on the load path is bypassed (a fresh
                fingerprint is written instead).
    embeddings: Shared embeddings client.
    ner_mode  : Recorded in the new fingerprint when (re)building. Has no
                effect on the load path — verification reads the on-disk
                value.

    Returns
    -------
    FAISS  Ready-to-query vectorstore.

    Raises
    ------
    StaleFaissIndexError
        Propagated from :func:`load_faiss_vectorstore` when the on-disk
        fingerprint does not match the live env. Never auto-rebuilt — the
        user must rerun ``setup_project.py``.
    """
    if embeddings is None:
        embeddings = build_embeddings()

    index_exists = (
        os.path.isfile(os.path.join(faiss_dir, "index.faiss")) and
        os.path.isfile(os.path.join(faiss_dir, "index.pkl"))
    )

    if index_exists and not rebuild:
        print(f"Loading tool FAISS index from {faiss_dir!r} …", flush=True)
        # Pass the live registry's tool names so the fingerprint also
        # validates the tool-set hash + count. StaleFaissIndexError
        # bubbles up — do NOT catch and rebuild.
        return load_faiss_vectorstore(
            faiss_dir, embeddings,
            expected_tool_names=list(registry.keys()) if registry else None,
            expected_ner_mode=ner_mode,
        )

    action = "Rebuilding" if (index_exists and rebuild) else "Building"
    print(
        f"{action} tool FAISS index ({len(registry)} tools) → {faiss_dir!r} …",
        flush=True,
    )
    return build_tools_faiss(registry, faiss_dir, embeddings, ner_mode=ner_mode)


def hits_to_callables(
    hits: List[ToolSearchHit],
    registry: Dict[str, BaseTool],
) -> List[BaseTool]:
    """
    Convert a list of :class:`ToolSearchHit` objects into the actual
    ``BaseTool`` callables by looking up ``hit.func_name`` in *registry*.

    Hits whose ``func_name`` is absent from the registry are silently skipped.
    """
    tools: List[BaseTool] = []
    seen: set = set()
    for hit in hits:
        fn = hit.func_name
        if fn and fn in registry and fn not in seen:
            tools.append(registry[fn])
            seen.add(fn)
    return tools
