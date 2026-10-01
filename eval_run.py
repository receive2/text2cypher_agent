#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_run.py
===========
Subprocess driver for the per-graph text-to-Cypher evaluation harness.

For each ``(dataset, graph)`` pair listed in :data:`eval_config.EVAL_PAIRS`
this script:

    1. Looks up the :class:`eval_config.GraphConn` for the pair.
    2. Calls :func:`eval.artifact_swap.swap_in` to copy that graph's
       archived setup outputs (``schema_data/``, ``generated/`` tools,
       ``agent/prompts.py``, FAISS index, ``EMBEDDABLE_PROPERTIES``
       snippet) into the live repo locations.
    3. Spawns ``python -m eval._worker <dataset> <graph> ...`` as a
       fresh subprocess with the connection's URI / user / password /
       database injected via ``EVAL_NEO4J_*`` env vars.
    4. Captures the subprocess's exit code and continues to the next
       pair on failure (one bad pair never aborts the rest).

Per-pair output files
---------------------
For each pair it writes a canonical per-run directory (see :mod:`eval_paths`)::

    <OUT_DIR>/<dataset>__<graph>__<method>/records.jsonl   — one record per example
    <OUT_DIR>/<dataset>__<graph>__<method>/summary.json    — aggregate summary

The ``<method>`` segment (e.g. ``graphrag`` or ``cyanchor_fl``) is derived from
the resolved run config, so a five-method sweep into one ``OUT_DIR`` keeps each
method separate and ``eval_aggregate`` / the report generators can read them
back without any external prefix map.

Records and summaries from previous runs persist on disk; re-running
``eval_run.py`` for a different slice of ``EVAL_PAIRS`` adds new files
without touching old ones.  The bucketed table is **not** printed here
— run ``python eval_aggregate.py`` for that.

This script has no CLI flags.  Edit :mod:`eval_config` and re-run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple

import component_names
import eval_config as cfg
import eval_paths
from eval.artifact_swap import archive_dir_for, swap_in, _setup_artifacts_root
from paths import REPO_ROOT


# Mapping of dataset name → ``eval_config`` attribute that holds its
# test-set path.  The worker subprocess reads neither; the parent passes
# the resolved path on the command line.
#
# Augmented variants (``*_augmented``) point at separate test-set paths
# so the augmentation runner's output can be evaluated independently of
# the base data.  The base attribute is kept so existing call sites
# (and partial eval_config installs) keep working.
_PATH_ATTR = {
    "cypherbench":            "CYPHERBENCH_PATH",
    "cypherbench_augmented":  "CYPHERBENCH_AUGMENTED_PATH",
    "mindthequery":           "MINDTHEQUERY_PATH",
    "mindthequery_augmented": "MINDTHEQUERY_AUGMENTED_PATH",
    "zograscope":             "ZOGRASCOPE_PATH",
    "zograscope_augmented":   "ZOGRASCOPE_AUGMENTED_PATH",
}


def _resolve_test_path(dataset: str) -> str:
    attr = _PATH_ATTR.get(dataset)
    if attr is None:
        raise ValueError(
            f"Unknown dataset {dataset!r}; expected one of {sorted(_PATH_ATTR)}."
        )
    path = getattr(cfg, attr, None)
    if not path:
        raise ValueError(f"eval_config.{attr} is not set.")
    return path


# Run-config fields eval_config injects into the worker env — and, verbatim,
# the knob set recorded into each run's summary.json ``run_config`` block
# (module-level so _build_env and _stamp_summary stay in lockstep).
# These are the switch names. Five of them have a paper name the eval_config panel is
# written with (component_names.py); the paper name is an alias and is never recorded,
# so a run's knobs read the same before and after the aliases existed.
_STR  = ("METHOD", "TOOL_TYPE", "CYANCHOR_TOOL_SCOPE", "GENERATOR_LLM")
_BOOL = ("RETRIEVAL_FUZZY", "RETRIEVAL_VECTOR", "RETRIEVAL_LEVENSHTEIN",
         "CYPHER_SEMANTIC_REPAIR", "CYPHER_EMPTY_IS_WRONG",
         # ablation toggles (eval_config control panel) — config.py reads each
         "PLAN_EXEC_ESCALATE", "PLAN_EXEC_VALUE_SNAP", "PLAN_EXEC_SKIP_GROUNDED",
         "PLAN_EXEC_SELECT_JUDGE",
         "PLAN_EXEC_PARALLEL_MENTIONS", "GRAPHRAG_EMPTY_IS_WRONG", "GRAPHRAG_LLM_EVALUATOR")
