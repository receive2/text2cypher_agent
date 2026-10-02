#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/rejudge_node_returns.py
===============================
Re-judge finished runs under the node-set rule (``eval/node_set_match.py``).
No model is called and no question is run again: the predictions stored in
``records.jsonl`` are judged a second time against the graph.

Why: a gold query that returns a whole node (``RETURN x0``) used to score every
prediction that returned a property of the right nodes as wrong. Runs made
before the rule existed hold such verdicts for 518 pole questions and 5 bloom
questions per method; this script corrects them in place. Runs made after it
are already judged this way and are left alone, as are graphs without
node-returning gold queries (all of CypherBench).

    python scripts/rejudge_node_returns.py              # every run under logs/runs/, every model
    python scripts/rejudge_node_returns.py --dry-run    # show what would change, write nothing
    python scripts/rejudge_node_returns.py logs/ablation_gpt-5.6-terra__judge-on-node
                                                        # every records.jsonl below the given paths

What it does to a run directory that holds verdicts from before the rule:

* ``records.jsonl`` — every record gets ``ea_strict`` (the verdict it had); a
  record the rule accepts gets ``ea: true``. Its PSJS is kept unless it was 0:
  PSJS reads EA only as a fallback (a query that cannot be rewritten for
  provenance), which gave 0 under the old verdict; such a value is computed
  again and the old one kept as ``psjs_strict``.
* ``summary.json`` — ``ea``, ``psjs``, ``by_difficulty`` recomputed from the
  records; ``ea_strict``, ``ea_rule`` and a ``rejudged`` note added.

Both files are replaced atomically; a second invocation finds nothing to do.
A run that is still being written (no ``summary.json`` yet, or ``records.jsonl``
modified in the last two minutes) is skipped. The graph is only read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import eval_config as cfg                                            # noqa: E402
import eval_paths                                                    # noqa: E402
from eval.difficulty import aggregate_by_difficulty                  # noqa: E402
from eval.node_set_match import (RULE, capped_executor, is_stale,    # noqa: E402
                                 node_set_verdict, strict_value)

FRESH_SEC = 120          # a records.jsonl touched more recently than this may still be written to
DEFAULT_TIMEOUT = 120.0  # seconds per statement


