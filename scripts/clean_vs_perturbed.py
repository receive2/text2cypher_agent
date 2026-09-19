#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/clean_vs_perturbed.py
=============================
Paired clean-vs-perturbed comparison for one generator model.

The perturbed benchmark is a subset of the clean one (only questions with a
groundable entity mention were perturbed), so comparing two whole-run averages
would let the extra, entity-free clean questions inflate the clean score. This
script pairs every perturbed question with its clean original and scores both
runs on exactly those pairs.

Pairing key per dataset (the perturbed row's ``_source_row`` vs the clean run's
``qid``): CypherBench ``qid`` (uuid); Mind-the-Query ``unique_id``; ZOGRASCOPE
``id``. Graph names: Mind-the-Query's clean graph is ``bloom50``, the perturbed
one ``bloom``.

    python scripts/clean_vs_perturbed.py                       # model = eval_config.GENERATOR_LLM
    python scripts/clean_vs_perturbed.py --model gpt-5.6-terra --methods no_val_link cyanchor

Reads the newest run per (pair, method, model) under logs/runs/ for both the
bare and the ``_augmented`` dataset names; writes
``report/<model>/CLEAN_VS_PERTURBED.md`` and prints it.
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import eval_config as cfg   # noqa: E402
import eval_paths           # noqa: E402

METHODS = [("No Val Link", "no_val_link"), ("FCAV", "fcav"), ("ReAct", "react"),
           ("GraphRAG", "graphrag"), ("CyANCHOR", "cyanchor")]
DATASET_LABEL = {"cypherbench": "CypherBench", "mindthequery": "MindTheQuery", "zograscope": "ZOGRASCOPE"}
SOURCE_KEY = {"cypherbench": "qid", "mindthequery": "unique_id", "zograscope": "id"}
CLEAN_GRAPH = {"bloom": "bloom50"}
STRATEGIES = ["casing", "typo", "partial", "abbrev", "alias"]
DIFFICULTIES = ["easy", "medium", "hard"]


def _records(run_dir: Optional[Path]) -> Dict[str, dict]:
    if run_dir is None:
        return {}
    d = Path(run_dir)
    d = d if d.is_absolute() else REPO / d
    f = d / "records.jsonl"
    if not f.is_file():
        return {}
    out = {}
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                out[str(r["qid"])] = r
    return out


def _source(row: dict) -> dict:
    src = row.get("_source_row") or {}
    if isinstance(src, str):
        try:
            src = ast.literal_eval(src)
        except Exception:  # noqa: BLE001
            src = {}
    return src if isinstance(src, dict) else {}


def _pairs_for(dataset: str, graph: str) -> List[Tuple[str, str, dict]]:
    """(perturbed qid, clean qid, perturbed benchmark row) for one graph."""
    rows = json.load(open(REPO / "benchmarks" / f"{dataset}_augmented_v2" / "test.json", encoding="utf-8"))
    key = SOURCE_KEY[dataset]
    out = []
    for r in rows:
        if r.get("graph") != graph:
            continue
        clean_qid = _source(r).get(key)
        if clean_qid is not None:
            out.append((str(r["id"]), str(clean_qid), r))
    return out


def _ea(rs: List[dict]) -> Optional[float]:
    return sum(1.0 for r in rs if r.get("ea") is True) / len(rs) if rs else None


def _psjs(rs: List[dict]) -> Optional[float]:
    if not rs:
        return None
    return sum(float(r["psjs"]) if isinstance(r.get("psjs"), (int, float)) and not isinstance(r.get("psjs"), bool)
               else 0.0 for r in rs) / len(rs)


def _fmt(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.3f}"


def collect(model: str, methods: List[str]) -> Dict[str, List[dict]]:
    """method -> list of paired rows {dataset, graph, strategy, difficulty, clean, pert}."""
    out: Dict[str, List[dict]] = {m: [] for m in methods}
    missing: List[str] = []
    for aug_ds, graph in cfg.FULL_EVAL_PAIRS_13_AUGMENTED:
        dataset = aug_ds[: -len("_augmented")]
        clean_graph = CLEAN_GRAPH.get(graph, graph)
        pairs = _pairs_for(dataset, graph)
        for m in methods:
            seg = eval_paths.method_tag(m)
            clean = _records(eval_paths.latest_run_dir(dataset, clean_graph, seg, model=model))
            pert = _records(eval_paths.latest_run_dir(aug_ds, graph, seg, model=model))
            if not clean or not pert:
                missing.append(f"{dataset}/{graph}/{m}: clean={'yes' if clean else 'MISSING'} perturbed={'yes' if pert else 'MISSING'}")
                continue
            for pq, cq, row in pairs:
                if pq in pert and cq in clean:
                    meta = row.get("_aug_meta") or {}
                    edits = meta.get("edits") or [{}]
                    strategy = edits[0].get("strategy") or meta.get("strategy") or pert[pq].get("strategy") or "?"
                    out[m].append({"dataset": dataset, "graph": graph, "strategy": strategy,
                                   "difficulty": pert[pq].get("difficulty") or "?",
                                   "clean": clean[cq], "pert": pert[pq]})
    for line in missing:
        print("  ! " + line, file=sys.stderr)
    return out