_INT  = ("CYPHER_REPAIR_MAX_ROUNDS", "CYPHER_RETRY_MAX_ROUNDS", "RETRIEVAL_LEVENSHTEIN_K",
         # plan_exec retrieval-budget knobs (tuned on the dev graph)
         "PLAN_EXEC_TOOLS_PER_ENTITY", "PLAN_EXEC_VALUES_PER_TOOL",
         "PLAN_EXEC_MAX_ITER", "PLAN_EXEC_ROUTE_FETCH")
# tuple-valued knob, passed through as a comma string
_TUPLE = ("PLAN_EXEC_ESCALATE_BUDGET",)


def _stamp_summary(out_summary: Path, env: dict, *, dataset: str, graph: str,
                   method_seg: str, stamp: str, shards: int,
                   limit: int | None) -> None:
    """Embed the run's full configuration into ``summary.json``.

    The run-dir name carries only (dataset, graph, method, timestamp); the
    ``run_config`` block written here is what makes a run self-describing —
    LLM per stage, embedding backend, and every injected knob — so runs with
    different models or settings coexist and stay attributable. Best-effort:
    a failure to stamp never fails the run."""
    try:
        summary = json.loads(out_summary.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no/broken summary: nothing to stamp
        return
    llm: dict = {}
    try:
        import config as _config
        # Resolve the generator preset from the SAME env that tags the run dir
        # (GENERATOR_LLM injected by _build_env). The parent process never has
        # that env var itself, so reading config.*_LLM_CONFIG here would record
        # the static literals (gpt-4.1) for a run that actually used the preset.
        preset = env.get("GENERATOR_LLM") or None
        overlay: dict = {}
        if preset:
            spec = _config.resolve_preset(preset)
            params = spec.pop("params", None) or {}
            overlay = {**spec, **params}
        llm["generator_llm"] = preset
        for stage in ("NER", "CYPHER", "QA"):
            c = {**(getattr(_config, f"{stage}_LLM_CONFIG", None) or {}), **overlay}
            llm[stage.lower()] = {k: c.get(k) for k in ("provider", "model") if k in c}
    except Exception:  # noqa: BLE001
        pass
    embedding: dict = {}
    try:
        import vector_config as _vc
        embedding = {"backend": getattr(_vc, "EMBEDDING_BACKEND", None),
                     "model":   getattr(_vc, "EMBEDDING_MODEL_NAME", None)}
    except Exception:  # noqa: BLE001
        pass
    summary["run_config"] = {
        "stamp":     stamp,
        "dataset":   dataset,
        "graph":     graph,
        "method":    method_seg,
        "llm":       llm,
        "embedding": embedding,
        "knobs":     {k: env[k] for k in (*_STR, *_BOOL, *_INT, *_TUPLE) if k in env},
        "shards":    shards,
        "limit":     limit,
    }
    try:
        out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _active_model(env: dict) -> str:
    """Generator preset for the child run — the GENERATOR_LLM that _build_env
    just injected from eval_config (so the dir name and the worker's model come
    from one value), else config.py's resolution of its own literals."""
    m = env.get("GENERATOR_LLM")
    if m:
        return m
    try:
        import config as _c
        return _c.active_generator_model()
    except Exception:  # noqa: BLE001
        return ""


def _build_env(uri: str, user: str, password: str, database: str) -> dict[str, str]:
    """Copy the parent env and overlay the worker's connection vars + the run
    config from eval_config — the single, authoritative source for what runs.

    eval_config is authoritative: for every run-config field it sets, it
    *overrides* anything inherited from the shell, so a stale `export METHOD=…`
    can never silently win over the file you edited. A field eval_config leaves
    unset (``None``) falls through to config.py's default in the worker. The sweep
    driver (orchestrate_sweep.py) drives a sweep by mutating ``cfg.METHOD`` etc.
    in-process — same single surface, not a parallel env channel."""
    env = dict(os.environ)
    env["EVAL_NEO4J_URI"]      = uri
    env["EVAL_NEO4J_USER"]     = user
    env["EVAL_NEO4J_PASSWORD"] = password
    env["EVAL_NEO4J_DATABASE"] = database

    # ── run config from eval_config (cfg wins → overwrite, don't just fill) ──
    for name in _STR:
        v = getattr(cfg, name, None)
        if v is not None:
            env[name] = str(v)
    for name in _BOOL:
        v = component_names.panel_get(cfg, name)   # the switch, set under its own name or its paper name
        if v is not None:
            env[name] = "1" if v else "0"
            env.pop(component_names.ALIAS_OF.get(name, ""), None)   # cfg wins over a shell export under either name
    for name in _INT:
        v = getattr(cfg, name, None)
        if v is not None:
            env[name] = str(int(v))
    for name in _TUPLE:
        v = getattr(cfg, name, None)
        if v is not None:
            env[name] = ",".join(str(int(x)) for x in v)
    component_names.normalize_env(env)   # a switch cfg leaves unset: a shell export of its paper name becomes the switch
    return env


def _summarize_records(recs: list[dict], dataset: str) -> dict:
    """Recompute the headline summary from merged shard records, so the merged
    summary.json matches exactly what the report generators derive from the
    records (they read records.jsonl, not summary.json). ``err`` = #(ea is None),
    consistent with gen_ablation_report."""
    def _mean(key: str) -> float:
        """Denominator is ALL records: an example that errored scored 0, it is not
        excluded. This is the convention documented in gen_ablation_report and
        used by every report table — a query that does not run is a wrong
        answer. Excluding errors here would silently inflate the summary
        relative to the reports (~+0.01 EA measured)."""
        if not recs:
            return 0.0
        total = 0.0
        for r in recs:
            v = r.get(key)
            if v is True:
                total += 1.0
            elif v is None or v is False:
                continue
            else:
                total += float(v)
        return total / len(recs)

    return {
        "dataset":   dataset,
        "n":         len(recs),
        "n_scored":  {k: sum(1 for r in recs if r.get(k) is not None)
                      for k in ("ea", "em", "psjs")},
        "n_errors":  sum(1 for r in recs if r.get("ea") is None),
        "ea":        _mean("ea"),
        "em":        _mean("em"),
        "psjs":      _mean("psjs"),
    }


def _merge_shard_outputs(dataset: str, shard_recs: list[Path], shard_sums: list[Path],
                         out_records: Path, out_summary: Path, elapsed: float) -> Tuple[bool, str]:
    """Concatenate shard record files into the standard ``out_records`` and write
    a recomputed ``out_summary`` (headline metrics from the merged records +
    run_meta carried from the first shard). Stride shards partition the example
    set exactly, so the concatenation reproduces full single-process coverage."""
    lines: list[str] = []
    for rp in shard_recs:
        if rp.exists():
            lines += [l for l in rp.read_text(encoding="utf-8").splitlines() if l.strip()]
    out_records.parent.mkdir(parents=True, exist_ok=True)
    out_records.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")

    run_meta: dict = {}
    for sp in shard_sums:
        if sp.exists():
            try:
                run_meta = json.loads(sp.read_text(encoding="utf-8")).get("run_meta", {})
                break
            except Exception:  # noqa: BLE001
                pass

    recs = []
    for l in lines:
        try:
            recs.append(json.loads(l))
        except Exception:  # noqa: BLE001
            pass
    summary = _summarize_records(recs, dataset)
    summary["elapsed_sec"] = round(elapsed, 2)
    summary["shards"]      = len(shard_recs)
    summary["run_meta"]    = run_meta
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, "ok"


# ── Worker supervision: progress watchdog + resume after a worker death ──────
# A worker can die with questions still to run: the in-process watchdog's last
# resort (``os._exit(3)`` when a question cannot be interrupted, see
# metrics_CypherBench), a crash, or the outer timeout. Until 2026-09-30 that
# lost the whole graph (the pair failed and the driver started it over; on
# geography one hung question cost a 331-question run). The worker writes
# ``records.jsonl`` live, so the parent now relaunches it on the questions not
# yet recorded and merges the segments. A worker that is alive but records
# nothing for ``stall`` seconds is killed and treated the same way.
_ID_KEYS_BY_DATASET = {   # the evaluators' own id columns, in their order (metrics_*.py)
    "cypherbench":  ("qid", "id", "question_id", "gid"),
    "mindthequery": ("unique_id", "id", "qid", "question_id", "original_index"),
    "zograscope":   ("id", "qid", "question_id"),
}
_QUESTION_KEYS = ("nl", "question", "nl_question", "natural_language_question", "text")
_GOLD_KEYS     = ("gold_cypher", "cypher", "target_cypher", "ground_truth_cypher", "query")
_MAX_RESUMES   = 3


def _row_id(row: dict, dataset: str) -> str | None:
    for k in _ID_KEYS_BY_DATASET.get(dataset.replace("_augmented", ""), ("id",)):
        v = row.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def _first(row: dict, keys: tuple) -> str:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _read_records(path: Path) -> list[dict]:
    recs: list[dict] = []
    try:
        for l in path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    recs.append(json.loads(l))
                except Exception:  # noqa: BLE001 — a line cut by the kill
                    pass
    except FileNotFoundError:
        pass
    return recs


def _remaining_rows(test_path, dataset: str, graph: str, done: set[str]) -> tuple[list[dict], object] | None:
    """The rows of *graph* in the JSON test set whose id is not in *done*, in file order,
    plus the file's top-level layout (list or dict). ``None`` when the set cannot be resumed:
    not a JSON file, a row without an id, or ids that do not map one-to-one onto *done*."""
    p = Path(test_path)
    if p.suffix.lower() != ".json":
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    rows = obj.get("data") if isinstance(obj, dict) else obj
    if not isinstance(rows, list):
        return None
    graph_rows = [r for r in rows if isinstance(r, dict) and r.get("graph") == graph]
    ids = [_row_id(r, dataset) for r in graph_rows]
    if any(i is None for i in ids) or len(set(ids)) != len(ids):
        return None
    if sum(1 for i in ids if i in done) != len(done):
        return None
    return [r for r, i in zip(graph_rows, ids) if i not in done], obj


def _stalled_record(row: dict, dataset: str, graph: str, why: str) -> dict:
    """The record of a question the worker could not get past twice: an error, scored 0,
    shaped like the evaluators' error records so every report reads it."""
    from eval.difficulty import classify, strategy_of
    gold = _first(row, _GOLD_KEYS)
    return {"qid": _row_id(row, dataset), "question": _first(row, _QUESTION_KEYS),
            "ea": None, "em": None, "psjs": None, "pred_cypher": "", "gold_cypher": gold,
            "graph": graph, "difficulty": classify(gold), "error": f"example stalled: {why}",
            "strategy": strategy_of(row)}


def _supervise_worker(argv_for, *, dataset: str, graph: str, test_path, out_records: Path,
                      out_summary: Path, limit: int | None, env: dict, outer_timeout: float,
                      stall_sec: float, startup_grace: float = 300.0, poll_sec: float = 5.0,
                      max_resumes: int = _MAX_RESUMES) -> Tuple[bool, str]:
    """Run the worker to completion, resuming it after a death or a stall.

    *argv_for(test_path, out_records, out_summary, limit)* builds the worker command.
    Attempt 0 writes ``out_records`` / ``out_summary`` directly, so a run that needs no
    resume leaves exactly the files it always did. When an attempt ends without exit
    code 0, its records are kept as a segment and the worker is relaunched on the rows
    not yet recorded (same order, ``limit`` reduced by what is done), at most
    *max_resumes* times. A resumed attempt that recorded nothing is relaunched once more
    with its first question recorded as ``example stalled``, so one question that kills
    the worker every time costs that question, not the graph; a worker that records
    nothing twice in a row fails the pair. Segments are merged into
    ``out_records`` and a recomputed ``out_summary`` at the end."""
    pair_dir = out_records.parent
    t_all = time.time()
    segments: list[Path] = []
    done: set[str] = set()
    zero_progress = 0
    attempt = 0
    cur_test, cur_limit = test_path, limit
    last_summary: Path | None = None
    while True:
        seg_rec = out_records if attempt == 0 else pair_dir / f"segment_{attempt}.records.jsonl"
        seg_sum = out_summary if attempt == 0 else pair_dir / f"segment_{attempt}.summary.json"
        cmd = argv_for(cur_test, seg_rec, seg_sum, cur_limit)
        out_fh = open(pair_dir / f".worker_{attempt}.out", "w", encoding="utf-8")
        err_fh = open(pair_dir / f".worker_{attempt}.err", "w", encoding="utf-8")
        t0 = time.time()
        proc = subprocess.Popen(cmd, env=env, stdout=out_fh, stderr=err_fh, text=True)
        reason = ""
        last_size, last_change = -1, t0
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            now = time.time()
            if now - t0 > outer_timeout:
                proc.kill(); proc.wait()
                reason = f"worker timed out after {int(outer_timeout)}s"; rc = None
                break
            try:
                size = seg_rec.stat().st_size
            except FileNotFoundError:
                size = -1
            if size != last_size:
                last_size, last_change = size, now
            if now - last_change > stall_sec + (startup_grace if last_size <= 0 else 0.0):
                proc.kill(); proc.wait()
                reason = f"no new record for {int(now - last_change)}s (stall)"; rc = None
                break
            time.sleep(poll_sec)
        out_fh.close(); err_fh.close()
        out_txt = (pair_dir / f".worker_{attempt}.out").read_text(encoding="utf-8", errors="replace")
        err_txt = (pair_dir / f".worker_{attempt}.err").read_text(encoding="utf-8", errors="replace")
        (pair_dir / f".worker_{attempt}.out").unlink(missing_ok=True)
        (pair_dir / f".worker_{attempt}.err").unlink(missing_ok=True)
        if out_txt:
            sys.stdout.write(out_txt)
        if err_txt:
            sys.stderr.write(err_txt)
        recs = _read_records(seg_rec)
        added = len(recs)
        if rc == 0:
            last_summary = seg_sum
            break
        if reason:
            print(f"[eval_run] ⚠ {reason} on {dataset}__{graph}. Worker killed.", file=sys.stderr)
        else:
            reason = f"worker exited {rc}"
        tail = "\n".join(err_txt.splitlines()[-20:])
        if added == 0:
            zero_progress += 1
        else:
            zero_progress = 0
        # resume?  needs resumable rows, a budget, and progress (or one stalled question to skip)
        if attempt >= max_resumes or zero_progress > 1:
            if segments:
                _merge_segments(dataset, segments + [seg_rec], last_summary, out_records, out_summary, time.time() - t_all, attempt)
            return False, f"{reason}; stderr tail:\n{tail}"
        done |= {str(r.get("qid")) for r in recs if r.get("qid") is not None}
        rem = _remaining_rows(test_path, dataset, graph, done)
        if rem is None:
            if segments:
                _merge_segments(dataset, segments + [seg_rec], last_summary, out_records, out_summary, time.time() - t_all, attempt)
            return False, f"{reason} (not resumable: the test set is not a JSON file with one id per row); stderr tail:\n{tail}"
        rest, layout = rem
        if limit is not None:
            rest = rest[:max(0, limit - len(done))]
        if zero_progress == 1 and rest and done:
            # a resumed worker died before recording anything: it could not get past the
            # first remaining question twice — record that question, move on. (A worker that
            # records nothing on its very first attempt is relaunched once without skipping:
            # that is more likely a systematic failure than one bad question.)
            head = rest.pop(0)
            stalled = _stalled_record(head, dataset, graph, f"{reason}; skipped after two attempts")
            with open(seg_rec, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(stalled, ensure_ascii=False) + "\n")
            done.add(str(stalled["qid"]))
            print(f"[eval_run] ↻ {dataset}__{graph}: question {stalled['qid']} recorded as stalled and skipped.", file=sys.stderr)
        segments.append(seg_rec)
        if not rest:
            # everything is recorded; nothing left to run
            _merge_segments(dataset, segments, last_summary, out_records, out_summary, time.time() - t_all, attempt)
            return True, "ok"
        attempt += 1
        cur_test = pair_dir / f"segment_{attempt}.test.json"
        cur_test.write_text(json.dumps(rest if isinstance(layout, list) else {**layout, "data": rest}, ensure_ascii=False), encoding="utf-8")
        cur_limit = None
        print(f"[eval_run] ↻ {dataset}__{graph}: resuming after '{reason}' — {len(done)} questions recorded, "
              f"{len(rest)} to run (attempt {attempt}/{max_resumes}).", file=sys.stderr)
    if segments:
        _merge_segments(dataset, segments + [seg_rec], last_summary, out_records, out_summary, time.time() - t_all, attempt)
    return True, "ok"


def _merge_segments(dataset: str, seg_recs: list[Path], last_summary: Path | None,
                    out_records: Path, out_summary: Path, elapsed: float, resumes: int) -> None:
    """Concatenate the segments of a resumed run into ``out_records`` (file order = question
    order) and write a recomputed ``out_summary``; the segment files are removed."""
    lines: list[str] = []
    for rp in seg_recs:
        if rp.exists():
            lines += [l for l in rp.read_text(encoding="utf-8").splitlines() if l.strip()]
    run_meta: dict = {}
    if last_summary is not None and last_summary.exists():
        try:
            run_meta = json.loads(last_summary.read_text(encoding="utf-8")).get("run_meta", {})
        except Exception:  # noqa: BLE001
            pass
    recs = []
    for l in lines:
        try:
            recs.append(json.loads(l))
        except Exception:  # noqa: BLE001
            pass
    summary = _summarize_records(recs, dataset)
    summary["elapsed_sec"] = round(elapsed, 2)
    summary["resumed"]     = resumes
    summary["run_meta"]    = run_meta
    tmp = out_records.with_suffix(".jsonl.tmp")
    tmp.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    tmp.replace(out_records)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for rp in seg_recs:
        if rp != out_records:
            rp.unlink(missing_ok=True)
            rp.with_name(rp.name.replace(".records.jsonl", ".summary.json")).unlink(missing_ok=True)
            rp.with_name(rp.name.replace(".records.jsonl", ".test.json")).unlink(missing_ok=True)


_FLAT_OUTER_SEC = 4 * 60 * 60   # floor of a full-graph run; the ceiling when the graph's size is unknown


def _count_examples(test_path, graph: str) -> int | None:
    """How many questions a full run of *graph* holds: the rows of the JSON test set whose
    ``graph`` field is *graph*. ``None`` when that cannot be read off the file (the clean CSV
    sets, an unexpected layout, a graph without rows) — the caller then keeps the flat ceiling."""
    try:
        p = Path(test_path)
        if p.suffix.lower() != ".json":
            return None
        obj = json.loads(p.read_text(encoding="utf-8"))
        rows = obj.get("data") if isinstance(obj, dict) else obj
        n = sum(1 for r in rows if isinstance(r, dict) and r.get("graph") == graph)
        return n or None
    except Exception:  # noqa: BLE001
        return None


def _outer_timeout_sec(n_per_proc: int | None, *, limited: bool, per_example_sec: int,
                       explicit: str | None) -> float:
    """Outer safety net for one worker process, in seconds.

    * ``EVAL_WORKER_TIMEOUT_SEC`` (*explicit*) wins.
    * A run with ``LIMIT`` set (*limited*): ``n × per_example_sec + 120``, as before.
    * A full-graph run: the same formula on the graph's question count, never below the
      former flat 4 h. A large graph is therefore no longer killed mid-run (pole, 1,283
      questions, needs 4.3–4.6 h with CyANCHOR and was cut at 4 h), and no graph gets
      less time than it had.
    * Size unknown: the flat 4 h.

    The limit stays because only the CypherBench evaluator has a per-question watchdog;
    for the MindTheQuery and ZOGRASCOPE graphs this is the one guard against a hung worker."""
    if explicit:
        return float(explicit)
    if n_per_proc is None:
        return float(_FLAT_OUTER_SEC)
    scaled = n_per_proc * per_example_sec + 120
    return float(scaled if limited else max(_FLAT_OUTER_SEC, scaled))


def _run_pair(
    dataset:     str,
    graph:       str,
    out_dir:     Path,
    *,
    limit:       int | None,
    verbose:     bool,
) -> Tuple[bool, str]:
    """
    Run one (dataset, graph) pair end-to-end.  Returns ``(ok, status_msg)``.

    On any failure (archive missing, subprocess non-zero, exception
    during swap_in) returns ``(False, "<reason>")`` and does not raise.
    The caller logs the reason and moves on.

    Output lands in the canonical per-run dir
    ``<out_dir>/<dataset>__<graph>__<method>/{records.jsonl,summary.json}`` —
    the method segment is derived (below) from the resolved run config so a
    five-method sweep into one ``out_dir`` keeps each method's records separate
    and self-describing (see :mod:`eval_paths`).
    """
    # ── Step 1: swap in archived artifacts ──────────────────────────────────
    try:
        swap_in(dataset, graph)
    except FileNotFoundError as exc:
        return False, f"swap_in: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"swap_in: {type(exc).__name__}: {exc}"

    # ── Step 1.5: published-set guard ───────────────────────────────────────
    # Results are only poolable if every generator saw byte-identical prompts
    # and tools, so an archive that differs from setup_artifacts/MANIFEST.json
    # is refused (coordinator: after a rebuild, run
    # `python scripts/artifact_manifest.py build` first). A graph the manifest
    # does not cover yet only warns. Bypass with EVAL_SKIP_MANIFEST_GUARD=1.
    if os.environ.get("EVAL_SKIP_MANIFEST_GUARD") != "1":
        from scripts import artifact_manifest as am
        root = _setup_artifacts_root()
        mstatus, mdetail = am.check_pair(am.load_manifest(am.manifest_path(root)), root, dataset, graph)
        if mstatus in (am.MISMATCH, am.MISSING):
            return False, f"published-set guard: {mstatus} — {mdetail}"
        if mstatus == am.UNPUBLISHED:
            print(f"[eval_run] ! {dataset}__{graph}: {mdetail} — running on an unpublished archive.")

    # ── Step 1.6: the fcav method needs its value index ─────────────────────
    if str(getattr(cfg, "METHOD", "") or "").strip().lower() == "fcav":
        if not (archive_dir_for(dataset, graph) / "generated" / "fcav").is_dir():
            return False, ("fcav: no generated/fcav/ index in this graph's archive — build it with "
                           "`python setup_fcav.py` (EVAL_PAIRS = this pair) or unpack the coordinator's bundle")

    # ── Step 2: connection lookup ───────────────────────────────────────────
    try:
        conn = cfg.conn_for(dataset, graph)
    except KeyError as exc:
        return False, f"conn_for: {exc}"

    # ── Step 2.5: graph-identity guard ──────────────────────────────────────
    # The swap copies artifacts into a single shared live tree; nothing else
    # checks that those artifacts belong to THIS graph. Ask the database
    # directly whether the live node tools search labels that exist here. A
    # mismatch means a contaminated archive — fail loud instead of silently
    # scoring at the no-val-link floor. Bypass with EVAL_SKIP_GRAPH_GUARD=1.
    if os.environ.get("EVAL_SKIP_GRAPH_GUARD") != "1":
        try:
            from eval.graph_guard import check_tools_match_graph
            ok, detail = check_tools_match_graph(
                REPO_ROOT / "generated" / "generated_node_tools.py",
                conn.uri, conn.user, conn.password, conn.database,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"graph_guard: {type(exc).__name__}: {exc}"
        if not ok:
            return False, f"graph_guard: {detail}"

    # ── Step 3: resolve test path ───────────────────────────────────────────
    try:
        test_path = _resolve_test_path(dataset)
    except ValueError as exc:
        return False, f"test path: {exc}"

    # ── Step 4: subprocess launch ───────────────────────────────────────────
    env = _build_env(conn.uri, conn.user, conn.password, conn.database)
    shards = int(getattr(cfg, "SHARDS", 1) or 1)

    # Canonical per-run output dir. The method + arms come from the resolved env
    # (_build_env has already overlaid eval_config / shell), so the dir name is a
    # faithful label of what actually ran.
    # The generator model is part of the dir name: readers resolve a triple to a
    # single dir, so without it a second model's run is just a newer stamp and
    # every report would silently switch to it.
    _tag = eval_paths.method_tag(
        env.get("METHOD", "cyanchor"),
        fuzzy  = env.get("RETRIEVAL_FUZZY", "1") == "1",
        vector = env.get("RETRIEVAL_VECTOR", "0") == "1",
        lev    = env.get("RETRIEVAL_LEVENSHTEIN", "1") == "1",
        model  = _active_model(env),
    )
    stamp    = eval_paths.new_stamp()
    pair_dir = eval_paths.run_dir(dataset, graph, _tag, root=out_dir, stamp=stamp)
    pair_dir.mkdir(parents=True, exist_ok=True)
    out_records = pair_dir / "records.jsonl"
    out_summary = pair_dir / "summary.json"

    # ── Outer subprocess timeout ────────────────────────────────────────────
    # The per-example wall-clock cap lives inside the worker (see
    # ``EVAL_PER_EXAMPLE_TIMEOUT`` / the watchdog in
    # ``metrics_CypherBench.evaluate_dataset``).  This subprocess timeout is the
    # *outer* safety net — sized to comfortably hold a process's example count
    # at the per-example cap plus startup overhead (FAISS load + Neo4j connect
    # + dataset parse ≈ 30–60 s). Under sharding each worker runs ~limit/shards
    # examples, so the cap is sized per shard. ``EVAL_WORKER_TIMEOUT_SEC``
    # overrides. A full-graph run (``limit is None``) is sized by the graph's
    # question count and never gets less than 4 h (see _outer_timeout_sec).
    per_example_sec = int(os.environ.get("EVAL_PER_EXAMPLE_TIMEOUT", "60")) + 5
    explicit_outer  = os.environ.get("EVAL_WORKER_TIMEOUT_SEC")
    n_total = limit if limit is not None else _count_examples(test_path, graph)

    def _outer_timeout(n_per_proc: int | None) -> float:
        return _outer_timeout_sec(n_per_proc, limited=limit is not None,
                                  per_example_sec=per_example_sec, explicit=explicit_outer)

    if shards <= 1:
        # ── single-process path, supervised: progress watchdog + resume ─────
        def _argv(tp, rec, summ, lim) -> List[str]:
            c: List[str] = [sys.executable, "-m", "eval._worker", dataset, graph, str(tp), str(rec), str(summ)]
            if lim is not None:
                c += ["--limit", str(lim)]
            if verbose:
                c += ["--verbose"]
            return c
        outer_timeout = _outer_timeout(n_total)
        stall_sec = float(os.environ.get("EVAL_STALL_SEC", str(max(4 * per_example_sec + 60, 300))))
        print(
            f"\n[eval_run] ▶ {dataset}__{graph}  uri={conn.uri}  db={conn.database}  "
            f"outer_timeout={int(outer_timeout)}s  stall={int(stall_sec)}s"
        )
        ok, msg = _supervise_worker(_argv, dataset=dataset, graph=graph, test_path=test_path,
                                    out_records=out_records, out_summary=out_summary, limit=limit,
                                    env=env, outer_timeout=outer_timeout, stall_sec=stall_sec)
        if not ok:
            return False, msg
        _stamp_summary(out_summary, env, dataset=dataset, graph=graph,
                       method_seg=_tag, stamp=stamp, shards=1, limit=limit)
        return True, "ok"

    # ── sharded path (SHARDS > 1): K parallel workers over example strides ───
    # All shards target the same already-swapped live tree + container; they
    # only differ in which stride of examples they run. Merged afterwards.
    per_proc = None if n_total is None else max(1, -(-n_total // shards))  # ceil
    outer_timeout = _outer_timeout(per_proc)
    shard_dir = pair_dir / ".shards"
    if shard_dir.exists():
        shutil.rmtree(shard_dir, ignore_errors=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"\n[eval_run] ▶ {dataset}__{graph}  uri={conn.uri}  db={conn.database}  "
        f"shards={shards}  per-shard outer_timeout={int(outer_timeout)}s"
    )
    shard_recs: list[Path] = []
    shard_sums: list[Path] = []
    procs: list[subprocess.Popen] = []
    for k in range(shards):
        rec_k = shard_dir / f"shard_{k}.records.jsonl"
        sum_k = shard_dir / f"shard_{k}.summary.json"
        shard_recs.append(rec_k)
        shard_sums.append(sum_k)
        cmd = [
            sys.executable, "-m", "eval._worker",
            dataset, graph, str(test_path), str(rec_k), str(sum_k),
            "--shard", str(k), "--shards", str(shards),
        ]
        if limit is not None:
            cmd += ["--limit", str(limit)]
        if verbose:
            cmd += ["--verbose"]
        procs.append(subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True))

    start = time.monotonic()
    deadline = start + outer_timeout
    errors: list[str] = []
    for k, p in enumerate(procs):
        remaining = max(1.0, deadline - time.monotonic())
        try:
            stdout, stderr = p.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            p.kill()
            stdout, stderr = p.communicate()
            errors.append(f"shard {k}: timeout after {int(outer_timeout)}s")
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
        if p.returncode not in (0, None) and not any(f"shard {k}:" in e for e in errors):
            tail = "\n".join((stderr or "").splitlines()[-10:])
            errors.append(f"shard {k}: exit {p.returncode}; {tail}")
    elapsed = time.monotonic() - start

    if errors:
        for p in procs:                       # kill any stragglers
            if p.poll() is None:
                p.kill()
        return False, "sharded run failed: " + " | ".join(errors)

    ok, msg = _merge_shard_outputs(dataset, shard_recs, shard_sums,
                                   out_records, out_summary, elapsed)
    shutil.rmtree(shard_dir, ignore_errors=True)
    if ok:
        _stamp_summary(out_summary, env, dataset=dataset, graph=graph,
                       method_seg=_tag, stamp=stamp, shards=shards, limit=limit)
    return ok, msg


def main() -> int:
    out_dir = Path(getattr(cfg, "OUT_DIR", "logs/eval"))
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs: List[Tuple[str, str]] = list(getattr(cfg, "EVAL_PAIRS", []) or [])
    if not pairs:
        print(
            "[eval_run] eval_config.EVAL_PAIRS is empty — nothing to do. "
            "Edit eval_config.py and re-run.",
            file=sys.stderr,
        )
        return 1

    statuses: list[tuple[str, str, bool, str]] = []
    for dataset, graph in pairs:
        ok, msg = _run_pair(
            dataset, graph, out_dir,
            limit   = getattr(cfg, "LIMIT", None),
            verbose = bool(getattr(cfg, "VERBOSE", False)),
        )
        statuses.append((dataset, graph, ok, msg))
        if not ok:
            print(f"[eval_run] ✗ {dataset}__{graph}: {msg}", file=sys.stderr)

    # ── Final per-pair status line ─────────────────────────────────────────
    print("\n══ eval_run summary ══")
    for dataset, graph, ok, msg in statuses:
        mark = "✓" if ok else "✗"
        suffix = "" if ok else f"  ({msg.splitlines()[0]})"
        print(f"  {mark} {dataset}__{graph}{suffix}")
    print(
        "\nRun `python eval_aggregate.py` to print the bucketed metric table "
        f"over everything currently in {out_dir}."
        "\nNOTE: that table is for development only. For the model sweep, run "
        "`python orchestrate_sweep.py` instead — it is the only path that "
        "checks completeness, writes report/<model>/SWEEP.md and publishes the "
        "branch (docs/EXPERIMENT_HANDOUT.md)."
    )

    # Exit non-zero iff every pair failed; partial success returns 0 so
    # the user can still aggregate what landed on disk.
    if statuses and all(not ok for _, _, ok, _ in statuses):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
