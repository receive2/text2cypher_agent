#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit_runs.py
=====================
Which run directories under ``logs/runs/`` can be used by the sweep, and which
must be deleted. Read-only: it prints one verdict per directory and the exact
``rm -rf`` lines for the ones to delete; it never deletes anything itself.

    python scripts/audit_runs.py                    # model = eval_config.GENERATOR_LLM
    python scripts/audit_runs.py --model gpt-5.6-luna
    python scripts/audit_runs.py --all-models
    python scripts/audit_runs.py --discard-all      # delete EVERY run of this model (asks you to type its name)

Two modes. The audit (default) judges each directory and prints the ``rm -rf``
lines for the ones that cannot be used, deleting nothing. ``--discard-all`` is
the clean slate: it lists every run directory of the model — suite, clean and
development graphs alike — plus the driver's state files and old
``logs/runs/report_*.md`` files, and deletes them after you type the model
name. The coordinator tells each runner which mode applies; the default for
runs made under the old procedure is ``--discard-all``.

A run can be used only if

1. its records were scored on the released benchmark rows — every record's
   ``qid`` is a release id of that graph and its ``question`` is the release
   text (the driver checks this too and marks such a cell ``≠release``); and
2. it was made from a checkout that already enforced the published artifact
   set (commit ``be36c26``, 2026-09-10). A run directory does not record which
   artifacts it saw, so the checkout's history is the only evidence: the first
   ``git reflog`` entry whose commit contains ``be36c26`` says when this
   checkout got the published set, and every run stamped before that moment
   cannot be verified.

Verdicts: ``DELETE`` (fails 1 or 2), ``CHECK`` (no reflog evidence — decide by
hand), ``keep`` (the newest usable run of its cell), ``older`` (superseded by a
newer run; harmless, never published), ``partial`` (newest but truncated: the
driver will re-run the cell; delete it only to fall back to an older complete
run), ``outside`` (not a suite pair: clean / development graphs; ignored by
the driver).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import eval_config as cfg           # noqa: E402
import eval_paths                   # noqa: E402
import orchestrate_sweep as osw     # noqa: E402

