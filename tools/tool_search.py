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

import inspect
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from paths import FAISS_AUTO_DIR

import httpx
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
) -> FAISS:
    """
    Load a FAISS vectorstore from a directory produced by ``FAISS.save_local()``.

    Handles both old (no ``allow_dangerous_deserialization``) and new
    LangChain API signatures transparently.
    """
    if not os.path.isdir(faiss_dir):
        raise FileNotFoundError(
            f"FAISS directory not found: {faiss_dir!r}. "
            "Run the appropriate build step first."
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
    registry: Dict[str, BaseTool],
    faiss_dir: Union[str, Path],
    embeddings: Optional[OpenAIEmbeddings] = None,
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
    return vs


def get_or_build_tools_faiss(
    registry: Dict[str, BaseTool],
    faiss_dir: Union[str, Path] = FAISS_AUTO_DIR,
    rebuild:   bool = False,
    embeddings: Optional[OpenAIEmbeddings] = None,
) -> FAISS:
    """
    Load the FAISS index from *faiss_dir* if it exists, otherwise build it.

    Parameters
    ----------
    registry  : Tool registry; only used when building (not loading).
    faiss_dir : Directory of the FAISS index.
    rebuild   : If *True*, always rebuild even if the directory exists.
    embeddings: Shared embeddings client.

    Returns
    -------
    FAISS  Ready-to-query vectorstore.
    """
    if embeddings is None:
        embeddings = build_embeddings()

    index_exists = (
        os.path.isfile(os.path.join(faiss_dir, "index.faiss")) and
        os.path.isfile(os.path.join(faiss_dir, "index.pkl"))
    )

    if index_exists and not rebuild:
        print(f"Loading tool FAISS index from {faiss_dir!r} …", flush=True)
        return load_faiss_vectorstore(faiss_dir, embeddings)

    action = "Rebuilding" if (index_exists and rebuild) else "Building"
    print(
        f"{action} tool FAISS index ({len(registry)} tools) → {faiss_dir!r} …",
        flush=True,
    )
    return build_tools_faiss(registry, faiss_dir, embeddings)


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
