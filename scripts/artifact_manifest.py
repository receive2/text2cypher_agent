#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/artifact_manifest.py
============================
Publish / verify the **shared** per-graph setup artifacts.

Every model owner must evaluate with byte-identical prompts, tools, schema
files and tool-routing index for each graph — otherwise the model comparison
is confounded by whatever `setup_project.py` (an LLM step) happened to
generate on each machine. So the small, model-independent parts of every
``setup_artifacts/<dataset>__<graph>/`` archive are committed to git together
with this manifest (one sha256 per file), and every checkout is checked
against it before an evaluation runs (``verify_setup.py``).

The large indexes (``generated/fcav``, ``generated/chess``) are distributed
separately and are *not* covered by the manifest.

    python scripts/artifact_manifest.py build           # coordinator: (re)write MANIFEST.json from the local archives
    python scripts/artifact_manifest.py check           # everyone: are my archives == the published set?  (EVAL_PAIRS)
    python scripts/artifact_manifest.py check --all     # every pair in the manifest

An archive is only published if it passes the identity gate: every required
file present and both FAISS fingerprints stamped with the archive's own pair
name — an index built for another graph (the 2026-07 pollution) can never be
published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from eval.artifact_swap import (  # noqa: E402
    SWAP_DIRS, SWAP_FILES, SWAP_FILES_OPTIONAL, _SNIPPET_NAME, _setup_artifacts_root,
)

MANIFEST_NAME = "MANIFEST.json"
SCHEMA_VERSION = 1

OK, MISMATCH, MISSING, UNPUBLISHED = "OK", "MISMATCH", "MISSING", "UNPUBLISHED"


# ──────────────────────────────────────────────────────────────────────────────
# What is published
# ──────────────────────────────────────────────────────────────────────────────

def pair_name(dataset: str, graph: str) -> str:
    return f"{dataset}__{graph}"


def published_rel_paths(archive: Path) -> List[str]:
    """Relative paths of the files the manifest covers for one archive: the
    swap contract of :mod:`eval.artifact_swap` minus the large optional dirs."""
    rels: List[str] = []
    for rel in SWAP_FILES:
        rels.append(rel)
    for rel in SWAP_FILES_OPTIONAL:
        if (archive / rel).is_file():
            rels.append(rel)
    for d in SWAP_DIRS:
        base = archive / d
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    rels.append(p.relative_to(archive).as_posix())
    rels.append(_SNIPPET_NAME)
    return sorted(set(rels))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _faiss_stamp(archive: Path, sub: str) -> Optional[str]:
    fp = archive / sub / "fingerprint.json"
    if not fp.is_file():
        return None
    try:
        return (json.loads(fp.read_text(encoding="utf-8")).get("identity") or {}).get("pair")
    except (OSError, ValueError):
        return None


def gate(pair: str, archive: Path) -> List[str]:
    """Problems that make an archive unpublishable (empty list = passes)."""
    problems: List[str] = []
    if not archive.is_dir():
        return [f"no archive at {archive}"]
    for rel in SWAP_FILES + [_SNIPPET_NAME]:
        if not (archive / rel).is_file():
            problems.append(f"missing {rel}")
    for d in SWAP_DIRS:
        if not (archive / d).is_dir():
            problems.append(f"missing {d}/")
            continue
        stamp = _faiss_stamp(archive, d)
        if stamp != pair:
            problems.append(f"{d} is stamped for {stamp!r}, not {pair!r}")
    return problems


# ──────────────────────────────────────────────────────────────────────────────
# Build / load
# ──────────────────────────────────────────────────────────────────────────────

def _git_commit() -> Optional[str]:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_REPO,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return None


def set_id(pairs: Dict[str, dict]) -> str:
    """Short id of the whole published set (order-independent)."""
    h = hashlib.sha256()
    for pair in sorted(pairs):
        for rel, sha in sorted(pairs[pair]["files"].items()):
            h.update(f"{pair}\t{rel}\t{sha}\n".encode())
    return h.hexdigest()[:12]


def build(root: Path, pairs: Iterable[Tuple[str, str]], commit: Optional[str] = None
          ) -> Tuple[dict, Dict[str, List[str]]]:
    """Return ``(manifest, excluded)``; ``excluded`` maps a pair to the gate
    problems that kept it out."""
    entries: Dict[str, dict] = {}
    excluded: Dict[str, List[str]] = {}
    for dataset, graph in pairs:
        pair = pair_name(dataset, graph)
        archive = root / pair
        problems = gate(pair, archive)
        if problems:
            excluded[pair] = problems
            continue
        files = {rel: _sha256(archive / rel) for rel in published_rel_paths(archive)}
        entries[pair] = {"dataset": dataset, "graph": graph, "n_files": len(files),
                         "bytes": sum((archive / rel).stat().st_size for rel in files),
                         "files": files}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": commit if commit is not None else _git_commit(),
        "set_id": set_id(entries),
        "covers": "prompts, generated tools, schema files, tool-routing FAISS index "
                  "(eval.artifact_swap SWAP_FILES/SWAP_DIRS); NOT generated/fcav or generated/chess",
        "pairs": entries,
    }
    return manifest, excluded


