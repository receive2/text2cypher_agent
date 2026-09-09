#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stdlib xlsx reader used for Excel annotation returns."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from xlsx_reader import read_xlsx, read_xlsx_records   # noqa: E402

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _make_xlsx(path: Path):
    """A minimal workbook: shared strings, an inline string, a number stored as
    007 -> 7 (Excel's coercion), a boolean, and a sparse row."""
    shared = ["id", "validity", "notes", "cypherbench:1", "valid", "Dòngtíng Hú ✓", "cypherbench:2"]
    sst = (f'<sst xmlns="{_NS}" count="{len(shared)}" uniqueCount="{len(shared)}">'
           + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
    sheet = (f'<worksheet xmlns="{_NS}"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2" t="s"><v>4</v></c><c r="C2" t="s"><v>5</v></c></row>'
             '<row r="3"><c r="A3" t="s"><v>6</v></c><c r="B3" t="inlineStr"><is><t>invalid</t></is></c>'
             '<c r="C3"><v>7</v></c></row>'
             '<row r="4"><c r="A4" t="b"><v>1</v></c></row>'
             '<row r="5"/>'
             "</sheetData></worksheet>")
    workbook = (f'<workbook xmlns="{_NS}" xmlns:r="{_RNS}"><sheets>'
                '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/sharedStrings.xml", sst)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def test_read_xlsx_grid(tmp_path):
    p = tmp_path / "r.xlsx"
    _make_xlsx(p)
    grid = read_xlsx(str(p))
    assert grid[0] == ["id", "validity", "notes"]
    assert grid[1] == ["cypherbench:1", "valid", "Dòngtíng Hú ✓"]     # shared strings, unicode intact
    assert grid[2] == ["cypherbench:2", "invalid", "7"]               # inline string + number
    assert grid[3] == ["TRUE", "", ""]                                # boolean, sparse row padded
    assert len(grid) == 4                                             # trailing empty row dropped


def test_read_xlsx_records_maps_header(tmp_path):
    p = tmp_path / "r.xlsx"
    _make_xlsx(p)
    recs = read_xlsx_records(str(p))
    assert recs[0] == {"id": "cypherbench:1", "validity": "valid", "notes": "Dòngtíng Hú ✓"}
    assert recs[1]["validity"] == "invalid"


def test_identify_return_reads_xlsx(tmp_path):
    import identify_return as ir
    p = tmp_path / "return.xlsx"
    _make_xlsx(p)
    rows, raw, enc = ir._read(str(p))
    assert enc == "xlsx" and rows[0]["id"] == "cypherbench:1"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
