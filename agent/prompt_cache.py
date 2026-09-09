#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_cache.py
===============
Provider-portable prompt caching, expressed once in the prompt text.

Every stage prompt in this repo is laid out static-first::

    <task instructions>  <graph schema>  |  <retrieved values>  <question>
    \\________ identical for every question on a graph ______/     \\__ varies __/

OpenAI caches that prefix automatically once it exceeds ~1k tokens, so the
GPT stages need nothing. Anthropic caching is opt-in: the static part has to
arrive as its own content block carrying ``cache_control``. Rather than teach
each call site (some prompts are assembled by LangChain chains we do not own),
the boundary is marked *in the template* with :data:`CACHE_BREAK` and resolved
here, at the model wrapper:

* Anthropic  → split into blocks, ``cache_control`` on everything before the
  last break.
* Everyone else → the marker is stripped.

**The model always sees byte-identical text either way** — the marker carries
no content and is removed on every path. That property is what makes it safe
to switch a run's generator model without changing what the model reads, and
it is pinned by ``tests/test_prompt_cache.py``.

Cost: the static prefix is ~2.8k tokens of a ~3.2k-token Cypher call, and it
repeats for every question on a graph. Anthropic bills a cache read at a tenth
of the input rate, so a full sweep on a Claude model drops by roughly half.
"""
from __future__ import annotations

from typing import Any, Dict, List

# A marker that cannot occur in natural prompt text or in graph data. Kept
# ASCII-safe so it survives template formatting, f-strings and JSON round-trips.
CACHE_BREAK = "<<<PROMPT_CACHE_BREAK>>>"


def strip_breaks(text: str) -> str:
    """The prompt as the model must see it — markers removed."""
    return text.replace(CACHE_BREAK, "")


def has_break(text: str) -> bool:
    return CACHE_BREAK in text


def to_anthropic_blocks(text: str, min_chars: int = 4096) -> List[Dict[str, Any]]:
    """Split marked text into Anthropic content blocks.

    Everything before the final marker becomes one cached block; the remainder
    becomes an uncached block. Returns a single plain block when there is no
    marker, or when the static part is shorter than ``min_chars`` — Anthropic
    silently declines to cache a prefix below roughly 1024 tokens (~4k chars),
    and a breakpoint that never hits is pure overhead.

    ``"".join(b["text"] for b in blocks) == strip_breaks(text)`` always holds.
    """
    if CACHE_BREAK not in text:
        return [{"type": "text", "text": text}]

    head, _, tail = text.rpartition(CACHE_BREAK)
    head = strip_breaks(head)          # collapse any earlier markers
    tail = strip_breaks(tail)

    if len(head) < min_chars:
        return [{"type": "text", "text": head + tail}]

    blocks: List[Dict[str, Any]] = [
        {"type": "text", "text": head, "cache_control": {"type": "ephemeral"}}
    ]
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks


def prepare_content(content: Any, anthropic: bool) -> Any:
    """Normalise one message's ``content`` for the target provider.

    Non-string content (already-structured blocks) is returned untouched apart
    from stripping markers out of any text blocks it contains.
    """
    if isinstance(content, str):
        if not anthropic:
            return strip_breaks(content)
        # No boundary declared → leave the message exactly as it was. Only
        # prompts that actually ask for caching change shape.
        return to_anthropic_blocks(content) if CACHE_BREAK in content else content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part = {**part, "text": strip_breaks(part["text"])}
            elif isinstance(part, str):
                part = strip_breaks(part)
            out.append(part)
        return out
    return content


def prepare_messages(messages: Any, anthropic: bool) -> Any:
    """Apply :func:`prepare_content` to every message, preserving message type.

    LangChain message objects are copied rather than mutated so a retry that
    re-sends the same list is unaffected.
    """
    out = []
    for m in messages:
        content = getattr(m, "content", None)
        if content is None:
            out.append(m)
            continue
        new = prepare_content(content, anthropic)
        if new is content:
            out.append(m)
        else:
            try:
                out.append(m.model_copy(update={"content": new}))   # pydantic v2
            except AttributeError:
                try:
                    out.append(m.copy(update={"content": new}))     # pydantic v1
                except Exception:                                    # noqa: BLE001
                    m.content = new
                    out.append(m)
    return out
