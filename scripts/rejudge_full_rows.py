#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/rejudge_full_rows.py
============================
Score finished runs of No Val Link and FCAV again on every row their queries
return (``eval/full_rows.py``). No model is called and no question is run
again: the predictions stored in ``records.jsonl`` are executed a second time
against the graph and compared with the gold result, as the evaluators now do.

Why: those methods end in LangChain's GraphCypherQAChain, which keeps the first
10 rows of a result for its answer prompt — and the evaluators scored those 10
rows. A correct query with a larger result was scored wrong. Runs made with the
fixed code are stamped ``rows_rule`` record by record and are left alone, as
are the runs of every other method (they always returned the full result).

    python scripts/rejudge_full_rows.py              # every run under logs/runs/, every model
    python scripts/rejudge_full_rows.py --dry-run    # show what would change, write nothing
    python scripts/rejudge_full_rows.py logs/clean_paired
                                                     # every records.jsonl below the given paths

What it does to a record of such a run that was scored before the fix:

* the stored prediction is executed again with the evaluation executor (its
  timeout: ``EVAL_NEO4J_QUERY_TIMEOUT``, 30 s) and compared with the gold
  result by the evaluator of its benchmark — value comparison, and on
  Mind-the-Query / ZOGRASCOPE the node-set rule — giving ``ea`` (and
  ``ea_strict``). The verdict it had is kept as ``ea_capped``; the record is
  stamped ``rows_rule``.
* PSJS is kept unless the verdict changed: PSJS reads EA as a fallback, so a
  record whose EA changed has its PSJS computed again (the old value kept as
  ``psjs_capped`` when it differs).
* a prediction whose full result no longer runs within the timeout is what the
  fixed code reports as an execution failure: the record becomes an agent
  error (``ea`` None, as every error), with the old verdicts kept. A prediction
  with a writing clause is not run again (the graph is only read): it keeps its
  verdict and is noted.

``summary.json`` gets ``ea``, ``ea_strict``, ``psjs``, ``n_scored``, ``n_errors``
and ``by_difficulty`` recomputed from the records, and a ``rows_rejudged`` note.
Both files are replaced atomically; a second invocation finds nothing to do. A
run that is still being written (no ``summary.json`` yet, or ``records.jsonl``
modified in the last two minutes) is skipped. The graph is only read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import eval_config as cfg                                            # noqa: E402
import eval_paths                                                    # noqa: E402
from eval.difficulty import aggregate_by_difficulty                  # noqa: E402
from eval.full_rows import RULE, is_stale, uses_chain                # noqa: E402
from eval.node_set_match import capped_executor, strict_value        # noqa: E402
from rejudge_node_returns import (ReadOnlyGraph, _mean_psjs, _mean_true, _replace,  # noqa: E402
                                  find_record_files, pair_of, read_records, still_written)

PRED_TIMEOUT = float(os.environ.get("EVAL_NEO4J_QUERY_TIMEOUT", "30"))   # the evaluation executor's
GOLD_TIMEOUT = 120.0                                                      # gold queries ran without one

Rows = Optional[List[Any]]
Executor = Callable[[str], Tuple[Rows, Optional[str]]]


class Scorer:
    """How the evaluator of one benchmark turns (prediction rows, gold rows) into
    ``ea`` / ``ea_strict``: its value comparison, and on Mind-the-Query and
    ZOGRASCOPE the node-set rule."""

    def __init__(self, value_cmp: Callable[..., bool], node_set: Optional[Callable[..., Optional[bool]]] = None):
        self.value_cmp, self.node_set = value_cmp, node_set

    def verdicts(self, pred_rows: List[Any], gold_rows: List[Any], pred: str, gold: str,
                 execute: Executor) -> Tuple[Optional[bool], Optional[bool]]:
        strict = self.value_cmp(pred_rows, gold_rows, gold_cypher=gold)
        if self.node_set is None:
            return strict, None
        return self.node_set(strict, pred, gold, gold_rows, execute), strict


def benchmark_of(dataset: str) -> str:
    d = dataset.lower()
    for name in ("cypherbench", "mindthequery", "zograscope"):
        if d.startswith(name):
            return name
    raise ValueError(f"unknown dataset {dataset!r}")


