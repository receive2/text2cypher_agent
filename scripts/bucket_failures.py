#!/usr/bin/env python3
"""
Bucket Text-to-Cypher failure records into three categories:

  1. NER          – entity string literal extracted/normalized incorrectly
                    (pred uses a literal not in gold, or vice versa)
  2. TOOL_SELECT  – wrong schema elements: Label / RelType / property name
                    (pred picks a different label/rel/prop than gold)
  3. CYPHER_GEN   – schema + literals match gold, but query structure is wrong
                    (UNION vs OR, missing aggregation, wrong RETURN/ORDER)

Plus auxiliary buckets:
  4. RUNTIME      – the agent threw before producing a Cypher (ea is None)
  5. EMPTY_PRED   – pred is empty / too short to be a real query
  6. PARTIAL_OK   – psjs >= 0.8 but ea=False (often LIMIT / alias artifacts)

The classification is multi-label friendly: a record can fall into NER
*and* TOOL_SELECT simultaneously. We report:
  - primary bucket = first failing layer in the pipeline order
  - co-occurrence matrix
  - 5 representative examples per bucket

Run:
  python scripts/bucket_failures.py logs/eval/cypherbench__movie.records.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

# --- regexes over Cypher text -------------------------------------------------

# String literals: single- or double-quoted, no escape handling needed for this scan
RE_STR_LITERAL = re.compile(r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")
# Node labels: :Label  (after a colon in node pattern)
RE_LABEL = re.compile(r"[\(,\s]\s*(?:\w+\s*)?:([A-Z][A-Za-z0-9_]*)")
# Relationship types: [:REL]  or  [r:REL]
RE_REL = re.compile(r"\[\s*\w*\s*:([A-Za-z_][A-Za-z0-9_]*)")
# Property accesses: foo.bar
RE_PROP = re.compile(r"\b([a-z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
# Cypher keywords that signal structural ops
STRUCTURAL_KEYWORDS = {
    "UNION", "CALL", "OPTIONAL", "WITH", "COUNT", "DISTINCT",
    "GROUP", "ORDER", "LIMIT", "COLLECT", "SUM", "AVG", "MAX", "MIN",
}


def extract_literals(cypher: str) -> set[str]:
    if not cypher:
        return set()
    out = set()
    for m in RE_STR_LITERAL.finditer(cypher):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        if s and not s.isdigit():
            out.add(s.strip().lower())
    return out


def extract_labels(cypher: str) -> set[str]:
    if not cypher:
        return set()
    return {m.group(1) for m in RE_LABEL.finditer(cypher)}


def extract_rels(cypher: str) -> set[str]:
    if not cypher:
        return set()
    return {m.group(1) for m in RE_REL.finditer(cypher)}


def extract_props(cypher: str) -> set[str]:
    if not cypher:
        return set()
    # only the property name (after the dot), not the variable
    return {m.group(2).lower() for m in RE_PROP.finditer(cypher)}


def extract_structural(cypher: str) -> set[str]:
    if not cypher:
        return set()
    upper = cypher.upper()
    return {kw for kw in STRUCTURAL_KEYWORDS if re.search(rf"\b{kw}\b", upper)}


# --- classifier ---------------------------------------------------------------

def classify(rec: dict) -> dict:
    """Return dict of {bucket: bool, ...} plus diagnostic deltas."""
    out = {
        "RUNTIME": False, "EMPTY_PRED": False,
        "NER": False, "TOOL_SELECT": False, "CYPHER_GEN": False,
        "PARTIAL_OK": False,
        "label_delta": [], "rel_delta": [], "prop_delta": [],
        "literal_only_in_gold": [], "literal_only_in_pred": [],
        "structural_delta": [],
    }

    if rec.get("error"):
        out["RUNTIME"] = True
        return out

    pred = (rec.get("pred_cypher") or "").strip()
    gold = (rec.get("gold_cypher") or "").strip()
    if len(pred) < 15 or "MATCH" not in pred.upper():
        out["EMPTY_PRED"] = True
        return out

    gold_lit, pred_lit = extract_literals(gold), extract_literals(pred)
    gold_lab, pred_lab = extract_labels(gold), extract_labels(pred)
    gold_rel, pred_rel = extract_rels(gold), extract_rels(pred)
    gold_pr,  pred_pr  = extract_props(gold), extract_props(pred)
    gold_st,  pred_st  = extract_structural(gold), extract_structural(pred)

    # NER: literal sets differ. Only flag when gold has values pred missed
    # (or pred invented values not in gold).
    lit_miss = gold_lit - pred_lit
    lit_extra = pred_lit - gold_lit
    if lit_miss or lit_extra:
        out["NER"] = True
        out["literal_only_in_gold"] = sorted(lit_miss)[:5]
        out["literal_only_in_pred"] = sorted(lit_extra)[:5]

    # TOOL_SELECT: schema-element mismatch
    lab_delta = gold_lab.symmetric_difference(pred_lab)
    rel_delta = gold_rel.symmetric_difference(pred_rel)
    # Property delta is unreliable because gold often uses inline syntax
    # `{name: 'X'}` while pred uses `var.name = 'X'`; a `name` mismatch is
    # therefore a false positive. Restrict prop check to non-`name` props.
    pr_delta = {p for p in gold_pr.symmetric_difference(pred_pr) if p != "name"}
    if lab_delta or rel_delta or pr_delta:
        out["TOOL_SELECT"] = True
        out["label_delta"] = sorted(lab_delta)
        out["rel_delta"] = sorted(rel_delta)
        out["prop_delta"] = sorted(pr_delta)

    # CYPHER_GEN: schema and literals match, but structure differs
    struct_delta = gold_st.symmetric_difference(pred_st)
    if not out["NER"] and not out["TOOL_SELECT"]:
        if struct_delta or rec.get("psjs", 0) < 0.99:
            out["CYPHER_GEN"] = True
            out["structural_delta"] = sorted(struct_delta)

    # Partial-OK overlay: psjs high but ea=False (likely cosmetic)
    if (rec.get("psjs") or 0) >= 0.8 and rec.get("ea") is False:
        out["PARTIAL_OK"] = True

    return out


def primary_bucket(c: dict) -> str:
    # pipeline order: RUNTIME > EMPTY > NER > TOOL > CYPHER > PARTIAL_OK > UNKNOWN
    for k in ("RUNTIME", "EMPTY_PRED", "NER", "TOOL_SELECT", "CYPHER_GEN"):
        if c[k]:
            return k
    if c["PARTIAL_OK"]:
        return "PARTIAL_OK"
    return "UNKNOWN"


# --- driver -------------------------------------------------------------------

def load_records(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(l) for l in f if l.strip()]


def report(records: list[dict]) -> None:
    total = len(records)
    fails = [r for r in records if r.get("ea") is not True]
    print(f"Total records  : {total}")
    print(f"EA=True (pass) : {total - len(fails)}")
    print(f"Failures       : {len(fails)}  ({100*len(fails)/total:.1f}%)\n")

    primary = Counter()
    multi = Counter()  # co-occurrence
    enriched = []
    for r in fails:
        c = classify(r)
        enriched.append((r, c))
        primary[primary_bucket(c)] += 1
        tags = tuple(sorted(k for k in ("NER", "TOOL_SELECT", "CYPHER_GEN") if c[k]))
        if tags:
            multi[tags] += 1

    print("PRIMARY BUCKET (first failing layer):")
    for k, v in primary.most_common():
        print(f"  {k:14s} {v:4d}  ({100*v/len(fails):5.1f}%)")

    print("\nCO-OCCURRENCE (NER / TOOL_SELECT / CYPHER_GEN tag set):")
    for tags, v in sorted(multi.items(), key=lambda kv: -kv[1]):
        print(f"  {'+'.join(tags) or '<none>':40s} {v:4d}")

    # Cross-tab: among failures, how many are "answer is right but ea fails"
    partial = sum(1 for _, c in enriched if c["PARTIAL_OK"])
    cypher_high_psjs = sum(
        1 for r, c in enriched
        if c["CYPHER_GEN"] and isinstance(r.get("psjs"), (int, float)) and r["psjs"] >= 0.8
    )
    print(f"\nOVERLAY:")
    print(f"  PARTIAL_OK (psjs>=0.8 but ea=False)      : {partial:4d}  ({100*partial/len(fails):5.1f}% of fails)")
    print(f"  CYPHER_GEN with high psjs (>=0.8)        : {cypher_high_psjs:4d}  "
          f"(near-misses: schema right, structure off)")

    # UNION vs OR signal — direct check
    union_vs_or = 0
    for r, c in enriched:
        gold = (r.get("gold_cypher") or "").upper()
        pred = (r.get("pred_cypher") or "").upper()
        if "UNION" in gold and "UNION" not in pred and (" OR " in pred or "OPTIONAL MATCH" in pred):
            union_vs_or += 1
    print(f"  Gold uses UNION but pred uses OR/OPTIONAL: {union_vs_or:4d}  "
          f"(systematic disjunction mistranslation)")

    print("\n=== Representative examples (3 per primary bucket) ===")
    by_bucket: dict[str, list] = defaultdict(list)
    for r, c in enriched:
        by_bucket[primary_bucket(c)].append((r, c))
    for bucket, items in by_bucket.items():
        print(f"\n--- {bucket} ({len(items)}) ---")
        for r, c in items[:3]:
            print(f"  Q: {r['question'][:140]}")
            if c["literal_only_in_gold"]:
                print(f"    NER missing literals : {c['literal_only_in_gold']}")
            if c["literal_only_in_pred"]:
                print(f"    NER extra literals   : {c['literal_only_in_pred']}")
            if c["label_delta"]:
                print(f"    Label delta          : {c['label_delta']}")
            if c["rel_delta"]:
                print(f"    Rel delta            : {c['rel_delta']}")
            if c["prop_delta"]:
                print(f"    Prop delta           : {c['prop_delta']}")
            if c["structural_delta"]:
                print(f"    Structural delta     : {c['structural_delta']}")
            psjs = r.get('psjs')
            psjs_str = f"{psjs:.3f}" if isinstance(psjs, (int, float)) else "n/a"
            print(f"    psjs={psjs_str}  ea={r.get('ea')}")


if __name__ == "__main__":
    paths = [Path(p) for p in sys.argv[1:]] or [
        Path("logs/eval/cypherbench__movie.records.jsonl")
    ]
    for p in paths:
        print(f"\n========== {p} ==========")
        report(load_records(p))