class ReadOnlyGraph:
    """The two things the scorers need from LangChain's ``Neo4jGraph`` — ``query()``
    returning ``Record.data()`` rows — over a read-only session with a per-statement
    transaction timeout."""

    def __init__(self, uri: str, user: str, password: str, database: str, timeout: float) -> None:
        from neo4j import GraphDatabase
        self._drv = GraphDatabase.driver(uri, auth=(user, password))
        self._db = database
        self._timeout = float(timeout)

    def query(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        from neo4j import READ_ACCESS
        with self._drv.session(database=self._db, default_access_mode=READ_ACCESS) as session:
            with session.begin_transaction(timeout=self._timeout) as tx:
                return [record.data() for record in tx.run(cypher, params or {})]

    def close(self) -> None:
        self._drv.close()


def find_record_files(paths: List[Path]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        if p.is_file() and p.name == "records.jsonl":
            out.append(p)
        elif p.is_dir():
            out += sorted(p.rglob("records.jsonl"))
    seen, uniq = set(), []
    for f in out:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


def read_records(path: Path) -> List[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def pair_of(records_file: Path, records: List[dict]) -> Optional[Tuple[str, str]]:
    """``(dataset, graph)`` of a run: from its ``summary.json``, else its directory name."""
    summary = records_file.with_name("summary.json")
    if summary.is_file():
        try:
            s = json.loads(summary.read_text(encoding="utf-8"))
            rc = s.get("run_config") or {}
            dataset = rc.get("dataset") or s.get("dataset")
            graph = rc.get("graph") or next((r.get("graph") for r in records if r.get("graph")), None)
            if dataset and graph:
                return str(dataset), str(graph)
        except Exception:  # noqa: BLE001
            pass
    parsed = eval_paths.parse_run_dir_stamped(records_file.parent)
    if parsed is not None:
        return parsed[0], parsed[1]
    return None


def still_written(records_file: Path, now: Optional[float] = None) -> str:
    """Why this run must not be touched yet, or ``""``."""
    if not records_file.with_name("summary.json").is_file():
        return "no summary.json — the run is not finished"
    age = (now if now is not None else time.time()) - records_file.stat().st_mtime
    if age < FRESH_SEC:
        return f"records.jsonl was written {int(age)} s ago — the run may not be finished"
    return ""


def _mean_true(records: List[dict], value) -> float:
    return (sum(1.0 for r in records if value(r) is True) / len(records)) if records else 0.0


def _mean_psjs(records: List[dict]) -> float:
    if not records:
        return 0.0
    return sum(float(r["psjs"]) if isinstance(r.get("psjs"), (int, float)) and not isinstance(r.get("psjs"), bool)
               else 0.0 for r in records) / len(records)


def rejudge_records(records: List[dict], graph: Any, gold_cache: Dict[str, Any],
                    compute_psjs=None) -> Dict[str, int]:
    """Apply the rule to *records* in place. Returns counts: ``checked`` (stale verdicts
    looked at) and ``accepted`` (turned correct). Raises when a gold query no longer runs —
    it ran when the record was made, so that is the environment, not the record."""
    execute = capped_executor(graph)
    stale = [r for r in records if is_stale(r)]
    accepted = 0
    for r in stale:
        gold = r["gold_cypher"]
        if gold not in gold_cache:
            rows, err = execute(gold)
            if err is not None:
                raise RuntimeError(f"gold query of {r.get('qid')} failed: {err}")
            gold_cache[gold] = rows
        if node_set_verdict(r.get("pred_cypher"), gold, gold_cache[gold], execute) is True:
            r["ea_strict"], r["ea"] = False, True
            accepted += 1
            # PSJS reads EA only as a fallback (a query that cannot be rewritten for provenance,
            # or two empty provenance sets), and that fallback gave 0 while EA was False. A PSJS
            # above 0 was measured and stays; a 0 is computed again with the new verdict.
            if compute_psjs is not None and not r.get("psjs"):
                new = compute_psjs(r.get("pred_cypher"), gold, neo4j_graph=graph, ea_value=True)
                if new:
                    r["psjs_strict"], r["psjs"] = r.get("psjs"), new
        else:
            r["ea_strict"] = False
    for r in records:                       # every record states its value verdict from now on
        r.setdefault("ea_strict", r.get("ea"))
    return {"checked": len(stale), "accepted": accepted}


def update_summary(summary: dict, records: List[dict], counts: Dict[str, int]) -> dict:
    out = dict(summary)
    out["ea"] = _mean_true(records, lambda r: r.get("ea"))
    out["ea_strict"] = _mean_true(records, strict_value)
    out["ea_rule"] = RULE
    out["psjs"] = _mean_psjs(records)
    if "by_difficulty" in out:
        out["by_difficulty"] = aggregate_by_difficulty(records)
    out["rejudged"] = {"rule": RULE, "at": time.strftime("%Y-%m-%d %H:%M:%S"), **counts}
    return out


def _replace(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".rejudge.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def rejudge_file(records_file: Path, graph: Any, gold_cache: Dict[str, Any], *, dry_run: bool,
                 compute_psjs=None) -> Dict[str, Any]:
    records = read_records(records_file)
    before = _mean_true(records, lambda r: r.get("ea"))
    counts = rejudge_records(records, graph, gold_cache, compute_psjs=compute_psjs)
    after = _mean_true(records, lambda r: r.get("ea"))
    if not dry_run:
        summary_file = records_file.with_name("summary.json")
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        _replace(records_file, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        _replace(summary_file, json.dumps(update_summary(summary, records, counts), ensure_ascii=False, indent=2))
    return {**counts, "n": len(records), "ea_before": before, "ea_after": after}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="run directories, folders that contain them, or records.jsonl files "
                                             f"(default: {eval_paths.RUNS_ROOT}/)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    ap.add_argument("--force", action="store_true", help="also touch runs that look unfinished (never while one is running)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds per statement (default %(default)s)")
    args = ap.parse_args(argv)

    roots = [Path(p) for p in args.paths] or [REPO / eval_paths.RUNS_ROOT]
    files = find_record_files([p if p.is_absolute() else Path.cwd() / p for p in roots])
    if not files:
        print("no records.jsonl found under: " + ", ".join(str(p) for p in roots))
        return 0

    from loguru import logger
    from eval.psjs import compute_psjs
    logger.disable("eval.psjs")          # its per-query warnings belong to a run's log, not to this report
    graphs: Dict[Tuple[str, str], ReadOnlyGraph] = {}
    caches: Dict[Tuple[str, str], Dict[str, Any]] = {}
    done = skipped = failed = 0
    try:
        for f in files:
            rel = f.parent.relative_to(REPO) if f.parent.is_relative_to(REPO) else f.parent
            try:
                records = read_records(f)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {rel}: unreadable records.jsonl ({exc})"); failed += 1
                continue
            if not any(is_stale(r) for r in records):
                continue                                  # judged under the rule already, or nothing it could change
            why = "" if args.force else still_written(f)
            if why:
                print(f"  - {rel}: skipped — {why}"); skipped += 1
                continue
            pair = pair_of(f, records)
            if pair is None:
                print(f"  ! {rel}: cannot tell which graph this run used (no summary.json run_config, "
                      "directory name not a run dir) — skipped"); failed += 1
                continue
            try:
                if pair not in graphs:
                    conn = cfg.conn_for(*pair)
                    graphs[pair] = ReadOnlyGraph(conn.uri, conn.user, conn.password, conn.database, args.timeout)
                    caches[pair] = {}
                res = rejudge_file(f, graphs[pair], caches[pair], dry_run=args.dry_run, compute_psjs=compute_psjs)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {rel}: not changed — {type(exc).__name__}: {str(exc)[:300]}"); failed += 1
                continue
            done += 1
            print(f"  {'would change' if args.dry_run else 'rejudged'} {rel}: {res['accepted']} of {res['checked']} "
                  f"checked verdicts accepted; EA {res['ea_before']:.3f} -> {res['ea_after']:.3f} (n={res['n']})")
    finally:
        for g in graphs.values():
            g.close()
    verb = "would be re-judged" if args.dry_run else "re-judged"
    print(f"\n{done} run(s) {verb}, {skipped} skipped as unfinished, {failed} could not be handled, "
          f"{len(files) - done - skipped - failed} needed nothing (rule {RULE}).")
    if skipped:
        print("Run this again when the skipped runs have finished.")
    if done and not args.dry_run:
        print("Sweep runs: `python orchestrate_sweep.py --status` now shows them without ↻, and `--publish` rebuilds "
              "the report tables from the corrected records.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
