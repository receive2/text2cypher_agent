"""
data_augmentation.llm
=====================
Thin wrapper around :func:`agent.agent_helper.build_llm_from_config` so
the augmentation pipeline can build an LLM from a config dict that has
exactly the same shape as ``NER_LLM_CONFIG`` / ``CYPHER_LLM_CONFIG`` in
``config.py``.

Disk cache
----------
:class:`LLMClient.complete` is wrapped by an append-only on-disk cache
backed by a JSONL file at ``cache/augmenter_paraphrase.jsonl`` (relative
to the repo root).  The filename is historical — the cache covers ALL
LLM calls routed through :meth:`LLMClient.complete` (paraphrase
augmenter, entity-extractor LLM fallback, and any future caller) since
they all funnel through this single chokepoint.

* Key: ``sha256((system or "") + "||" + user_prompt + "||" + model).hexdigest()``
* Storage: append-only JSONL of ``{"key": "...", "response": "..."}``
* Loading: read once into an in-memory dict at module import.
* Hits: return cached value immediately, log at DEBUG.
* Misses: call LLM; if non-None, persist + cache + return.  Failures
  (None) are NOT cached so the pipeline can retry on the next run.

Tests can override the cache file location by setting the
``DATA_AUG_CACHE_FILE`` env var before importing / reloading this
module.

Example
-------
::

    from data_augmentation.llm import LLMClient
    client = LLMClient({
        "provider":    "anthropic",
        "model":       "claude-opus-4-20250514",
        "temperature": 0.4,
    })
    text = client.complete("Rewrite 'Sacramento Kings' colloquially.")
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# ──────────────────────────────────────────────────────────────────────────────
# Disk cache
# ──────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE_FILE = _REPO_ROOT / "cache" / "augmenter_paraphrase.jsonl"


def _cache_file_path() -> Path:
    """Resolve the cache JSONL path; honors DATA_AUG_CACHE_FILE override."""
    override = os.environ.get("DATA_AUG_CACHE_FILE")
    if override:
        return Path(override)
    return _DEFAULT_CACHE_FILE


def _cache_key(system: Optional[str], prompt: str, model: str) -> str:
    blob = (system or "") + "||" + prompt + "||" + model
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_cache(path: Path) -> Dict[str, str]:
    """
    Read the JSONL cache into an in-memory dict.  Tolerant of missing
    file and individual corrupt lines (corrupt lines are logged and
    skipped).
    """
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug(
                        f"data_augmentation.llm: skipping corrupt cache line "
                        f"{line_no} in {path}"
                    )
                    continue
                key = obj.get("key")
                resp = obj.get("response")
                if isinstance(key, str) and isinstance(resp, str):
                    out[key] = resp
    except OSError as exc:  # noqa: BLE001
        logger.warning(f"data_augmentation.llm: failed to read cache {path}: {exc}")
    return out


def _persist_cache_entry(path: Path, key: str, response: str) -> None:
    """Append one ``{"key","response"}`` line to the cache JSONL."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "response": response}, ensure_ascii=False))
            fh.write("\n")
    except OSError as exc:  # noqa: BLE001
        logger.warning(f"data_augmentation.llm: failed to persist cache to {path}: {exc}")


# Module-level cache state.  Loaded once at import; protected by a lock
# for thread-safe append + dict mutation under (rare) concurrent use.
_CACHE_PATH: Path = _cache_file_path()
_CACHE: Dict[str, str] = _load_cache(_CACHE_PATH)
_CACHE_LOCK = threading.Lock()


# ──────────────────────────────────────────────────────────────────────────────
# Lazy import of the LangChain stack
# ──────────────────────────────────────────────────────────────────────────────
# We import inside the constructor so importing this module doesn't pull
# the full LangChain dep tree just to inspect type signatures.

