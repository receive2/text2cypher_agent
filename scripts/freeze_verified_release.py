#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
freeze_verified_release.py
==========================
Apply the human-verification verdicts to the frozen v2.1 generation set and
freeze the result as the verified release: new benchmark files, a new decision
manifest, a complete row-level decision log, and the list of rows the
verification removed (``removed_rows.jsonl`` next to the manifest — readers of
evaluation records drop these rows, so runs made on an earlier release are
re-read on the released rows without re-running anything).

The verdict rules (docs/VERIFICATION_PROTOCOL.md §5) are the same for every
tier:

  source_error                                -> remove
  invalid, LLM-proposed / attested edit,
      certified prior algorithmic form exists -> revert to that form
      no certified prior form                 -> remove
  invalid, rule-based edit                    -> remove (a rule-based edit has
                                                 no verified replacement form)
  valid + unnatural (any rater)               -> remove   (--naturalness, default)
  valid + awkward                             -> keep     (--naturalness drop-both
                                                 removes these too)
  pending (raters disagree / unsure)          -> refuse to freeze (--pending block)
                                                 until adjudicated; keep / drop
                                                 only for provisional bounds
  calibration items                           -> organizer reference answer:
                                                 invalid -> remove (their
                                                 main-queue labels are never
                                                 used, per pre-registration)
  rows never sampled for review               -> keep

Reverting to a prior LLM- or KB-sourced form is prohibited (never verified);
only ``audit/prior_forms.csv`` rows with ``revert_certified == yes`` qualify. A
reverted row's question is re-derived through the same word-boundary
replacement the release rebuild uses, and its difficulty class is recomputed
with the same classifier that produced the frozen classes.

Contingency (pre-registered): if the invalid rate among census rows without a
certified prior form exceeds 20%, the pre-registered fallback is a different
procedure; this script stops and says so (``--force`` to proceed anyway).

Verdicts come from ``verification_stats.collect_labels`` — the same code the
statistics report uses — so what the paper says was removed is exactly what
was removed. The new manifest verifies with ``rebuild_from_manifest.py``, and
every v2.1 row's fate is in ``audit/verification/decisions.csv``.

Usage
-----
    # 1. before adjudication: what would happen, plus the raw artifacts
    python scripts/freeze_verified_release.py --dry-run
    python scripts/freeze_verified_release.py --export-artifacts-only

    # 2. after adjudication (verification/adjudicated.csv filled in):
    python scripts/freeze_verified_release.py --adjudicated verification/adjudicated.csv
    python scripts/rebuild_from_manifest.py          # three-way check of the new manifest
    python scripts/render_datasheet_tables.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import rebuild_from_manifest as rb                                   # noqa: E402
from verification_stats import (collect_labels, expand_paths,        # noqa: E402
                                _annotator_name, _norm, resolve_calibration_paths)
from grounding_probe import _classify as grounding_class             # noqa: E402
from data_augmentation.pipeline import _replace_all                  # noqa: E402

CENSUS = {"llm", "attested"}
CONTINGENCY_RATE = 0.20


# ── decision logic (pure) ─────────────────────────────────────────────────────

def decide(tier: str, final: str, naturalness: List[str], has_prior: bool,
           naturalness_policy: str, pending_policy: str) -> Tuple[str, str]:
    """One queue item -> (action, reason). Actions are ``keep:*``, ``remove:*``,
    ``revert:*`` or ``pending``."""
    if final == "source_error":
        return "remove:source_error", "a rater flagged the source item itself as broken"
    if final == "invalid":
        if tier in CENSUS:
            if has_prior:
                return "revert:prior_algorithmic", "census-rejected; certified prior algorithmic form exists"
            return "remove:invalid", "census-rejected; no certified prior form"
        return "remove:invalid", "rejected rule-based edit; no verified replacement form"
    if final == "pending":
        if pending_policy == "keep":
            return "keep:pending", "provisional: unresolved disagreement kept"
        if pending_policy == "drop":
            return "remove:pending", "provisional: unresolved disagreement dropped"
        return "pending", "awaiting adjudication"
    # valid
    nat = set(naturalness)
    if naturalness_policy != "keep":
        if "unnatural" in nat:
            return "remove:unnatural", "valid but a rater judged it a form nobody would write"
        if naturalness_policy == "drop-both" and "awkward" in nat:
            return "remove:awkward", "valid but a rater judged it stilted (drop-both policy)"
    return "keep:valid", "valid"