PUBLISHED_SET_GUARD_COMMIT = "be36c26928876fd3a3ee70f9c6c01c8d20b3329a"   # eval_run enforces MANIFEST.json (2026-09-10)
_REFLOG_LINE = re.compile(r"^([0-9a-f]+) HEAD@\{(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _git(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)


def guard_since(repo: Path = REPO) -> Tuple[Optional[datetime], str]:
    """When this checkout first contained the published-set guard, from
    ``git reflog``; ``(None, why)`` when that cannot be established."""
    head = _git("merge-base", "--is-ancestor", PUBLISHED_SET_GUARD_COMMIT, "HEAD", cwd=repo)
    if head.returncode != 0:
        return None, "this checkout does not contain the published-set guard — git pull first, then re-run the audit"
    log = _git("reflog", "--date=iso", cwd=repo)
    entries: List[Tuple[str, datetime]] = []
    for line in log.stdout.splitlines():
        m = _REFLOG_LINE.match(line)
        if m:
            entries.append((m.group(1), datetime.strptime(m.group(2), "%Y-%m-%d %H:%M:%S")))
    if not entries:
        return None, "git reflog is empty or unavailable — the moment this checkout got the published set is unknown"
    for sha, when in reversed(entries):            # oldest first
        if _git("merge-base", "--is-ancestor", PUBLISHED_SET_GUARD_COMMIT, sha, cwd=repo).returncode == 0:
            return when, f"this checkout has contained the published artifact set since {when:%Y-%m-%d %H:%M} (git reflog)"
    return None, "no reflog entry contains the published-set guard — the moment this checkout got it is unknown"


def parse_stamp(stamp: str) -> Optional[datetime]:
    try:
        return datetime.strptime(stamp, eval_paths.STAMP_FMT)
    except ValueError:
        return None


def run_dir_model(d: Path, method_seg: str) -> str:
    """The model segment a run dir belongs to: from its ``@<model>`` tag, else
    from the model recorded in its ``summary.json`` (dirs from before tagging)."""
    base, tagged = eval_paths.split_method_seg(method_seg)
    return tagged or eval_paths.model_seg(eval_paths.run_meta_model(d) or "")


def model_run_dirs(runs_root: Path, model: str, include_unattributed: bool = False) -> List[Path]:
    """Every run directory of *model* under *runs_root*, suite or not. With
    *include_unattributed*, also the directories that belong to no model at all
    (no ``@<model>`` tag and no model in ``summary.json`` — a run killed under
    the old procedure): in a one-person checkout they can only be the runner's."""
    want = eval_paths.model_seg(model)
    out: List[Path] = []
    for d in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        parsed = eval_paths.parse_run_dir_stamped(d)
        if parsed is None:
            continue
        owner = run_dir_model(d, parsed[2])
        if owner == want or (include_unattributed and not owner):
            out.append(d)
    return out


def discard_all(model: str, runs_root: Path, logs_root: Path,
                confirm: Callable[[List[Path]], bool]) -> List[Path]:
    """The clean slate: delete every run directory of *model*, the driver's
    state files for it and old ``eval_aggregate`` report files — but only after
    *confirm(paths)* returns True. Returns what was deleted."""
    targets: List[Path] = model_run_dirs(runs_root, model, include_unattributed=True) if runs_root.is_dir() else []
    targets += sorted(runs_root.glob("report_*.md")) if runs_root.is_dir() else []
    targets += [p for p in (logs_root / f"sweep_{model}.json", logs_root / f"sweep_{model}_smoke.json") if p.is_file()]
    if not targets or not confirm(targets):
        return []
    for p in targets:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    return targets


def audit(runs_root: Path, model: Optional[str], all_models: bool,
          guard_time: Optional[datetime]) -> List[dict]:
    """One row per run directory: verdict, reason, and what the driver would use."""
    suite = set(osw.suite_pairs())
    expected = osw.expected_counts()
    want_model = eval_paths.model_seg(model) if model else ""
    dirs: List[dict] = []
    for d in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        parsed = eval_paths.parse_run_dir_stamped(d)
        if parsed is None:
            continue
        dataset, graph, seg, stamp = parsed
        base, _tagged = eval_paths.split_method_seg(seg)
        run_model = run_dir_model(d, seg)
        if not all_models and run_model != want_model:
            continue
        recs = eval_paths.drop_retired(dataset, graph, osw.read_records(d))
        dirs.append({"dir": d, "rel": str(d.relative_to(REPO)) if d.is_relative_to(REPO) else str(d),
                     "dataset": dataset, "graph": graph, "method": base, "model": run_model,
                     "stamp": stamp, "made": parse_stamp(stamp) if stamp else None,
                     "n": len(recs), "expected": expected.get((dataset, graph), 0),
                     "in_suite": (dataset, graph) in suite, "records": recs})
    # rules 1 and 2 per directory
    for r in dirs:
        r["rows_ok"], r["rows_why"] = (osw.rows_match_release(r["dataset"], r["graph"], r["records"])
                                       if r["in_suite"] else (True, ""))
        if guard_time is None:
            r["before_guard"] = r["made"] is None          # untagged/unstamped dirs predate the guard by construction
            r["guard_unknown"] = r["made"] is not None
        else:
            r["before_guard"] = r["made"] is None or r["made"] < guard_time
            r["guard_unknown"] = False
        r["usable"] = r["in_suite"] and r["rows_ok"] and not r["before_guard"] and not r["guard_unknown"]
    # newest usable / newest overall per cell, as the driver sees it (newest stamp wins)
    by_cell: Dict[Tuple[str, str, str, str], List[dict]] = {}
    for r in dirs:
        by_cell.setdefault((r["dataset"], r["graph"], r["method"], r["model"]), []).append(r)
    for rows in by_cell.values():
        rows.sort(key=lambda r: r["stamp"])
        newest = rows[-1]
        usable_complete = [r for r in rows if r["usable"] and r["n"] == r["expected"] and r["expected"]]
        for r in rows:
            r["is_newest"] = r is newest
            r["fallback"] = usable_complete[-1]["rel"] if usable_complete and usable_complete[-1] is not r else None
    for r in dirs:
        n, exp = r["n"], r["expected"]
        if not r["in_suite"]:
            r["verdict"], r["reason"] = "outside", "not a suite pair (clean / development graph) — ignored by the driver"
        elif not r["rows_ok"]:
            r["verdict"], r["reason"] = "DELETE", r["rows_why"]
        elif r["before_guard"]:
            made = f"made {r['made']:%Y-%m-%d %H:%M}" if r["made"] else "unstamped (predates model tagging)"
            since = f" ({guard_time:%Y-%m-%d %H:%M})" if guard_time else ""
            r["verdict"], r["reason"] = "DELETE", f"{made}, before this checkout had the published artifact set{since} — its artifacts cannot be verified"
        elif r["guard_unknown"]:
            r["verdict"], r["reason"] = "CHECK", "cannot tell whether this checkout had the published set when it ran — delete unless you know it did"
        elif not r["is_newest"]:
            r["verdict"], r["reason"] = "older", "superseded by a newer run of this cell — harmless, never published"
        elif n < exp:
            r["verdict"] = "partial"
            r["reason"] = (f"newest but {n}/{exp} records — the driver will re-run this cell"
                           + (f"; delete it to fall back to {r['fallback']}" if r["fallback"] else ""))
        else:
            r["verdict"], r["reason"] = "keep", f"newest for this cell, {n}/{exp}, rows = release"
    return dirs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="generator preset (default: eval_config.GENERATOR_LLM)")
    ap.add_argument("--all-models", action="store_true", help="every model's run dirs")
    ap.add_argument("--discard-all", action="store_true",
                    help="delete EVERY run directory of this model (plus its state files and old report_*.md) "
                         "after you type the model name — the clean slate for runs made under the old procedure")
    ap.add_argument("--yes", action="store_true", help="with --discard-all: do not ask (scripts only)")
    args = ap.parse_args(argv)
    if args.discard_all and (args.all_models or not args.model):
        # never infer the model to wipe from eval_config.py: the handout's step 1 has just reset that file
        ap.error("--discard-all needs --model <the model you were assigned> (and works on one model)")
    model = None if args.all_models else (args.model or str(getattr(cfg, "GENERATOR_LLM", "") or "")).strip()
    if not args.all_models and not model:
        ap.error("no model: set eval_config.GENERATOR_LLM or pass --model")
    if model:
        import config
        try:
            config.resolve_preset(model)
        except KeyError:
            ap.error(f"'{model}' is not a model preset. Copy the exact name from the handout; the presets are: "
                     + ", ".join(sorted(config.MODEL_PRESETS)))
    runs_root = REPO / eval_paths.RUNS_ROOT
    if args.discard_all:
        def confirm(paths: List[Path]) -> bool:
            print(f"--discard-all will delete these {len(paths)} item(s) of model {model} "
                  "(run dirs tagged with it, run dirs tagged with no model at all, its state files, old report_*.md):")
            for p in paths:
                print(f"  {p.relative_to(REPO) if p.is_relative_to(REPO) else p}")
            if args.yes:
                return True
            if not sys.stdin.isatty():
                print("not a terminal — re-run with --yes to confirm", file=sys.stderr)
                return False
            try:
                typed = input(f"Type the model name ({model}) to delete them, anything else to abort: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\naborted")
                return False
            return typed == model
        gone = discard_all(model, runs_root, REPO / "logs", confirm)
        if gone:
            print(f"deleted {len(gone)} item(s). Continue with the handout from §1 "
                  "(python benchmarks/verify.py, then --smoke, then the full run).")
        else:
            print("nothing deleted.")
        return 0
    guard_time, guard_note = guard_since()
    print(f"audit of {eval_paths.RUNS_ROOT}/ for {'every model' if args.all_models else f'model {model}'} — "
          f"benchmarks {osw._benchmarks_version()}; {guard_note}\n")
    if not runs_root.is_dir():
        print("  (no run directories)"); return 0
    rows = audit(runs_root, model, args.all_models, guard_time)
    if not rows:
        print("  (no run directories for this model)"); return 0
    width = max(len(r["rel"]) for r in rows)
    for r in rows:
        print(f"  {r['verdict']:<8} {r['rel']:<{width}}  {r['reason']}")
    deletes = [r for r in rows if r["verdict"] == "DELETE"]
    checks = [r for r in rows if r["verdict"] == "CHECK"]
    partial = [r for r in rows if r["verdict"] == "partial" and r["fallback"]]
    print()
    if deletes:
        print(f"{len(deletes)} run director{'y' if len(deletes) == 1 else 'ies'} cannot be used. Delete exactly these:")
        for r in deletes:
            print(f"  rm -rf {r['rel']}")
    if checks:
        print(f"{len(checks)} run director{'y' if len(checks) == 1 else 'ies'} need a decision (no git evidence); "
              "delete unless you know the checkout had the published set when they ran:")
        for r in checks:
            print(f"  rm -rf {r['rel']}")
    if partial:
        print("Optional — a truncated newest run that hides an older complete one (the driver would otherwise re-run the cell in full):")
        for r in partial:
            print(f"  rm -rf {r['rel']}      # falls back to {r['fallback']}")
    if not deletes and not checks:
        print("Nothing has to be deleted.")
    print("\nThen: python orchestrate_sweep.py --status")
    if not args.all_models:
        print(f"Optional: rm logs/sweep_{model}.json   # resets the automatic ⚠ re-run budgets; completeness is read from the run directories")
    return 1 if (deletes or checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
