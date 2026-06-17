#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verification_sample.py
======================
Build the seeded, stratified, **blinded** human-verification queues for the
entity-perturbed benchmark, per docs/VERIFICATION_PROTOCOL.md.

Coverage (by provenance of each perturbation's single edit):
  * Tier 1 — FULL CENSUS of LLM-proposed + attested/KB edits (corruption-prone).
  * Tier 2 — POWERED STRATIFIED SAMPLE of purely-algorithmic edits
             (casing / typo / rule-based partial), to *measure* (not assume)
             their validity rate.

Each selected item is assigned to a rotating pair of annotators (double
annotation). Outputs:
  * <out>/verification_key.csv          — full metadata incl. provenance/tier
                                          (the un-blinded key; NOT for annotators)
  * <out>/verification_annotator_<X>.csv — one blind queue per annotator
                                          (provenance/tier hidden; empty label cols)

Determinism: everything is driven by --seed; re-running with the same seed and
inputs reproduces identical queues.

Usage
-----
    python scripts/verification_sample.py --out verification/ \
        --annotators 3 --seed 42 \
        --sample-typo 300 --sample-partial 200 --sample-casing 150

Dataset inputs: pass `--data name=path ...`, or rely on the
`*_AUGMENTED_PATH` constants in eval_config.py when importable.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Annotator-facing columns (blind: NO provenance / tier).
_BLIND_COLUMNS = [
    "id", "dataset", "graph", "strategy",
    "original_entity", "perturbed_form", "property", "augmented_question",
    # to be filled by the annotator:
    "validity", "naturalness", "source_error", "corrected_form", "notes",
]
_KEY_COLUMNS = [
    "id", "source_id", "dataset", "graph", "strategy", "provenance", "tier",
    "label", "prop", "original_entity", "perturbed_form",
    "augmented_question", "assigned_annotators",
]

_ATTESTED_KEYS = ("kb", "attest", "wikidata", "simplekg", "alias_table")


def _provenance(source: str) -> str:
    s = (source or "").lower()
    if "llm" in s:
        return "llm"
    if any(k in s for k in _ATTESTED_KEYS):
        return "attested"
    return "algorithmic"


def _default_datasets() -> Dict[str, str]:
    """Best-effort dataset paths from eval_config (optional)."""
    try:
        import eval_config as cfg  # noqa: WPS433
    except Exception:
        return {}
    out = {}
    for name, attr in (
        ("cypherbench", "CYPHERBENCH_AUGMENTED_PATH"),
        ("mindthequery", "MINDTHEQUERY_AUGMENTED_PATH"),
        ("zograscope", "ZOGRASCOPE_AUGMENTED_PATH"),
    ):
        p = getattr(cfg, attr, None)
        if p and os.path.exists(p):
            out[name] = p
    return out


def _load_examples(datasets: Dict[str, str]) -> List[Dict[str, Any]]:
    """Flatten every perturbation into a verification record."""
    recs: List[Dict[str, Any]] = []
    for ds_name, path in datasets.items():
        if not os.path.exists(path):
            print(f"  ! dataset path missing, skipping: {ds_name} -> {path}", file=sys.stderr)
            continue
        rows = json.load(open(path, encoding="utf-8"))
        for i, x in enumerate(rows):
            meta = x.get("_aug_meta") or {}
            edits = meta.get("edits") or []
            if not edits or not isinstance(edits[0], dict):
                continue
            e = edits[0]
            frm, to, strat = e.get("from"), e.get("to"), e.get("strategy")
            if not (frm and to and strat):
                continue
            # Globally-unique id: dataset-prefixed row index. (Source datasets
            # reuse their own `id`/`qid` across graphs — e.g. Mind-the-Query's
            # "Complex_Retrieval_test:163" — so we never key on it directly.)
            rid = f"{ds_name}:{i}"
            recs.append({
                "id": rid,
                "source_id": str(x.get("id") or x.get("qid") or ""),
                "dataset": ds_name,
                "graph": x.get("graph", ""),
                "strategy": strat,
                "provenance": _provenance(e.get("source") or ""),
                "label": e.get("label") or "",
                "prop": e.get("prop") or "",
                "original_entity": frm,
                "perturbed_form": to,
                "augmented_question": x.get("nl") or x.get("question") or "",
            })
    return recs


def _select(
    recs: List[Dict[str, Any]],
    rng: random.Random,
    sample_sizes: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Tier 1 census (llm + attested) + Tier 2 sample (algorithmic)."""
    selected: List[Dict[str, Any]] = []
    # Tier 1 — census of human/KB-mediated edits.
    for r in recs:
        if r["provenance"] in ("llm", "attested"):
            r["tier"] = "1-census"
            selected.append(r)
    # Tier 2 — stratified sample of algorithmic edits, per strategy.
    by_strat: Dict[str, List[Dict[str, Any]]] = {}
    for r in recs:
        if r["provenance"] == "algorithmic":
            by_strat.setdefault(r["strategy"], []).append(r)
    for strat, pool in by_strat.items():
        k = sample_sizes.get(strat, sample_sizes.get("_default", 150))
        pool_sorted = sorted(pool, key=lambda r: r["id"])  # stable before sampling
        take = pool_sorted if k >= len(pool_sorted) else rng.sample(pool_sorted, k)
        for r in take:
            r["tier"] = "2-sample"
            selected.append(r)
    return selected


def _assign_pairs(
    selected: List[Dict[str, Any]],
    rng: random.Random,
    n_annotators: int,
) -> List[str]:
    """Round-robin assign each item a rotating annotator pair (double annotation)."""
    names = [chr(ord("A") + i) for i in range(n_annotators)]
    pairs = list(combinations(names, 2)) if n_annotators >= 2 else [(names[0],)]
    rng.shuffle(selected)  # seeded
    for idx, r in enumerate(selected):
        r["assigned"] = pairs[idx % len(pairs)]
    return names


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="verification", help="output directory")
    ap.add_argument("--annotators", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample-typo", type=int, default=300)
    ap.add_argument("--sample-partial", type=int, default=200)
    ap.add_argument("--sample-casing", type=int, default=150)
    ap.add_argument("--sample-default", type=int, default=150,
                    help="sample size for any other algorithmic strategy")
    ap.add_argument("--data", action="append", default=[],
                    metavar="NAME=PATH", help="dataset (repeatable); overrides eval_config")
    args = ap.parse_args(argv)

    datasets = dict(kv.split("=", 1) for kv in args.data) if args.data else _default_datasets()
    if not datasets:
        print("ERROR: no datasets. Pass --data name=path or set *_AUGMENTED_PATH in eval_config.py.",
              file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    recs = _load_examples(datasets)
    print(f"Loaded {len(recs)} perturbations from {len(datasets)} dataset(s).")

    sample_sizes = {
        "typo": args.sample_typo, "partial": args.sample_partial,
        "casing": args.sample_casing, "_default": args.sample_default,
    }
    selected = _select(recs, rng, sample_sizes)
    names = _assign_pairs(selected, rng, args.annotators)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Key file (un-blinded).
    with open(out / "verification_key.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_KEY_COLUMNS)
        w.writeheader()
        for r in selected:
            w.writerow({
                "id": r["id"], "source_id": r.get("source_id", ""),
                "dataset": r["dataset"], "graph": r["graph"],
                "strategy": r["strategy"], "provenance": r["provenance"], "tier": r["tier"],
                "label": r["label"], "prop": r["prop"],
                "original_entity": r["original_entity"], "perturbed_form": r["perturbed_form"],
                "augmented_question": r["augmented_question"],
                "assigned_annotators": ";".join(r["assigned"]),
            })

    # Per-annotator blind queues.
    per: Dict[str, List[Dict[str, Any]]] = {n: [] for n in names}
    for r in selected:
        for n in r["assigned"]:
            per[n].append(r)
    for n in names:
        items = sorted(per[n], key=lambda r: r["id"])
        with open(out / f"verification_annotator_{n}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=_BLIND_COLUMNS)
            w.writeheader()
            for r in items:
                w.writerow({
                    "id": r["id"], "dataset": r["dataset"], "graph": r["graph"],
                    "strategy": r["strategy"],
                    "original_entity": r["original_entity"], "perturbed_form": r["perturbed_form"],
                    "property": f"{r['label']}.{r['prop']}" if r["label"] else "",
                    "augmented_question": r["augmented_question"],
                    "validity": "", "naturalness": "", "source_error": "",
                    "corrected_form": "", "notes": "",
                })

    # Summary.
    from collections import Counter
    tier_c = Counter(r["tier"] for r in selected)
    strat_prov = Counter((r["strategy"], r["provenance"]) for r in selected)
    print(f"\nSelected {len(selected)} items "
          f"(Tier1 census={tier_c['1-census']}, Tier2 sample={tier_c['2-sample']}).")
    print("By strategy x provenance:")
    for (s, p), c in sorted(strat_prov.items()):
        print(f"  {s:9} {p:11} {c}")
    print(f"\nDouble annotation -> {len(selected) * 2} judgments across "
          f"{args.annotators} annotators (~{len(selected) * 2 // args.annotators} each).")
    print(f"Wrote: {out}/verification_key.csv + verification_annotator_{{{','.join(names)}}}.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
