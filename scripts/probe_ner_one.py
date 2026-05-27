#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/probe_ner_one.py
========================
Single-example NER pipeline probe.

Why
---
The aggregate eval shows `node_only` and `no_ner` NER modes produce
essentially identical EA on cypherbench_augmented__movie (Δ ≈ 0.2 pp).
That could mean either:

  (A) NER pipeline is working but the augmented split barely tests it
      (only ~12% of rows have entity-surface perturbations).
  (B) NER pipeline is silently broken — `node_only` mode runs the agent
      but produces empty / wrong / unused entities.

To disambiguate we run ONE partial-name example end-to-end in
`node_only` mode with `verbose=True` and inspect exactly what gets
injected into the Cypher prompt's `{relevant_entities}` slot.

Default example
---------------
qid `8ae5de16` — a partial-name augmented row where the gold canonical
entity ('Amanda Award for Best Foreign Feature Film') is truncated in
the question to 'Award for Best Foreign Feature Film'. If NER works,
`{relevant_entities}` should contain the full canonical name pulled
from the Award nodes via FAISS lookup.

Usage
-----
::

    python -m scripts.probe_ner_one                       # default qid
    python -m scripts.probe_ner_one --qid 110312ee        # different example
    python -m scripts.probe_ner_one --mode full           # try "full" mode
    python -m scripts.probe_ner_one --mode no_ner         # baseline (entities="{}")

Outputs
-------
Prints (in order):
  1. The question text (augmented surface).
  2. The original (non-augmented) question for reference.
  3. NER mode resolved.
  4. The `{relevant_entities}` payload injected into the Cypher prompt.
  5. The generated Cypher.
  6. The gold Cypher.
  7. A coarse pass/fail signal (does the canonical entity appear in the pred?).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# 1. Env bridge — set NEO4J_* BEFORE importing ner_agent_auto
# ──────────────────────────────────────────────────────────────────────────────

def _bridge_env(graph: str = "movie") -> None:
    """Look up the movie graph's GraphConn and push it into NEO4J_* env vars."""
    # Import is local so we can bridge env vars before the agent stack pulls them.
    from eval_config import GRAPH_CONNS

    key = ("cypherbench_augmented", graph)
    if key not in GRAPH_CONNS:
        # Fall back to the base sibling — augmented variants share the same DB.
        key = ("cypherbench", graph)
    if key not in GRAPH_CONNS:
        raise SystemExit(
            f"probe_ner_one: no GraphConn for {key!r} in eval_config.GRAPH_CONNS."
        )

    conn = GRAPH_CONNS[key]
    os.environ["NEO4J_URI"]      = conn.uri
    os.environ["NEO4J_USERNAME"] = conn.user
    os.environ["NEO4J_PASSWORD"] = conn.password
    os.environ.setdefault("NEO4J_DATABASE", "neo4j")
    print(f"[env] NEO4J_URI={conn.uri}  user={conn.user}")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Locate the example by qid
# ──────────────────────────────────────────────────────────────────────────────

# Default = the canonical partial-name example we've been discussing.
_DEFAULT_QID = "8ae5de16-66e3-4f25-9ee1-3b8cc4716876"

