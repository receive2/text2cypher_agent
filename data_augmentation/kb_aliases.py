"""
data_augmentation.kb_aliases
============================
Attested-alias provider.  Supplies abbreviation and alias candidate forms
from sources that are *independent of any LLM and any system under test*, so
using them cannot bias the benchmark toward a model:

  1. **CypherBench shipped aliases** — each ``*_simplekg.json`` entity carries
     a Wikidata-derived ``aliases`` list (nba 76.6%, movie 29.4%, company
     25.4% coverage).  Citable, reproducible, model-free.
  2. **Curated tables** — hand-verified acronym pairs (countries, orgs, US
     agencies, sports leagues, ranks) and replacement nicknames.
  3. **RxNorm brand↔generic** (Mind-the-Query drugs) — Phase-2 hook; loaded
     from a TSV if present, else empty.

Each lookup returns ``(form, source_tag)`` pairs so provenance lands in
``_aug_meta``.  Forms are classified abbrev-vs-alias: an acronym/initialism or
much-shorter token is ``abbrev``; a replacement nickname is ``alias``.
LLM-proposed forms do NOT come from here — the augmenters add those directly,
flagged for human verification.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

from loguru import logger

from data_augmentation.augmenters.base import (
    SOURCE_KB_CURATED, SOURCE_KB_SIMPLEKG, SOURCE_RXNORM,
)

# ── Curated acronym pairs (long, short) — ported & trimmed from the old
#    abbreviation._PAIRS.  Bidirectional. ──────────────────────────────────────
_CURATED_ABBREV: List[Tuple[str, str]] = [
    ("United States", "US"), ("United States of America", "USA"),
    ("United Kingdom", "UK"), ("European Union", "EU"), ("United Nations", "UN"),
    ("North Atlantic Treaty Organization", "NATO"), ("World Health Organization", "WHO"),
    ("Federal Bureau of Investigation", "FBI"), ("Central Intelligence Agency", "CIA"),
    ("National Aeronautics and Space Administration", "NASA"),
    ("National Basketball Association", "NBA"), ("National Football League", "NFL"),
    ("Republican Party", "GOP"), ("New York City", "NYC"), ("Los Angeles", "LA"),
    # ranks (ZOGRASCOPE policing)
    ("Sergeant", "Sgt"), ("Inspector", "Insp"), ("Constable", "PC"),
    ("Detective", "DET"),
]

# ── Curated replacement nicknames (surface → alternatives) ───────────────────
_CURATED_ALIAS: Dict[str, Tuple[str, ...]] = {
    "united states of america": ("America",), "united states": ("America",),
    "united kingdom": ("Britain",), "netherlands": ("Holland",),
    "new york city": ("the Big Apple",), "los angeles": ("LA",),
    "los angeles lakers": ("the Lakers",), "boston celtics": ("the Celtics",),
    "golden state warriors": ("the Warriors",),
    # basketball position slang — a closed set, so the LLM alias fallback won't
    # fire here; these come from this trusted table instead.
    "point guard": ("the floor general", "the one"),
    "shooting guard": ("the two guard", "the two"),
    "small forward": ("the three",),
    "power forward": ("the four",),
    "center": ("the five", "the big man"),
}


def _is_acronymish(name: str, form: str) -> bool:
    """Heuristic: does *form* read as an acronym / short form of *name*?"""
    f = form.strip()
    if not f or " " in f.strip() and not f.isupper():
        # multi-word non-caps → not an acronym
        if not f.isupper():
            return False
    # all-caps short token
    if f.isupper() and 1 < len(f) <= 6:
        return True
    # initials match
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name)).upper()
    return f.upper().replace(".", "") == initials and len(initials) >= 2


class AliasProvider:
    """Per-graph alias source.  Construct once per (dataset, graph)."""

    def __init__(
        self,
        graph: Optional[str] = None,
        simplekg_root: Optional[str] = None,
        rxnorm_path: Optional[str] = None,
    ):
        self.graph = graph
        self._simplekg_root = Path(
            simplekg_root or os.path.expanduser("~/datasets/cypherbench/graphs/simplekg")
        )
        self._rxnorm_path = rxnorm_path
        self._skg: Optional[Dict[str, FrozenSet[str]]] = None   # name.lower → aliases
        self._rx: Optional[Dict[str, FrozenSet[str]]] = None
        self._curated_abbrev = self._build_curated_abbrev()

    # ── loading ───────────────────────────────────────────────────────────
    def _build_curated_abbrev(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for lo, sh in _CURATED_ABBREV:
            out[lo.lower()] = sh
            out.setdefault(sh.lower(), lo)   # reverse; first long form wins
        return out

    def _load_simplekg(self) -> Dict[str, FrozenSet[str]]:
        if self._skg is not None:
            return self._skg
        out: Dict[str, set] = {}
        if self.graph:
            f = self._simplekg_root / f"{self.graph}_simplekg.json"
            if f.is_file():
                try:
                    g = json.load(open(f, encoding="utf-8"))
                    for e in g.get("entities", []):
                        nm = e.get("name")
                        al = e.get("aliases") or []
                        if isinstance(nm, str) and al:
                            out.setdefault(nm.strip().lower(), set()).update(
                                a.strip() for a in al if isinstance(a, str) and a.strip()
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"kb_aliases: failed to load {f}: {exc}")
            else:
                logger.debug(f"kb_aliases: no simplekg file for graph={self.graph} ({f})")
        self._skg = {k: frozenset(v) for k, v in out.items()}
        return self._skg

    def _load_rxnorm(self) -> Dict[str, FrozenSet[str]]:
        if self._rx is not None:
            return self._rx
        out: Dict[str, set] = {}
        if self._rxnorm_path and Path(self._rxnorm_path).is_file():
            # Expected TSV: <name>\t<alias>  (both directions added).
            try:
                for line in open(self._rxnorm_path, encoding="utf-8"):
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
                        a, b = parts[0].strip(), parts[1].strip()
                        out.setdefault(a.lower(), set()).add(b)
                        out.setdefault(b.lower(), set()).add(a)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"kb_aliases: failed to load RxNorm {self._rxnorm_path}: {exc}")
        self._rx = {k: frozenset(v) for k, v in out.items()}
        return self._rx

    # ── lookups ───────────────────────────────────────────────────────────
    def abbrevs(self, surface: str) -> List[Tuple[str, str]]:
        """Attested acronym / short-form (and expansion) candidates."""
        key = surface.strip().lower()
        out: List[Tuple[str, str]] = []
        # curated (bidirectional)
        if key in self._curated_abbrev:
            cand = self._curated_abbrev[key]
            if cand.lower() != key:
                out.append((cand, SOURCE_KB_CURATED))
        # simplekg aliases that look acronym-ish
        for a in self._load_simplekg().get(key, ()):  # type: ignore[arg-type]
            if a.lower() != key and _is_acronymish(surface, a):
                out.append((a, SOURCE_KB_SIMPLEKG))
        return _dedup(out)

    def aliases(self, surface: str) -> List[Tuple[str, str]]:
        """Attested replacement-nickname candidates (NOT acronyms)."""
        key = surface.strip().lower()
        out: List[Tuple[str, str]] = []
        for a in _CURATED_ALIAS.get(key, ()):
            if a.lower() != key:
                out.append((a, SOURCE_KB_CURATED))
        for a in self._load_simplekg().get(key, ()):  # type: ignore[arg-type]
            if a.lower() != key and not _is_acronymish(surface, a):
                out.append((a, SOURCE_KB_SIMPLEKG))
        for a in self._load_rxnorm().get(key, ()):  # type: ignore[arg-type]
            if a.lower() != key:
                out.append((a, SOURCE_RXNORM))
        return _dedup(out)


def _dedup(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    seen = set()
    out = []
    for form, src in pairs:
        if form.lower() in seen:
            continue
        seen.add(form.lower())
        out.append((form, src))
    return out
