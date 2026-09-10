#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit_artifact_identity.py
==================================
Audit (and optionally migrate) identity stamps on per-graph generated
artifacts across all setup archives + the live tree.

Checks, per archive ``setup_artifacts/<dataset>__<graph>/``:

1. **Stamp mismatch** — an index dir stamped for a different pair than the
   archive it sits in. CRITICAL: proven cross-graph pollution.
2. **Cross-archive duplicates** — the same index content appearing under two
   or more archives. CRITICAL: per-graph value/tool indexes are never
   legitimately identical across graphs (this is exactly the 2026-07 FCAV
   incident signature: geography's index copied into four MTQ archives).
3. **Unstamped (legacy) dirs** — built before identity stamps existed.
   Reported as ADOPTABLE when their content is unique across archives.

``--adopt`` stamps every ADOPTABLE dir with its archive's pair name (the
archive dir name is the harness's ground truth for what the archive holds).
Dirs implicated in a duplicate group are NEVER adopted — delete the polluted
copies and rebuild them for their graphs (setup_fcav.py / setup_project.py).

The live tree is audited against the ``.current_setup`` sentinel but never
adopted (live state is transient; archives are the durable record).

Usage
-----
    python scripts/audit_artifact_identity.py            # report only
    python scripts/audit_artifact_identity.py --adopt    # + stamp adoptables
    python scripts/audit_artifact_identity.py --root setup_artifacts.bak

Exit status: 1 if any CRITICAL finding remains, else 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eval.artifact_identity import (  # noqa: E402
    ArtifactIdentityError,
    current_pair,
    pairs_equivalent,
    read_identity,
    split_pair,
    stamp_dir,
)

#: Per-graph artifact dirs to audit (relative to an archive root or the live
#: repo root). Mirrors artifact_swap's SWAP_DIRS + SWAP_DIRS_OPTIONAL index
#: dirs; extend when a new per-graph index kind is added (e.g. generated/chess).
TARGET_RELS: List[str] = [
    "generated/fcav",
    "generated/faiss/tools_auto",
    "generated/faiss/tools_auto_node_only",
    "generated/chess",
]

_HEAD_BYTES = 8 * 1024 * 1024  # hash the first 8 MB of big binaries


def _content_key(d: Path) -> str:
    """
    Cheap content fingerprint of an index dir: full hash of every small JSON
    (meta/manifest minus any identity block) + size and head-hash of every
    other file. Robust to identity stamping (stamps must not change the key).
    """
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(d))
        h.update(rel.encode())
        if p.suffix == ".json":
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    obj.pop("identity", None)
                h.update(json.dumps(obj, sort_keys=True).encode())
                continue
            except (OSError, json.JSONDecodeError):
                pass  # fall through to binary hashing
        st = p.stat()
        h.update(str(st.st_size).encode())
        with p.open("rb") as fh:
            h.update(fh.read(_HEAD_BYTES))
    return h.hexdigest()[:16]