# Resolve via test.json under the augmented dataset.  We pick up the path
# from eval_config so it stays in sync.
def _load_example(qid_prefix: str, graph: str) -> dict:
    from eval_config import CYPHERBENCH_AUGMENTED_PATH

    aug_path = Path(CYPHERBENCH_AUGMENTED_PATH)
    if not aug_path.exists():
        raise SystemExit(f"probe_ner_one: dataset file not found: {aug_path}")

    with aug_path.open() as f:
        rows = json.load(f)

    # qid_prefix can be a full qid or just the first 8 chars (matches our
    # bucket_failures.py output convention).
    for r in rows:
        rid = r.get("qid") or r.get("id") or ""
        if rid.startswith(qid_prefix) and r.get("graph") == graph:
            return r
    raise SystemExit(
        f"probe_ner_one: no row with qid prefix {qid_prefix!r} on graph "
        f"{graph!r} in {aug_path.name}."
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. Run the pipeline
# ──────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.probe_ner_one")
    ap.add_argument(
        "--qid",
        default=_DEFAULT_QID,
        help="Full qid or 8-char prefix (default = partial-name example "
             "'Award for Best Foreign Feature Film').",
    )
    ap.add_argument(
        "--graph",
        default="movie",
        help="Graph name (default 'movie').",
    )
    ap.add_argument(
        "--mode",
        choices=["full", "node_only", "no_ner"],
        default="node_only",
        help="NER mode override (default 'node_only' — the one the paper "
             "claims should rescue partial-name entities).",
    )
    args = ap.parse_args(argv)

    # ── Step 1: env vars before agent import ──────────────────────────────────
    _bridge_env(graph=args.graph)

    # ── Step 2: locate the example ────────────────────────────────────────────
    ex = _load_example(args.qid, args.graph)
    aug_meta = ex.get("_aug_meta") or {}
    edits    = aug_meta.get("edits") or []

    nl_question = ex.get("nl_question") or ex.get("question") or ""
    gold_cypher = ex.get("gold_cypher") or ""
    original_q  = aug_meta.get("original_nl", "<not recorded>")

    print()
    print("=" * 72)
    print(f"qid          : {ex.get('qid','?')}")
    print(f"graph        : {ex.get('graph','?')}")
    print(f"NER mode     : {args.mode}")
    print(f"augmenters   : {[e.get('strategy') for e in edits] or '<none>'}")
    if edits:
        for e in edits:
            print(f"  edit       : '{e.get('from')}'  →  '{e.get('to')}'  "
                  f"(strategy={e.get('strategy')})")
    print("-" * 72)
    print(f"original     : {original_q}")
    print(f"augmented Q  : {nl_question}")
    print("-" * 72)
    print(f"gold cypher  :")
    for line in gold_cypher.splitlines() or [gold_cypher]:
        print(f"   {line}")
    print("=" * 72)
    print()

    # ── Step 3: run the pipeline ──────────────────────────────────────────────
    # NB: importing ner_agent_auto triggers load_dotenv() + Neo4j driver
    # construction.  Env vars must be set above this point.
    from ner_agent_auto import ask_auto

    out = ask_auto(
        prompt  = nl_question,
        verbose = True,
        mode    = args.mode,
    )

    # ── Step 4: post-mortem ───────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("PROBE RESULTS")
    print("=" * 72)
    entities = out.get("entities", "<no entities key>")
    cypher   = out.get("cypher",   "<no cypher key>")

    print(f"entities (raw)  : {entities}")
    print()
    print("pred cypher     :")
    for line in (cypher or "").splitlines() or [cypher or ""]:
        print(f"   {line}")
    print()

    # Quick heuristic: did NER recover any canonical name from the gold
    # that the question's surface didn't already contain?
    import re
    gold_names = set(re.findall(r"\{name:\s*'([^']+)'\}", gold_cypher))
    print(f"gold canonical names : {sorted(gold_names)}")
    for gn in sorted(gold_names):
        in_q       = gn.lower() in nl_question.lower()
        in_ents    = gn.lower() in (entities or "").lower()
        in_pred    = gn.lower() in (cypher or "").lower()
        verdict    = (
            "✓ trivially copyable from question"   if in_q else
            "✓ recovered by NER and used in Cypher" if (in_ents and in_pred) else
            "✓ recovered by NER but NOT used"      if (in_ents and not in_pred) else
            "✗ NER did NOT recover it"             if not in_ents else
            "?"
        )
        print(f"  '{gn}'")
        print(f"     in question? {in_q}")
        print(f"     in entities? {in_ents}")
        print(f"     in pred?     {in_pred}")
        print(f"     verdict:     {verdict}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