def load_scorers(conn: Any) -> Dict[str, Scorer]:
    """The evaluators' own comparison functions. Importing them imports the agent
    stack, which connects to the Neo4j named by NEO4J_*; point it at a reachable
    graph first (any graph: the functions themselves do not query)."""
    for key, val in (("NEO4J_URI", conn.uri), ("NEO4J_USERNAME", conn.user),
                     ("NEO4J_PASSWORD", conn.password), ("NEO4J_DATABASE", conn.database)):
        os.environ[key] = val
    from eval import metrics_CypherBench as cb, metrics_MindTheQuery as mtq, metrics_ZOGRASCOPE as zg
    from eval.node_set_match import judge
    return {"cypherbench": Scorer(cb.execution_accuracy),
            "mindthequery": Scorer(mtq._execution_accuracy, judge),
            "zograscope": Scorer(zg._execution_accuracy, judge)}


def _is_timeout(err: str) -> bool:
    e = err.lower()
    return any(s in e for s in ("timeout", "timed out", "timedout", "terminated"))


def _is_write(err: str) -> bool:
    e = err.lower()
    return "access mode" in e or "accessmode" in e or "read access" in e


def rejudge_records(records: List[dict], scorer: Scorer, pred_exec: Executor, gold_exec: Executor,
                    node_exec: Executor, gold_cache: Dict[str, Any], compute_psjs=None,
                    graph: Any = None) -> Dict[str, int]:
    """Score the stale records of a chain run again, in place. Returns counts:
    ``checked``, ``changed`` (EA verdict differs), ``to_error`` (full result no
    longer runs within the timeout), ``kept_writes`` (a writing prediction, not
    run again). Raises when a gold query or a prediction fails for any other
    reason — it ran when the record was made, so that is the environment."""
    counts = {"checked": 0, "changed": 0, "to_error": 0, "kept_writes": 0}
    for r in records:
        if not is_stale(r):
            continue
        counts["checked"] += 1
        pred, gold = r.get("pred_cypher") or "", r.get("gold_cypher") or ""
        old_ea, old_psjs = r.get("ea"), r.get("psjs")
        if gold not in gold_cache:
            rows, err = gold_exec(gold)
            if err is not None:
                raise RuntimeError(f"gold query of {r.get('qid')} failed: {err}")
            gold_cache[gold] = rows
        pred_rows, err = pred_exec(pred) if pred.strip() else ([], None)   # no query: the chain's empty result
        if err is not None and _is_write(err):
            # a prediction with a writing clause is never run again here (the graph is only read): its verdict stays
            r["rows_rule"], r["rows_note"] = RULE, "not executed again: writing clause"
            counts["kept_writes"] += 1
            continue
        if err is not None:
            if not _is_timeout(err):
                raise RuntimeError(f"prediction of {r.get('qid')} failed: {err}")
            r["ea_capped"], r["psjs_capped"] = old_ea, old_psjs
            if "ea_strict" in r:
                r["ea_strict_capped"], r["ea_strict"] = r["ea_strict"], None
            r["ea"], r["psjs"] = None, None
            r["error"] = f"agent: RuntimeError: the generated Cypher did not run to completion: {err}"
            r["rows_rule"] = RULE
            counts["to_error"] += 1
            continue
        ea, strict = scorer.verdicts(pred_rows, gold_cache[gold], pred, gold, node_exec)
        r["ea_capped"] = old_ea
        if strict is not None:
            r["ea_strict"] = strict
        r["ea"] = ea
        if ea != old_ea:
            counts["changed"] += 1
            if compute_psjs is not None:
                new = compute_psjs(pred, gold, neo4j_graph=graph, ea_value=ea)
                if new != old_psjs:
                    r["psjs_capped"], r["psjs"] = old_psjs, new
        r["rows_rule"] = RULE
    return counts


def update_summary(summary: dict, records: List[dict], counts: Dict[str, int]) -> dict:
    out = dict(summary)
    n = len(records)
    out["n"] = n
    out["n_scored"] = {k: sum(1 for r in records if r.get(k) is not None) for k in ("ea", "em", "psjs")}
    out["n_errors"] = sum(1 for r in records if r.get("ea") is None)
    out["ea"] = _mean_true(records, lambda r: r.get("ea"))
    if "ea_strict" in out or any("ea_strict" in r for r in records):
        out["ea_strict"] = _mean_true(records, strict_value)
    out["psjs"] = _mean_psjs(records)
    if "by_difficulty" in out:
        out["by_difficulty"] = aggregate_by_difficulty(records)
    out["rows_rejudged"] = {"rule": RULE, "at": time.strftime("%Y-%m-%d %H:%M:%S"), **counts}
    return out