def manifest_path(root: Optional[Path] = None) -> Path:
    return (root or _setup_artifacts_root()) / MANIFEST_NAME


def load_manifest(path: Optional[Path] = None) -> Optional[dict]:
    p = path or manifest_path()
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Check
# ──────────────────────────────────────────────────────────────────────────────

def check_pair(manifest: Optional[dict], root: Path, dataset: str, graph: str) -> Tuple[str, str]:
    """Compare one local archive with the published set.

    Returns ``(status, detail)`` with status one of OK / MISMATCH / MISSING /
    UNPUBLISHED. MISMATCH lists the differing / missing / extra files."""
    pair = pair_name(dataset, graph)
    if not manifest or pair not in manifest.get("pairs", {}):
        return UNPUBLISHED, "not in the published set (the coordinator has not published this graph yet)"
    archive = root / pair
    if not archive.is_dir():
        return MISSING, f"no archive at {archive} — git pull (the published files ship in the repo)"
    want: Dict[str, str] = manifest["pairs"][pair]["files"]
    have = {rel: _sha256(archive / rel) for rel in published_rel_paths(archive) if (archive / rel).is_file()}
    changed = sorted(rel for rel in want if rel in have and have[rel] != want[rel])
    absent = sorted(rel for rel in want if rel not in have)
    extra = sorted(rel for rel in have if rel not in want)
    if not (changed or absent or extra):
        return OK, f"= published set {manifest.get('set_id', '?')} ({len(want)} files)"
    parts = []
    if changed:
        parts.append("differs: " + ", ".join(changed))
    if absent:
        parts.append("missing: " + ", ".join(absent))
    if extra:
        parts.append("not in set: " + ", ".join(extra))
    return MISMATCH, "; ".join(parts)


def check(manifest: Optional[dict], root: Path, pairs: Iterable[Tuple[str, str]]) -> Dict[str, Tuple[str, str]]:
    return {pair_name(d, g): check_pair(manifest, root, d, g) for d, g in pairs}


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _eval_pairs(all_pairs: bool, manifest: Optional[dict]) -> List[Tuple[str, str]]:
    import eval_config as cfg  # noqa: WPS433 — repo module
    if all_pairs:
        if manifest:
            return [(e["dataset"], e["graph"]) for e in manifest["pairs"].values()]
        return list(cfg.FULL_EVAL_PAIRS_13_AUGMENTED)
    return list(cfg.EVAL_PAIRS)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="(coordinator) write MANIFEST.json from the local archives")
    b.add_argument("--strict", action="store_true", help="fail if any of the 13 pairs is excluded by the identity gate")
    c = sub.add_parser("check", help="compare local archives with the published set")
    c.add_argument("--all", action="store_true", help="every pair in the manifest instead of eval_config.EVAL_PAIRS")
    args = ap.parse_args(argv)

    root = _setup_artifacts_root()
    if args.cmd == "build":
        import eval_config as cfg
        manifest, excluded = build(root, cfg.FULL_EVAL_PAIRS_13_AUGMENTED)
        write_manifest(manifest, manifest_path(root))
        print(f"[artifact_manifest] wrote {manifest_path(root)}  set_id={manifest['set_id']}  "
              f"commit={(manifest['commit'] or '?')[:9]}")
        for pair, e in manifest["pairs"].items():
            print(f"  ✓ {pair:45s} {e['n_files']:3d} files  {e['bytes'] / 1e6:6.2f} MB")
        for pair, problems in excluded.items():
            print(f"  ✗ {pair:45s} EXCLUDED — " + "; ".join(problems))
        print(f"[artifact_manifest] {len(manifest['pairs'])} published, {len(excluded)} excluded")
        return 1 if (args.strict and excluded) else 0

    manifest = load_manifest(manifest_path(root))
    if manifest is None:
        print(f"[artifact_manifest] ✗ no {MANIFEST_NAME} under {root} — git pull; the published set ships in the repo")
        return 1
    results = check(manifest, root, _eval_pairs(args.all, manifest))
    bad = 0
    for pair, (status, detail) in results.items():
        mark = {OK: "✓", UNPUBLISHED: "!"}.get(status, "✗")
        bad += status in (MISMATCH, MISSING)
        print(f"  {mark} {pair:45s} {status:11s} {detail}")
    print(f"[artifact_manifest] published set {manifest.get('set_id')} (built {manifest.get('built_at')}, "
          f"commit {(manifest.get('commit') or '?')[:9]}): {len(results) - bad}/{len(results)} match")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
