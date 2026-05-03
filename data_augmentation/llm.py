"""
data_augmentation.llm
=====================
Thin wrapper around :func:`agent.agent_helper.build_llm_from_config` so
the augmentation pipeline can build an LLM from a config dict that has
exactly the same shape as ``NER_LLM_CONFIG`` / ``CYPHER_LLM_CONFIG`` in
``config.py``.

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

import re
from typing import Any, Dict, List, Optional

from loguru import logger


# ── Lazy import of the LangChain stack ───────────────────────────────────────
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
        """
        if not self.enabled:
            return None
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
        return text.strip() or None

    # ── Internals ─────────────────────────────────────────────────────

    def _ensure_llm(self):
        if self._llm is not None:
            return self._llm
        from agent.agent_helper import build_llm_from_config

        self._llm = build_llm_from_config(self._config)
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