def rejudge_file(records_file: Path, scorer: Scorer, graphs: Tuple[Any, Any], gold_cache: Dict[str, Any], *,
                 dry_run: bool, compute_psjs=None) -> Dict[str, Any]:
    """*graphs* = (a read-only graph whose statements time out like the evaluation
    executor's, one with the longer timeout for gold queries, the node-set rule and PSJS)."""
    pred_graph, graph = graphs
    records = read_records(records_file)
    before = _mean_true(records, lambda r: r.get("ea"))
    counts = rejudge_records(records, scorer, capped_executor(pred_graph), capped_executor(graph),
                             capped_executor(graph), gold_cache, compute_psjs=compute_psjs, graph=graph)
    after = _mean_true(records, lambda r: r.get("ea"))
    if not dry_run:
        summary_file = records_file.with_name("summary.json")
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        _replace(records_file, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        _replace(summary_file, json.dumps(update_summary(summary, records, counts), ensure_ascii=False, indent=2))
    return {**counts, "n": len(records), "ea_before": before, "ea_after": after}


def _summary_of(records_file: Path) -> dict:
    try:
        return json.loads(records_file.with_name("summary.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="run directories, folders that contain them, or records.jsonl files "
                                             f"(default: {eval_paths.RUNS_ROOT}/)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    ap.add_argument("--force", action="store_true", help="also touch runs that look unfinished (never while one is running)")
    args = ap.parse_args(argv)

    roots = [Path(p) for p in args.paths] or [REPO / eval_paths.RUNS_ROOT]
    files = find_record_files([p if p.is_absolute() else Path.cwd() / p for p in roots])
    if not files:
        print("no records.jsonl found under: " + ", ".join(str(p) for p in roots))
        return 0

    from loguru import logger
    graphs: Dict[Tuple[str, str], Tuple[ReadOnlyGraph, ReadOnlyGraph]] = {}
    caches: Dict[Tuple[str, str], Dict[str, Any]] = {}
    scorers: Optional[Dict[str, Scorer]] = None
    compute_psjs = None
    done = skipped = failed = 0
    try:
        for f in files:
            rel = f.parent.relative_to(REPO) if f.parent.is_relative_to(REPO) else f.parent
            try:
                records = read_records(f)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {rel}: unreadable records.jsonl ({exc})"); failed += 1
                continue
            if not uses_chain(_summary_of(f), f.parent.name) or not any(is_stale(r) for r in records):
                continue                       # another method, or scored on full rows already
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
                conn = cfg.conn_for(*pair)
                if scorers is None:
                    scorers = load_scorers(conn)
                    from eval.psjs import compute_psjs
                    logger.disable("eval.psjs")    # its per-query warnings belong to a run's log, not this report
                if pair not in graphs:
                    graphs[pair] = (ReadOnlyGraph(conn.uri, conn.user, conn.password, conn.database, PRED_TIMEOUT),
                                    ReadOnlyGraph(conn.uri, conn.user, conn.password, conn.database, GOLD_TIMEOUT))
                    caches[pair] = {}
                res = rejudge_file(f, scorers[benchmark_of(pair[0])], graphs[pair], caches[pair],
                                   dry_run=args.dry_run, compute_psjs=compute_psjs)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {rel}: not changed — {type(exc).__name__}: {str(exc)[:300]}"); failed += 1
                continue
            done += 1
            extra = (f", {res['to_error']} no longer run within {PRED_TIMEOUT:.0f} s" if res["to_error"] else "") + \
                    (f", {res['kept_writes']} writing predictions kept" if res["kept_writes"] else "")
            print(f"  {'would change' if args.dry_run else 'rejudged'} {rel}: {res['changed']} of {res['checked']} "
                  f"verdicts changed{extra}; EA {res['ea_before']:.3f} -> {res['ea_after']:.3f} (n={res['n']})")
    finally:
        for pg, g in graphs.values():
            pg.close()
            g.close()
    verb = "would be re-judged" if args.dry_run else "re-judged"
    print(f"\n{done} run(s) {verb}, {skipped} skipped as unfinished, {failed} could not be handled, "
          f"{len(files) - done - skipped - failed} needed nothing (rule {RULE}).")
    if skipped:
        print("Run this again when the skipped runs have finished.")
    if failed:
        print("A run that could not be handled is left exactly as it was; run this again when its graph answers.")
    if done and not args.dry_run:
        print("Sweep runs: `python orchestrate_sweep.py --status` now shows them without ↻, and `--publish` rebuilds "
              "the report tables from the corrected records.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
