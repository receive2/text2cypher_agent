#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
identify_return.py — figure out which annotator a returned CSV belongs to,
and (with --file) copy it into verification/returns/<X>/ under its canonical
name. No more hand-renaming email attachments.

Identification order (first hit wins):
  1. an `annotator` column inside the file (v2.3+ calibration files);
  2. the row id-set matches one annotator's main queue exactly;
  3. a letter in the filename (annotator_A / _A.csv);
  4. a real name in the filename, looked up in the OPTIONAL local mapping
     verification/annotator_names.local.csv (two columns: letter,name).
     This file holds real names -> it must NEVER be committed or shipped.
Calibration files with none of the above report as UNIDENTIFIED (identify by
email sender), since every annotator's calibration content is identical.

Usage:
    python scripts/identify_return.py ~/Downloads            # scan a folder
    python scripts/identify_return.py ~/Downloads --file     # + file them
    python scripts/identify_return.py some.csv another.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(REPO, "verification")
SCHEMA_HEAD = {"id", "strategy", "original_entity", "perturbed_form", "validity"}
_ENC_WARN: dict = {}


ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _decode(raw):
    """Returned files come back in whatever Excel felt like using. Try UTF-8
    first, then the Windows/Mac single-byte fallbacks. Returns (text, encoding)."""
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8/replace"


def _read(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if str(path).lower().endswith((".xlsx", ".xlsm")):
        # Excel return: read the first sheet directly (stdlib), header row first.
        from xlsx_reader import read_xlsx_records
        return read_xlsx_records(path), raw, "xlsx"
    text, enc = _decode(raw)
    return list(csv.DictReader(io.StringIO(text))), raw, enc


def _load_context():
    queues = {}
    for x in "ABCDE":
        p = os.path.join(VDIR, f"verification_annotator_{x}.csv")
        if os.path.exists(p):
            queues[x] = {r["id"] for r, in zip(csv.DictReader(open(p, encoding="utf-8-sig")))} \
                if False else {r["id"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
    cal = set()
    p = os.path.join(VDIR, "calibration_50.csv")
    if os.path.exists(p):
        cal = {r["id"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
    names = {}
    p = os.path.join(VDIR, "annotator_names.local.csv")
    if os.path.exists(p):
        for r in csv.reader(open(p, encoding="utf-8-sig")):
            if len(r) >= 2 and r[0].strip().upper() in "ABCDE":
                names[r[1].strip().lower()] = r[0].strip().upper()
    return queues, cal, names


def identify(path, queues, cal, names):
    """-> (letter or None, kind, how)  kind: 'main'|'calibration'|'other'"""
    try:
        rows, raw, enc = _read(path)
    except Exception as e:
        return None, "unreadable", f"UNREADABLE ({e})"
    if not rows or not SCHEMA_HEAD.issubset(rows[0].keys()):
        return None, "other", "not an annotation CSV"
    if enc not in ("utf-8-sig", "xlsx"):
        _ENC_WARN[path] = enc
    ids = {r["id"] for r in rows}
    kind = "calibration" if ids == cal or len(rows) < 100 else "main"
    # 1. annotator column
    vals = {(r.get("annotator") or "").strip().upper() for r in rows}
    vals.discard("")
    if len(vals) == 1 and vals <= set("ABCDE"):
        return vals.pop(), kind, "annotator column"
    # 2. id-set match against queues
    for x, q in queues.items():
        if ids == q:
            return x, "main", "id-set match"
    # 3. letter in filename
    base = os.path.basename(path)
    m = re.search(r"annotator[_ -]?([A-Ea-e])\b", base) or re.search(r"[_ -]([A-E])\.csv$", base)
    if m:
        return m.group(1).upper(), kind, "letter in filename"
    # 4. real name in filename (local mapping only)
    low = base.lower()
    for name, x in names.items():
        if name and re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", low):
            return x, kind, "name in filename (local map)"
    return None, kind, "UNIDENTIFIED - check the email sender"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="CSV files and/or directories to scan")
    ap.add_argument("--file", action="store_true",
                    help="copy identified files into verification/returns/<X>/")
    args = ap.parse_args(argv)

    targets = []
    for p in args.paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            targets += sorted(os.path.join(p, f) for f in os.listdir(p)
                              if f.lower().endswith((".csv", ".xlsx")))
        else:
            targets.append(p)

    queues, cal, names = _load_context()
    seen_digests = {}
    for t in targets:
        letter, kind, how = identify(t, queues, cal, names)
        if kind == "other":
            continue
        if kind == "unreadable":
            print(f"  {os.path.basename(t):45s} -> !! {how}")
            continue
        digest = hashlib.sha256(open(t, "rb").read()).hexdigest()[:12]
        dup = seen_digests.get(digest)
        tag = f"annotator {letter}" if letter else "??"
        line = f"  {os.path.basename(t):45s} -> {tag:12s} [{kind}, {how}]"
        if dup:
            line += f"  DUPLICATE of {dup}"
        print(line)
        # an identified copy beats an unidentified twin seen earlier
        seen_digests.setdefault(digest, os.path.basename(t))
        if letter:
            seen_digests[digest] = os.path.basename(t)
        if args.file and letter and dup is None:
            canon = (f"2_calibration_50_{letter}.csv" if kind == "calibration"
                     else f"verification_annotator_{letter}.csv")
            dest_dir = os.path.join(VDIR, "returns", f"annotator_{letter}")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, canon)
            if os.path.exists(dest) and open(dest, "rb").read() != open(t, "rb").read():
                dest = os.path.join(dest_dir, "CONFLICT_" + os.path.basename(t))
                print(f"      !! different file already filed; saved as {os.path.basename(dest)}")
            if t.lower().endswith((".xlsx", ".xlsm")):
                # Downstream reads CSV: convert on filing, keep the workbook as evidence.
                rows, _, _ = _read(t)
                with open(dest, "w", encoding="utf-8-sig", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
                shutil.copy2(t, os.path.join(dest_dir, os.path.basename(t)))
                print(f"      converted xlsx -> {os.path.relpath(dest, REPO)} "
                      f"(original kept beside it)")
            else:
                shutil.copy2(t, dest)
                print(f"      filed -> {os.path.relpath(dest, REPO)}")
    if _ENC_WARN:
        print("\n  NOTE: not UTF-8 (decoded with a fallback; verify the text columns):")
        for p_, e_ in _ENC_WARN.items():
            print(f"    {os.path.basename(p_):45s} {e_}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
