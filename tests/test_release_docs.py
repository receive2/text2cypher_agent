#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The dataset-release documents must agree with the released data."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
RELEASE_DOCS = [DOCS / n for n in ("DATASHEET.md", "VERIFICATION_PROTOCOL.md", "AUGMENTATION_METHODS.md",
                                  "LLM_USE_DISCLOSURE.md", "INDEX.md")] + [REPO / "benchmarks" / "README.md"]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_datasheet_numbers_match_the_data():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "render_datasheet_tables.py"), "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_release_docs_carry_no_working_state():
    bad = re.compile(r"TODO|TBD|pending adjudication|await adjudication|in progress|~/datasets|/Users/", re.I)
    for p in RELEASE_DOCS:
        for i, line in enumerate(_read(p).splitlines(), 1):
            assert not bad.search(line), f"{p.name}:{i}: {line.strip()[:100]}"


def test_release_docs_do_not_point_at_archived_files():
    archived = ("REVIEW_GUIDE.md", "ANNOTATION_SHEET.md", "ANNOTATION_PROCESS_LOG.md")
    for p in RELEASE_DOCS:
        for name in archived:
            for m in re.finditer(re.escape(name), _read(p)):
                ctx = _read(p)[max(0, m.start() - 12):m.start()]
                assert "archive/" in ctx, f"{p.name} links {name} outside archive/"


def test_calibration_size_is_stated_correctly():
    n = sum(1 for _ in (REPO / "audit" / "verification" / "calibration_ids.csv").open(encoding="utf-8")) - 1
    assert f"the same {n} items" in _read(DOCS / "VERIFICATION_PROTOCOL.md")


def test_gold_executability_covers_every_released_question():
    d = json.loads(_read(REPO / "audit" / "gold_executability.json"))
    released = 0
    for ds in ("cypherbench", "mindthequery", "zograscope"):
        released += len(json.loads(_read(REPO / "benchmarks" / f"{ds}_augmented_v2" / "test.json")))
    assert sum(g["n"] for g in d["graphs"]) == released
    assert "v2.3" in d["version"]


def test_proposer_pins_are_stated_exactly():
    pinned = unpinned = 0
    for ds in ("cypherbench", "mindthequery", "zograscope"):
        for r in json.loads(_read(REPO / "benchmarks" / f"{ds}_augmented_v2" / "test.json")):
            e = (r["_aug_meta"].get("edits") or [{}])[0]
            if e.get("source") == "llm":
                pinned += "proposer_model" in e; unpinned += "proposer_model" not in e
    for name in ("DATASHEET.md", "AUGMENTATION_METHODS.md", "LLM_USE_DISCLOSURE.md"):
        t = _read(DOCS / name)
        assert str(pinned) in t and str(unpinned) in t, f"{name} does not state {pinned} pinned / {unpinned} unpinned"