# ── inputs ────────────────────────────────────────────────────────────────────

def load_rater_fields(patterns: List[str], skip_ids: set) -> Dict[str, Dict[str, dict]]:
    """id -> annotator -> {validity, naturalness, source_error, corrected_form, notes}."""
    out: Dict[str, Dict[str, dict]] = defaultdict(dict)
    for f in expand_paths(patterns):
        ann = _annotator_name(f)
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            if row["id"] in skip_ids:
                continue
            out[row["id"]][ann] = {k: (row.get(k) or "").strip()
                                   for k in ("validity", "naturalness", "source_error",
                                             "corrected_form", "notes")}
    return out


def load_prior_forms(path: str) -> Dict[Tuple[str, str, str], dict]:
    return {(r["dataset"], r["graph"], r["id"]): r
            for r in csv.DictReader(open(path, encoding="utf-8-sig"))
            if (r.get("revert_certified") or "").strip() == "yes"}


def load_calibration_key(path: Optional[str]) -> Dict[str, str]:
    if not path or not os.path.exists(path):
        return {}
    return {r["id"]: _norm(r.get("ref_validity")) for r in csv.DictReader(open(path, encoding="utf-8-sig"))}


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default="verification/verification_key.csv")
    ap.add_argument("--annotations", nargs="+",
                    default=["verification/returns/annotator_*/verification_annotator_*.REPAIRED.csv"])
    ap.add_argument("--adjudicated", default=None, help="id,validity CSV from adjudication")
    ap.add_argument("--calibration", nargs="*", default=None,
                    help="calibration id files (default: auto-detect next to --key)")
    ap.add_argument("--calibration-key", default=None,
                    help="organizer reference answers (default: calibration_key.csv next to --key)")
    ap.add_argument("--prior-forms", default="audit/prior_forms.csv")
    ap.add_argument("--manifest-in", default=str(rb.MANIFEST_V21),
                    help="the frozen generation set the verdicts are applied to (v2.1)")
    ap.add_argument("--manifest-out", default=str(REPO / "benchmarks" / "release_manifest_v2.3.jsonl"))
    ap.add_argument("--removed-out", default=None,
                    help="rows the verification removed, one JSON line each (default: removed_rows.jsonl "
                         "next to --manifest-out)")
    ap.add_argument("--version", default=f"v2.3-verified-{date.today().isoformat()}")
    ap.add_argument("--benchmarks-dir", default=None,
                    help="write <dir>/<dataset>/test.json instead of the configured release paths (tests)")
    ap.add_argument("--pending", choices=("block", "keep", "drop"), default="block")
    ap.add_argument("--naturalness", choices=("drop-unnatural", "drop-both", "keep"),
                    default="drop-unnatural")
    ap.add_argument("--export-dir", default="audit/verification")
    ap.add_argument("--dry-run", action="store_true",
                    help="decide and report; freeze nothing (the raw verification artifacts "
                         "and decisions.preview.csv are still written to --export-dir)")
    ap.add_argument("--export-artifacts-only", action="store_true",
                    help="write the raw verification artifacts (verdicts, key, calibration, stats) and stop")
    ap.add_argument("--force", action="store_true", help="proceed past the 20%% contingency stop")
    args = ap.parse_args(argv)

    key_rows = {r["id"]: r for r in csv.DictReader(open(args.key, encoding="utf-8-sig"))}
    cal_paths = resolve_calibration_paths(args.key, args.calibration)
    cal_ids: set = set()
    for p in cal_paths:
        cal_ids |= {r["id"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
    cal_key_path = args.calibration_key or os.path.join(os.path.dirname(os.path.abspath(args.key)),
                                                        "calibration_key.csv")
    cal_key = load_calibration_key(cal_key_path)

    got = collect_labels(args.key, args.annotations, args.adjudicated, args.calibration)
    final: Dict[str, str] = dict(got["final"])
    raters = load_rater_fields(args.annotations, skip_ids=set())      # incl. calibration rows, for export
    for i in key_rows:                                                  # queue items with no label at all
        if i not in final and i not in cal_ids:
            final[i] = "pending"

    export = Path(args.export_dir)
    export.mkdir(parents=True, exist_ok=True)
    _export_raw_artifacts(export, args, key_rows, cal_ids, cal_key_path, raters)
    if args.export_artifacts_only:
        print(f"raw verification artifacts written to {export}/")
        return 0

    # ── decide every v2.1 row ────────────────────────────────────────────────
    header, recs = rb.load_manifest(args.manifest_in)
    prior = load_prior_forms(args.prior_forms)
    decisions: List[dict] = []
    actions = Counter()
    contingency_num = contingency_den = 0
    for r in recs:
        vid = f"{r['dataset']}:{r['position']}"
        k = key_rows.get(vid)
        tier = k["provenance"] if k else ""
        e = (r["aug_meta"].get("edits") or [{}])[0]
        pf = prior.get((r["dataset"], r["graph"], r["id"]))
        d = {"id": vid, "dataset": r["dataset"], "graph": r["graph"], "uuid": r["id"],
             "tier": tier or r["aug_meta"].get("edits", [{}])[0].get("source", ""),
             "strategy": e.get("strategy", ""), "in_queue": bool(k), "final_label": "",
             "action": "", "reason": "", "revert_strategy": "", "revert_to": "", "release_position": ""}
        if vid in cal_ids:
            ref = cal_key.get(vid, "")
            d["final_label"] = f"calibration:{ref or 'n/a'}"
            if ref == "invalid":
                d["action"], d["reason"] = "remove:calibration_key_invalid", "organizer reference answer: invalid"
            else:
                d["action"], d["reason"] = "keep:calibration", "calibration item; main-queue labels not used (pre-registered)"
        elif k:
            f = final.get(vid, "pending")
            nat = [v["naturalness"].lower() for v in raters.get(vid, {}).values() if v.get("naturalness")]
            d["final_label"] = f
            d["action"], d["reason"] = decide(tier, f, nat, pf is not None,
                                              args.naturalness, args.pending)
            if d["action"] == "revert:prior_algorithmic":
                d["revert_strategy"], d["revert_to"] = pf["revert_strategy"], pf["revert_to"]
            if tier in CENSUS and pf is None and f in ("valid", "invalid"):
                contingency_den += 1
                contingency_num += (f == "invalid")
        else:
            d["final_label"] = "unsampled"
            d["action"], d["reason"] = "keep:unsampled", "never sampled for human review"
        decisions.append(d)
        actions[d["action"]] += 1

    rate = contingency_num / contingency_den if contingency_den else 0.0
    print(f"\n=== verdict application ({args.version}) ===")
    print(f"rows in: {len(recs)}   pending policy: {args.pending}   naturalness policy: {args.naturalness}")
    for a, n in sorted(actions.items()):
        print(f"  {a:34s} {n}")
    print(f"contingency check: invalid rate among no-prior census rows = "
          f"{contingency_num}/{contingency_den} = {100*rate:.1f}% (stop threshold 20%)")
    if rate > CONTINGENCY_RATE and not args.force:
        print("!! pre-registered contingency triggered — the fallback is a different procedure; "
              "not freezing (use --force to override)")
        return 3
    n_pending = actions.get("pending", 0)
    if n_pending and not args.dry_run:
        print(f"!! {n_pending} items still await adjudication — not freezing. Fill "
              f"verification/adjudicated.csv (see scripts/adjudication_worklist.py) and rerun, "
              f"or pass --pending keep|drop for a provisional build.")
        return 4

    # ── apply ────────────────────────────────────────────────────────────────
    by_id = {d["id"]: d for d in decisions}
    new_recs: List[dict] = []
    pos = Counter()
    for r in sorted(recs, key=lambda r: (r["dataset"], r["position"])):
        vid = f"{r['dataset']}:{r['position']}"
        d = by_id[vid]
        if d["action"].startswith("remove") or d["action"] == "pending":
            continue
        nr = json.loads(json.dumps(r))                   # deep copy
        nr["v21_position"], nr["v21_id"] = r["position"], vid
        if d["action"] == "revert:prior_algorithmic":
            e = nr["aug_meta"]["edits"][0]
            nl = _replace_all(nr["aug_meta"].get("original_nl") or "", e["from"], d["revert_to"])
            if nl is None:
                d["action"], d["reason"] = "remove:revert_failed", "prior form could not be spliced into the question"
                actions["revert:prior_algorithmic"] -= 1
                actions["remove:revert_failed"] += 1
                continue
            reverted_from = {k: e.get(k) for k in ("strategy", "to", "source", "proposer_model", "evidence")
                             if k in e}
            e.update({"strategy": d["revert_strategy"], "to": d["revert_to"], "source": "algorithmic",
                      "needs_verification": False, "validity": "ok",
                      "regenerated": f"verification_revert_{args.version}",
                      "reverted_from": reverted_from})
            for k in ("proposer_model", "evidence"):
                e.pop(k, None)
            nr["probed_grounding"] = grounding_class(e["from"], e["to"])
        vb = {"in_queue": d["in_queue"], "final_label": d["final_label"], "action": d["action"]}
        if d["in_queue"] and vid not in cal_ids:
            vb["raters"] = {a: {k: v[k] for k in ("validity", "naturalness", "source_error")}
                            for a, v in raters.get(vid, {}).items()}
        nr["verification"] = vb
        nr["position"] = pos[r["dataset"]]
        pos[r["dataset"]] += 1
        d["release_position"] = nr["position"]
        new_recs.append(nr)

    rebuilt = rb.build_rows(new_recs)
    datasets = ({ds: os.path.join(args.benchmarks_dir, ds, "test.json") for ds in rb._DATASETS}
                if args.benchmarks_dir else rb._DATASETS)
    hashes = {}
    for ds in datasets:
        rows, prows = rebuilt[ds]
        hashes[f"{ds}/test.json"] = rb.canonical_hash(rows)
        hashes[f"{ds}/test.probed.json"] = rb.canonical_hash(prows)

    summary = {
        "version": args.version, "rows_in": len(recs), "rows_out": len(new_recs),
        "pending_policy": args.pending, "naturalness_policy": args.naturalness,
        "actions": dict(actions),
        "contingency": {"invalid": contingency_num, "resolved": contingency_den, "rate": rate},
        "source_manifest": {"path": args.manifest_in, "version": header.get("version"),
                            "sha256": sha256_file(args.manifest_in), "row_count": len(recs)},
        "per_dataset_out": {ds: len(rebuilt[ds][0]) for ds in datasets},
    }
    summary["actions"]["remove_total"] = sum(n for a, n in actions.items() if a.startswith("remove"))
    summary["actions"]["revert_total"] = sum(n for a, n in actions.items() if a.startswith("revert"))
    print(f"rows out: {len(new_recs)}  " + "  ".join(f"{ds}={n}" for ds, n in summary["per_dataset_out"].items()))

    if args.dry_run:
        _write_decisions(export / "decisions.preview.csv", decisions)
        print(f"dry run — nothing frozen; plan written to {export/'decisions.preview.csv'}")
        return 0

    # ── write: benchmark files, manifest, decision log, summary ──────────────
    for ds, path in datasets.items():
        rows, prows = rebuilt[ds]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(prows, open(Path(path).with_name("test.probed.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    _write_decisions(export / "decisions.csv", decisions)
    removed_out = Path(args.removed_out) if args.removed_out else Path(args.manifest_out).with_name("removed_rows.jsonl")
    n_removed = _write_removed_rows(removed_out, recs, decisions, args.version)
    summary["removed_rows"] = {"file": removed_out.name, "count": n_removed}
    new_header = {"_manifest_header": True, "version": args.version, "row_count": len(new_recs),
                  "released_hashes": hashes,
                  "source_manifest": summary["source_manifest"],
                  "verification": {"pending_policy": args.pending,
                                   "naturalness_policy": args.naturalness,
                                   "actions": summary["actions"],
                                   "decisions_csv_sha256": sha256_file(export / "decisions.csv")},
                  "removed_rows": {"file": removed_out.name, "count": n_removed,
                                   "sha256": sha256_file(removed_out)}}
    Path(args.manifest_out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.manifest_out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(new_header, ensure_ascii=False) + "\n")
        for nr in new_recs:
            fh.write(json.dumps(nr, ensure_ascii=False) + "\n")
    (export / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    # independent check: the new manifest must rebuild to the files just written
    h2, recs2 = rb.load_manifest(args.manifest_out)
    ok = rb.verify(h2, rb.build_rows(recs2), datasets=datasets)
    for ds, path in datasets.items():
        on_disk = json.load(open(path, encoding="utf-8"))
        if rb.canonical_hash(on_disk) != hashes[f"{ds}/test.json"]:
            ok = False
            print(f"  FAIL on-disk {ds}/test.json differs from the frozen hash")
    print(f"manifest -> {args.manifest_out}\nfrozen {len(new_recs)} rows; "
          + ("REBUILD VERIFIED" if ok else "MISMATCH — do not release"))
    return 0 if ok else 1


# ── artifacts ─────────────────────────────────────────────────────────────────

_DEC_COLS = ["id", "dataset", "graph", "uuid", "tier", "strategy", "in_queue", "final_label",
             "action", "reason", "revert_strategy", "revert_to", "release_position"]


def _write_removed_rows(path: Path, recs: List[dict], decisions: List[dict], version: str) -> int:
    """Every source row the verification removed, as it stood in the source
    release: dataset, graph, question id, question text, the action and the
    release that removed it. Readers of evaluation records (the sweep driver,
    the report scripts) drop these rows, so a run made before the removal is
    scored on exactly the released rows."""
    removed = {d["id"]: d for d in decisions if d["action"].startswith("remove")}
    rebuilt = rb.build_rows(recs)
    out: List[dict] = []
    for ds in sorted(rebuilt):
        rows = rebuilt[ds][0]
        srecs = sorted((r for r in recs if r["dataset"] == ds), key=lambda r: r["position"])
        assert len(rows) == len(srecs)
        for row, r in zip(rows, srecs):
            assert row["id"] == r["id"]
            vid = f"{r['dataset']}:{r['position']}"
            d = removed.get(vid)
            if d is None:
                continue
            out.append({"dataset": r["dataset"], "graph": r["graph"], "id": r["id"], "nl": row["nl"],
                        "source_id": vid, "action": d["action"], "removed_in": version})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for o in out:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    return len(out)


def _write_decisions(path: Path, decisions: List[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_DEC_COLS)
        w.writeheader()
        for d in decisions:
            w.writerow({c: d.get(c, "") for c in _DEC_COLS})


def _export_raw_artifacts(export: Path, args, key_rows, cal_ids, cal_key_path, raters) -> None:
    """Everything a reviewer needs to recompute the verification numbers:
    the blind key, every anonymised per-item verdict, the calibration set and
    its reference answers, and the statistics report (markdown + JSON)."""
    shutil.copy2(args.key, export / "verification_key.csv")
    with open(export / "verdicts_long.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "annotator", "validity", "naturalness", "source_error",
                    "corrected_form", "notes", "calibration_item"])
        for vid in sorted(raters):
            for ann in sorted(raters[vid]):
                v = raters[vid][ann]
                w.writerow([vid, ann, v["validity"], v["naturalness"], v["source_error"],
                            v["corrected_form"], v["notes"], "yes" if vid in cal_ids else "no"])
    with open(export / "calibration_ids.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow(["id"])
        for i in sorted(cal_ids):
            w.writerow([i])
    if os.path.exists(cal_key_path):
        shutil.copy2(cal_key_path, export / "calibration_key.csv")
    import verification_stats
    argv = ["--key", args.key, "--annotations", *args.annotations,
            "--out", str(export / "stats.md"), "--json", str(export / "stats.json")]
    if args.adjudicated:
        argv += ["--adjudicated", args.adjudicated]
    if args.calibration is not None:
        argv += ["--calibration", *args.calibration]
    verification_stats.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