def _fmt(d: Dict[str, Any]) -> str:
    ident = d["identity"]
    stamp = ident["pair"] if ident else "UNSTAMPED"
    extra = f" count={d['count']}" if d["count"] is not None else ""
    return f"{d['pair']:<45} {d['rel']:<38} stamp={stamp}{extra} key={d['key']}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 3)[3].split("\n")[0])
    ap.add_argument("--root", default=None,
                    help="archive root to audit (default: eval_config."
                         "SETUP_ARTIFACTS_ROOT, falling back to setup_artifacts/)")
    ap.add_argument("--adopt", action="store_true",
                    help="stamp unstamped, non-duplicated archive dirs with "
                         "their archive's pair name")
    ap.add_argument("--claim", nargs=2, metavar=("PAIR", "REL"), default=None,
                    help="manually stamp ONE archive dir (e.g. --claim "
                         "cypherbench_augmented__geography generated/fcav) — "
                         "records the human judgment that this archive is the "
                         "true owner of content the audit flagged as "
                         "duplicated. The OTHER members of the duplicate "
                         "group must still be deleted and rebuilt.")
    args = ap.parse_args()

    if args.root:
        root = Path(args.root)
    else:
        try:
            from eval_config import SETUP_ARTIFACTS_ROOT  # noqa: WPS433
            root = Path(SETUP_ARTIFACTS_ROOT)
        except (ImportError, AttributeError):
            root = Path("setup_artifacts")
        if not root.is_absolute():
            root = _REPO_ROOT / root
    if not root.is_dir():
        sys.exit(f"[audit] archive root not found: {root}")

    if args.claim:
        pair, rel = args.claim
        d = root / pair / rel
        if not d.is_dir():
            sys.exit(f"[claim] not a directory: {d}")
        dataset, graph = split_pair(pair)
        stamp_dir(d, dataset, graph)
        print(f"[claim] stamped {d} as {pair} (manual ownership claim). "
              "Delete + rebuild the other members of its duplicate group, "
              "then rerun the audit.")
        return 0

    # ── Scan archives ────────────────────────────────────────────────────────
    entries: List[Dict[str, Any]] = []
    critical = 0
    for arch in sorted(root.iterdir()):
        if not arch.is_dir() or "__" not in arch.name:
            continue
        if arch.is_symlink():
            # Sibling dedupe: clean archives may symlink to their augmented
            # twin (same graph). Legitimate iff the pairs are equivalent;
            # anything else is a mis-wired archive.
            target = arch.resolve().name
            if pairs_equivalent(arch.name, target):
                print(f"symlink   {arch.name} → {target} (same graph — shares "
                      "its artifacts; skipping duplicate scan)")
            else:
                critical += 1
                print(f"CRITICAL  {arch.name} is a symlink to {target}, which "
                      "is a DIFFERENT graph — mis-wired archive.")
            continue
        for rel in TARGET_RELS:
            d = arch / rel
            if not d.is_dir():
                continue
            try:
                ident = read_identity(d)
            except ArtifactIdentityError as exc:
                print(f"CRITICAL  corrupt carrier: {d}\n          {exc}")
                ident = None
            count: Optional[int] = None
            for carrier in ("manifest.json", "fingerprint.json"):
                cp = d / carrier
                if cp.is_file():
                    try:
                        count = json.loads(cp.read_text(encoding="utf-8")).get(
                            "count", json.loads(cp.read_text(encoding="utf-8")).get("tool_count"))
                    except (OSError, json.JSONDecodeError):
                        pass
                    break
            entries.append({
                "pair": arch.name, "rel": rel, "dir": d,
                "identity": ident, "count": count, "key": _content_key(d),
            })

    # ── Findings ─────────────────────────────────────────────────────────────
    dup_groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for e in entries:
        dup_groups[(e["rel"], e["key"])].append(e)
    duplicated_dirs = set()
    print(f"[audit] scanned {len(entries)} index dirs under {root}\n")
    for (rel, key), grp in sorted(dup_groups.items()):
        if len(grp) < 2:
            continue
        # Clean/augmented siblings share the SAME graph (same connection in
        # eval_config.GRAPH_CONNS) — identical content there is legitimate.
        all_same_graph = all(pairs_equivalent(grp[0]["pair"], e["pair"])
                             for e in grp[1:])
        pairs = ", ".join(e["pair"] for e in grp)
        if all_same_graph:
            print(f"ok-shared duplicate {rel} across clean/augmented siblings "
                  f"of one graph (key={key}): {pairs}")
            continue
        critical += 1
        for e in grp:
            duplicated_dirs.add(e["dir"])
        print(f"CRITICAL  duplicate {rel} content (key={key}) shared by "
              f"DIFFERENT graphs: {pairs}\n"
              f"          Per-graph indexes are never legitimately identical "
              f"across graphs — keep the true owner, delete the rest, rebuild "
              f"for their graphs.")

    for e in entries:
        ident = e["identity"]
        if ident and not pairs_equivalent(ident.get("pair"), e["pair"]):
            critical += 1
            print(f"CRITICAL  stamp mismatch: {e['dir']} stamped "
                  f"{ident.get('pair')!r} inside archive {e['pair']!r}")

    adoptable = [e for e in entries
                 if e["identity"] is None and e["dir"] not in duplicated_dirs]
    polluted_unstamped = [e for e in entries
                          if e["identity"] is None and e["dir"] in duplicated_dirs]

    print()
    for e in entries:
        print(("ok        " if e["identity"] and pairs_equivalent(
                   e["identity"].get("pair"), e["pair"])
               else "DUP+unstp " if e in polluted_unstamped
               else "adoptable " if e in adoptable
               else "MISMATCH  ") + _fmt(e))

    # ── Adopt ────────────────────────────────────────────────────────────────
    if args.adopt and adoptable:
        print()
        for e in adoptable:
            dataset, graph = split_pair(e["pair"])
            try:
                stamp_dir(e["dir"], dataset, graph)
            except ArtifactIdentityError as exc:
                print(f"[adopt] SKIP {e['dir']}: {exc}")
                continue
            print(f"[adopt] stamped {e['dir']} as {e['pair']}")
    elif adoptable:
        print(f"\n[audit] {len(adoptable)} unstamped dir(s) are adoptable — "
              "rerun with --adopt to stamp them.")

    # ── Live tree vs sentinel ────────────────────────────────────────────────
    print()
    live_pair = current_pair(_REPO_ROOT)
    print(f"[live] .current_setup sentinel: {live_pair or '<absent>'}")
    for rel in TARGET_RELS:
        d = _REPO_ROOT / rel
        if not d.is_dir():
            continue
        try:
            ident = read_identity(d)
        except ArtifactIdentityError as exc:
            print(f"CRITICAL  live {rel}: corrupt carrier ({exc})")
            critical += 1
            continue
        if ident is None:
            print(f"[live] {rel}: UNSTAMPED — will be replaced on next swap_in "
                  "(hermetic); do not archive it as-is.")
        elif live_pair and not pairs_equivalent(ident.get("pair"), live_pair):
            critical += 1
            print(f"CRITICAL  live {rel}: stamped {ident.get('pair')!r} but "
                  f"sentinel says {live_pair!r} — re-run swap_in before eval.")
        else:
            print(f"[live] {rel}: ok (stamp={ident.get('pair')})")

    print(f"\n[audit] {'FAIL — ' + str(critical) + ' critical finding(s)' if critical else 'PASS'}")
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