def _table(rows_by_method: Dict[str, List[dict]], methods: List[str], group_field: Optional[str],
           groups: List[str]) -> str:
    labels = dict((m, lab) for lab, m in METHODS)
    head = "| method | " + " | ".join(f"{g} clean | {g} pert. | Δ" for g in groups) + " |\n|---|" + "---:|" * (3 * len(groups))
    lines = [head]
    for m in methods:
        cells = []
        for g in groups:
            rs = [r for r in rows_by_method[m] if group_field is None or r[group_field] == g]
            c, p = _ea([r["clean"] for r in rs]), _ea([r["pert"] for r in rs])
            cells += [_fmt(c), _fmt(p), ("—" if c is None or p is None else f"{p - c:+.3f}")]
        lines.append(f"| {labels[m]} | " + " | ".join(cells) + " |")
    n = "| n | " + " | ".join(f"{len([r for r in rows_by_method[methods[0]] if group_field is None or r[group_field] == g])} | | " for g in groups) + "|"
    lines.append(n)
    return "\n".join(lines)


def render(model: str, data: Dict[str, List[dict]], methods: List[str]) -> str:
    labels = dict((m, lab) for lab, m in METHODS)
    ds_present = [d for d in DATASET_LABEL if any(r["dataset"] == d for m in methods for r in data[m])]
    L = [f"# Clean vs. perturbed — `{model}`", "",
         "Execution accuracy on **paired** questions: every perturbed question scored next to its clean original "
         "(same gold Cypher, same graph); clean questions without a perturbed counterpart are excluded. "
         "Errored questions score 0. Δ = perturbed − clean.", ""]
    L += ["## By dataset", "", _table(data, methods, "dataset", ds_present).replace("| method |", "| method |")]
    # dataset labels
    for d in ds_present:
        L[-1] = L[-1].replace(f"{d} clean", f"{DATASET_LABEL[d]} clean").replace(f"{d} pert.", f"{DATASET_LABEL[d]} pert.")
    L += ["", "## All datasets pooled", "", _table(data, methods, None, ["all"]), ""]
    # flips
    L += ["## Question flips (pooled)", "", "| method | clean ✓ → pert. ✗ | clean ✗ → pert. ✓ | both ✓ | both ✗ | n |", "|---|---:|---:|---:|---:|---:|"]
    for m in methods:
        rs = data[m]
        cp = lambda r: r["clean"].get("ea") is True
        pp = lambda r: r["pert"].get("ea") is True
        L.append(f"| {labels[m]} | {sum(1 for r in rs if cp(r) and not pp(r))} | {sum(1 for r in rs if not cp(r) and pp(r))} | "
                 f"{sum(1 for r in rs if cp(r) and pp(r))} | {sum(1 for r in rs if not cp(r) and not pp(r))} | {len(rs)} |")
    strategies = [s for s in STRATEGIES if any(r["strategy"] == s for m in methods for r in data[m])]
    L += ["", "## By perturbation strategy (pooled)", "", _table(data, methods, "strategy", strategies)]
    diffs = [d for d in DIFFICULTIES if any(r["difficulty"] == d for m in methods for r in data[m])]
    L += ["", "## By query difficulty (pooled)", "", _table(data, methods, "difficulty", diffs)]
    L += ["", "## PSJS (pooled)", "", "| method | clean | perturbed | Δ |", "|---|---:|---:|---:|"]
    for m in methods:
        c, p = _psjs([r["clean"] for r in data[m]]), _psjs([r["pert"] for r in data[m]])
        L.append(f"| {labels[m]} | {_fmt(c)} | {_fmt(p)} | {'—' if c is None or p is None else f'{p - c:+.3f}'} |")
    L += ["", "## Per graph", "", "| dataset | graph | n | " + " | ".join(f"{labels[m]} clean | {labels[m]} pert." for m in methods) + " |",
          "|---|---|---:|" + "---:|" * (2 * len(methods))]
    for aug_ds, g in cfg.FULL_EVAL_PAIRS_13_AUGMENTED:
        d = aug_ds[: -len("_augmented")]
        cells = []
        n = 0
        for m in methods:
            rs = [r for r in data[m] if r["graph"] == g and r["dataset"] == d]
            n = max(n, len(rs))
            cells += [_fmt(_ea([r["clean"] for r in rs])), _fmt(_ea([r["pert"] for r in rs]))]
        L.append(f"| {DATASET_LABEL[d]} | {g} | {n} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None, help="generator preset (default: eval_config.GENERATOR_LLM)")
    ap.add_argument("--methods", nargs="+", default=["no_val_link"], choices=[m for _, m in METHODS])
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    model = args.model or str(cfg.GENERATOR_LLM)
    data = collect(model, args.methods)
    if not any(data.values()):
        print("no paired records found — run the clean and perturbed sides first", file=sys.stderr)
        return 1
    text = render(model, data, args.methods)
    out = Path(args.out) if args.out else REPO / cfg.REPORT_DIR / model / "CLEAN_VS_PERTURBED.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"[clean_vs_perturbed] wrote {out.relative_to(REPO)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