class LLMClient:
    """
    Stateless chat-completion adapter for the augmentation pipeline.

    Parameters
    ----------
    config
        Dict matching :mod:`config`'s LLM-config schema.  When ``None``
        the client refuses to issue calls — useful when LLM-dependent
        strategies (paraphrase, abbreviation/synonym fallback, LLM
        entity extraction) should be skipped entirely.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = dict(config) if config else None
        self._llm = None  # lazily built on first call

    # ── Public API ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._config is not None

    def complete(self, prompt: str, *, system: Optional[str] = None) -> Optional[str]:
        """
        Issue one chat completion.  Returns the assistant's text reply,
        or ``None`` on any failure (LLM not configured, network error,
        empty response).  Failures are logged at WARNING.

        Backed by a process-wide on-disk cache; identical
        (system, prompt, model) tuples are served from cache and never
        re-issued.  Failures are not cached.
        """
        if not self.enabled:
            return None

        # Defensive against config-shape variation: some callers use
        # "model", others "model_name".  Don't let None collapse all
        # models into one cache key.
        model = (
            (self._config.get("model")
             or self._config.get("model_name")
             or "unknown")
            if self._config else "unknown"
        )
        key = _cache_key(system, prompt, str(model))

        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached is not None:
            logger.debug(f"data_augmentation.llm: cache hit ({key[:12]}…)")
            return cached

        try:
            llm = self._ensure_llm()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"data_augmentation.llm: build_llm failed: {exc}")
            return None

        from langchain_core.messages import HumanMessage, SystemMessage

        msgs: List[Any] = []
        if system:
            msgs.append(SystemMessage(content=system))
        msgs.append(HumanMessage(content=prompt))

        try:
            resp = llm.invoke(msgs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"data_augmentation.llm: invoke failed: {exc}")
            return None

        text = getattr(resp, "content", None)
        if isinstance(text, list):
            # Some LangChain backends return list-of-content-blocks.
            text = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in text
            )
        if not isinstance(text, str):
            return None
        text = text.strip()
        if not text:
            return None

        # Cache successful response.
        with _CACHE_LOCK:
            _CACHE[key] = text
            _persist_cache_entry(_CACHE_PATH, key, text)
        logger.debug(f"data_augmentation.llm: cache miss → persisted ({key[:12]}…)")

        return text

    # ── Internals ─────────────────────────────────────────────────────

    def _ensure_llm(self):
        if self._llm is not None:
            return self._llm
        # Primary path: route through agent.agent_helper so the
        # augmentation pipeline shares the same provider abstraction as
        # the rest of the codebase.  However, ``agent.agent_helper``
        # transitively imports Neo4j-bound modules — which is fine in
        # production but fails in environments where Neo4j isn't
        # running.  Fall back to LangChain's direct constructors so the
        # augmentation pipeline doesn't require a live graph DB just to
        # paraphrase strings.
        try:
            from agent.agent_helper import build_llm_from_config
            self._llm = build_llm_from_config(self._config)
            return self._llm
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"data_augmentation.llm: agent.agent_helper unavailable "
                f"({exc}); falling back to direct LangChain construction"
            )

        cfg = self._config or {}
        provider = (cfg.get("provider") or "").lower()
        model = cfg.get("model") or cfg.get("model_name") or ""
        temperature = cfg.get("temperature", 0.4)
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            self._llm = ChatAnthropic(model=model, temperature=temperature)
        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(model=model, temperature=temperature)
        elif provider == "azure" or provider == "azure_openai":
            from langchain_openai import AzureChatOpenAI
            self._llm = AzureChatOpenAI(
                deployment_name=model,
                temperature=temperature,
            )
        else:
            # Last-resort generic init.
            from langchain.chat_models import init_chat_model
            self._llm = init_chat_model(
                model=model,
                model_provider=provider or None,
                temperature=temperature,
            )
        return self._llm


# ──────────────────────────────────────────────────────────────────────────────
# Output parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

_QUOTE_RE = re.compile(r'^["\'`]+|["\'`]+$')


def strip_quotes(s: str) -> str:
    """Strip wrapping quotes / backticks / surrounding whitespace."""
    return _QUOTE_RE.sub("", s).strip()


def first_nonempty_line(text: Optional[str]) -> Optional[str]:
    """Return the first non-empty stripped line of *text* (or None)."""
    if text is None:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line:
            return strip_quotes(line)
    return None
