#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt caching must not change what the model reads.

The cache marker is inserted into prompt templates, so the one property that
makes it safe to land before a multi-model sweep is that the marker never
reaches a provider: on every path the text the model sees is byte-identical to
the text it saw before caching existed. If that ever breaks, results move and
the numbers stop being comparable to the runs already on disk.
"""
from __future__ import annotations

import pytest

from agent import prompt_cache as pc


STATIC = "TASK INSTRUCTIONS\n" + ("schema line\n" * 500)   # > min_chars
VARIABLE = "entities: {a: 1}\nquestion: who directed Alien?"
MARKED = STATIC + pc.CACHE_BREAK + VARIABLE
PLAIN = STATIC + VARIABLE


# ── the invariant ────────────────────────────────────────────────────────────

def test_anthropic_blocks_reconstruct_the_original_text():
    blocks = pc.to_anthropic_blocks(MARKED)
    assert "".join(b["text"] for b in blocks) == PLAIN


def test_stripping_reconstructs_the_original_text():
    assert pc.strip_breaks(MARKED) == PLAIN


def test_marker_never_survives_to_any_provider():
    for anthropic in (True, False):
        prepared = pc.prepare_content(MARKED, anthropic=anthropic)
        text = prepared if isinstance(prepared, str) else "".join(
            b["text"] for b in prepared)
        assert pc.CACHE_BREAK not in text
        assert text == PLAIN


# ── block shape ──────────────────────────────────────────────────────────────

def test_cache_control_is_on_the_static_block_only():
    blocks = pc.to_anthropic_blocks(MARKED)
    assert len(blocks) == 2
    assert blocks[0]["text"] == STATIC
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[1]
    assert blocks[1]["text"] == VARIABLE


def test_short_prefix_is_not_split():
    short = "tiny" + pc.CACHE_BREAK + "tail"
    blocks = pc.to_anthropic_blocks(short)
    assert blocks == [{"type": "text", "text": "tinytail"}]


def test_unmarked_text_is_passed_through():
    assert pc.to_anthropic_blocks(PLAIN) == [{"type": "text", "text": PLAIN}]


def test_multiple_markers_split_at_the_last_one():
    text = STATIC + pc.CACHE_BREAK + "middle" + pc.CACHE_BREAK + VARIABLE
    blocks = pc.to_anthropic_blocks(text)
    assert "".join(b["text"] for b in blocks) == STATIC + "middle" + VARIABLE
    assert blocks[0]["text"].endswith("middle")
    assert blocks[1]["text"] == VARIABLE


def test_openai_path_returns_a_plain_string():
    out = pc.prepare_content(MARKED, anthropic=False)
    assert isinstance(out, str) and out == PLAIN


# ── message handling ─────────────────────────────────────────────────────────

class _Msg:
    """Minimal stand-in for a LangChain message (no pydantic copy helpers)."""

    def __init__(self, content):
        self.content = content


def test_prepare_messages_covers_every_message():
    msgs = [_Msg(MARKED), _Msg("no marker here")]
    out = pc.prepare_messages(msgs, anthropic=True)
    assert "".join(b["text"] for b in out[0].content) == PLAIN
    assert out[1].content == "no marker here"


def test_prepare_messages_leaves_unrelated_objects_alone():
    class NoContent:
        pass

    obj = NoContent()
    assert pc.prepare_messages([obj], anthropic=True) == [obj]


def test_already_structured_content_only_gets_stripped():
    content = [{"type": "text", "text": "a" + pc.CACHE_BREAK + "b"}]
    out = pc.prepare_content(content, anthropic=True)
    assert out == [{"type": "text", "text": "ab"}]


# ── the real template ────────────────────────────────────────────────────────

def test_cypher_template_marks_the_static_variable_boundary():
    """The marker must sit after the schema and before the per-question parts,
    or the cached prefix would differ on every question and never hit."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "agent" / "agent_helper.py"
    text = src.read_text(encoding="utf-8")
    m = re.search(r'cypher_template = """', text)
    assert m, "cypher_template not found"
    tpl = text[m.end():text.index('"""', m.end())]

    assert "{cache_break}" in tpl, "cypher_template lost its cache boundary"
    i_break = tpl.index("{cache_break}")
    assert tpl.index("{schema}") < i_break, "schema must be inside the cached prefix"
    assert i_break < tpl.index("{relevant_entities}")
    assert i_break < tpl.index("{question}")


def test_filled_cypher_template_has_a_prefix_worth_caching():
    """With a realistic schema injected the static prefix must clear the
    Anthropic minimum, otherwise the breakpoint is silently ignored."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "agent" / "agent_helper.py"
    text = src.read_text(encoding="utf-8")
    m = re.search(r'cypher_template = """', text)
    tpl = text[m.end():text.index('"""', m.end())]

    filled = (tpl.replace("{cache_break}", pc.CACHE_BREAK)
                 .replace("{schema}", "node props\n" * 250)      # ~2.5k chars
                 .replace("{relevant_entities}", "{'Movie.name': ['Alien']}")
                 .replace("{question}", "who directed Alien?"))
    blocks = pc.to_anthropic_blocks(filled)
    assert len(blocks) == 2, "prefix too short to cache — check the boundary"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "".join(b["text"] for b in blocks) == pc.strip_breaks(filled)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
