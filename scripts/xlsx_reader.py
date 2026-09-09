#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xlsx_reader.py
==============
Read the first worksheet of an ``.xlsx`` file into rows of strings using only
the standard library.

Why this exists: annotators sometimes return the annotation sheet as an Excel
workbook rather than CSV, and this machine cannot install ``openpyxl`` (the
package proxy blocks wheel downloads). An ``.xlsx`` is a zip of XML, and the
subset an annotation sheet uses — shared strings, inline strings, numbers,
booleans — is small enough to parse directly.

Limitations (deliberate): formulas are read as their cached value; dates come
back as Excel serial numbers; only the first sheet is read. None of these occur
in an annotation return, whose cells are all short strings.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
_T = "{%s}t" % _NS["m"]
_CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _first_sheet_path(z: zipfile.ZipFile) -> str:
    """Resolve the workbook's first sheet through workbook.xml + its rels, so
    sheet order is what the user sees, not zip-entry order."""
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = wb.find("m:sheets", _NS)
        first = sheets.find("m:sheet", _NS)
        rid = first.get("{%s}id" % _NS["r"])
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.findall("pr:Relationship", _NS):
            if rel.get("Id") == rid:
                target = rel.get("Target").lstrip("/")
                return target if target.startswith("xl/") else "xl/" + target
    except (KeyError, AttributeError, ET.ParseError):
        pass
    cands = sorted(n for n in z.namelist()
                   if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    if not cands:
        raise ValueError("no worksheet found in workbook")
    return cands[0]


def _shared_strings(z: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(_T)) for si in root.findall("m:si", _NS)]


def _cell_value(c: ET.Element, shared: List[str]) -> str:
    t = c.get("t")
    v = c.find("m:v", _NS)
    if t == "s":
        return shared[int(v.text)] if v is not None and v.text else ""
    if t == "inlineStr":
        node = c.find("m:is", _NS)
        return "".join(x.text or "" for x in node.iter(_T)) if node is not None else ""
    if t == "b":
        return "TRUE" if v is not None and v.text == "1" else "FALSE"
    if v is None or v.text is None:
        return ""
    txt = v.text
    # Excel writes integers as "7" and floats as "7.5"; normalise "7.0" -> "7".
    if re.fullmatch(r"-?\d+\.0+", txt):
        txt = txt.split(".")[0]
    return txt


def read_xlsx(path: str) -> List[List[str]]:
    """Rows of the first worksheet as lists of strings, rectangular (short rows
    padded with ``""``). Empty trailing rows are dropped."""
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        root = ET.fromstring(z.read(_first_sheet_path(z)))
        data = root.find("m:sheetData", _NS)
        sparse: List[Dict[int, str]] = []
        for row in (data.findall("m:row", _NS) if data is not None else []):
            cells: Dict[int, str] = {}
            for i, c in enumerate(row.findall("m:c", _NS)):
                m = _CELL_RE.match(c.get("r") or "")
                idx = _col_index(m.group(1)) if m else i
                cells[idx] = _cell_value(c, shared)
            sparse.append(cells)
    width = max((max(c) + 1 for c in sparse if c), default=0)
    grid = []
    for cells in sparse:
        line = [""] * width
        for i, val in cells.items():
            line[i] = val
        grid.append(line)
    while grid and not any(x.strip() for x in grid[-1]):
        grid.pop()
    return grid


def read_xlsx_records(path: str) -> List[Dict[str, str]]:
    """First row as header → list of dicts (blank header cells are dropped)."""
    grid = read_xlsx(path)
    if not grid:
        return []
    header = [h.strip() for h in grid[0]]
    keep = [i for i, h in enumerate(header) if h]
    return [{header[i]: (row[i] if i < len(row) else "") for i in keep}
            for row in grid[1:] if any(x.strip() for x in row)]
