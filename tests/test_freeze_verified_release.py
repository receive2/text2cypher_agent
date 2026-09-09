#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The verified-release freeze must apply exactly the pre-registered rules and
produce a manifest that rebuilds to the files it wrote.

Decision logic is tested branch by branch; the end-to-end test builds a tiny
v2.1-shaped manifest + queue + two raters in a temp dir, runs the freeze, and
checks removals, a revert (question re-derived, difficulty class recomputed),
position renumbering, the decision log, and that rebuild_from_manifest
verifies the new manifest against the files on disk.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import freeze_verified_release as fz          # noqa: E402
import rebuild_from_manifest as rb            # noqa: E402


# ── decide() ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier,final,nat,prior,natpol,penpol,expect", [
    ("llm", "source_error", [], True, "drop-unnatural", "block", "remove:source_error"),
    ("algorithmic", "source_error", [], False, "drop-unnatural", "block", "remove:source_error"),
    ("llm", "invalid", [], True, "drop-unnatural", "block", "revert:prior_algorithmic"),
    ("attested", "invalid", [], True, "drop-unnatural", "block", "revert:prior_algorithmic"),
    ("llm", "invalid", [], False, "drop-unnatural", "block", "remove:invalid"),
    ("algorithmic", "invalid", [], True, "drop-unnatural", "block", "keep:invalid_rate_only"),
    ("llm", "pending", [], False, "drop-unnatural", "block", "pending"),
    ("llm", "pending", [], False, "drop-unnatural", "keep", "keep:pending"),
    ("llm", "pending", [], False, "drop-unnatural", "drop", "remove:pending"),
    ("llm", "valid", ["natural", "natural"], False, "drop-unnatural", "block", "keep:valid"),
    ("llm", "valid", ["natural", "unnatural"], False, "drop-unnatural", "block", "remove:unnatural"),
    ("llm", "valid", ["awkward"], False, "drop-unnatural", "block", "keep:valid"),
    ("llm", "valid", ["awkward"], False, "drop-both", "block", "remove:awkward"),
    ("llm", "valid", ["unnatural"], False, "keep", "block", "keep:valid"),
    ("algorithmic", "valid", ["unnatural"], False, "drop-unnatural", "block", "keep:naturalness_rate_only"),
])
def test_decide_follows_the_preregistered_rules(tier, final, nat, prior, natpol, penpol, expect):
    action, _ = fz.decide(tier, final, nat, prior, natpol, penpol)
    assert action == expect


def test_prior_form_never_used_for_algorithmic_tier():
    # An algorithmic-tier invalid keeps the row even if a prior form exists.
    assert fz.decide("algorithmic", "invalid", [], True, "drop-unnatural", "block")[0] == "keep:invalid_rate_only"


# ── end to end ────────────────────────────────────────────────────────────────

def _q(entity, form):
    return f"Which teams drafted players from {form}?"


def _manifest_rec(ds, pos, uuid, entity, form, strategy, source, graph="nba"):
    orig = _q(entity, entity)
    return {"dataset": ds, "position": pos, "graph": graph, "id": uuid,
            "gold_cypher": "MATCH (n) RETURN n", "_source_row": {"k": pos},
            "aug_meta": {"augmented": True, "original_nl": orig, "graph": graph,
                         "edits": [{"strategy": strategy, "from": entity, "to": form,
                                    "source": source, "needs_verification": source == "llm",
                                    "label": "Team", "prop": "name", "occurrences": 1,
                                    "validity": "ok"}],
                         "query_difficulty": "easy"},
            "probed_grounding": {"exact_ci": False, "damerau": 3, "substring": False, "class": "semantic"},
            "probed_extra_keys": {}}


def _write_csv(path, rows, cols):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def world(tmp_path):
    """Four v2.1 rows on one dataset:
       0 valid (kept)   1 invalid with certified prior (reverted)
       2 source_error (removed)   3 never sampled (kept)"""
    ds = "cypherbench"
    recs = [
        _manifest_rec(ds, 0, "u0", "Los Angeles Lakers", "LAL", "abbrev", "llm"),
        _manifest_rec(ds, 1, "u1", "Chicago Bulls", "Windy City Five", "alias", "llm"),
        _manifest_rec(ds, 2, "u2", "Boston Celtics", "BOS", "abbrev", "attested"),
        _manifest_rec(ds, 3, "u3", "Miami Heat", "miami heat", "casing", "algorithmic"),
    ]
    # v2.1 "released" files the manifest describes
    bench = tmp_path / "bench"
    rebuilt = rb.build_rows(recs)
    (bench / ds).mkdir(parents=True)
    json.dump(rebuilt[ds][0], open(bench / ds / "test.json", "w"), ensure_ascii=False)
    json.dump(rebuilt[ds][1], open(bench / ds / "test.probed.json", "w"), ensure_ascii=False)
    for other in ("mindthequery", "zograscope"):             # empty sibling datasets
        (bench / other).mkdir()
        json.dump([], open(bench / other / "test.json", "w"))
        json.dump([], open(bench / other / "test.probed.json", "w"))
    header = {"_manifest_header": True, "version": "v2.1-test", "row_count": 4,
              "released_hashes": {f"{d}/{n}": rb.canonical_hash(rebuilt[d][i] if d == ds else [])
                                  for d in ("cypherbench", "mindthequery", "zograscope")
                                  for i, n in ((0, "test.json"), (1, "test.probed.json"))}}
    man = tmp_path / "m21.jsonl"
    man.write_text("\n".join(json.dumps(x) for x in [header, *recs]) + "\n", encoding="utf-8")

    vdir = tmp_path / "verification"
    vdir.mkdir()
    keycols = ["id", "source_id", "dataset", "graph", "strategy", "provenance", "tier", "n_ann",
               "label", "prop", "original_entity", "perturbed_form", "augmented_question",
               "assigned_annotators"]
    key = [{"id": f"{ds}:{i}", "source_id": f"u{i}", "dataset": ds, "graph": "nba",
            "strategy": r["aug_meta"]["edits"][0]["strategy"],
            "provenance": r["aug_meta"]["edits"][0]["source"], "tier": "1-census", "n_ann": 2,
            "label": "Team", "prop": "name",
            "original_entity": r["aug_meta"]["edits"][0]["from"],
            "perturbed_form": r["aug_meta"]["edits"][0]["to"],
            "augmented_question": "", "assigned_annotators": "A;B"}
           for i, r in enumerate(recs[:3])]                  # row 3 is unsampled
    _write_csv(vdir / "verification_key.csv", key, keycols)
    anncols = ["id", "validity", "naturalness", "source_error", "corrected_form", "notes"]
    A = [{"id": f"{ds}:0", "validity": "valid", "naturalness": "natural", "source_error": "no"},
         {"id": f"{ds}:1", "validity": "invalid", "naturalness": "natural", "source_error": "no"},
         {"id": f"{ds}:2", "validity": "valid", "naturalness": "natural", "source_error": "yes"}]
    B = [{"id": f"{ds}:0", "validity": "valid", "naturalness": "natural", "source_error": "no"},
         {"id": f"{ds}:1", "validity": "invalid", "naturalness": "awkward", "source_error": "no"},
         {"id": f"{ds}:2", "validity": "valid", "naturalness": "natural", "source_error": "no"}]
    for name, rows in (("A", A), ("B", B)):
        d = vdir / "returns" / f"annotator_{name}"
        d.mkdir(parents=True)
        _write_csv(d / f"verification_annotator_{name}.REPAIRED.csv",
                   [{**{c: "" for c in anncols}, **r} for r in rows], anncols)
    pf = tmp_path / "prior_forms.csv"
    _write_csv(pf, [{"dataset": ds, "graph": "nba", "id": "u1", "strategy": "alias", "source": "llm",
                     "from": "Chicago Bulls", "current_to": "Windy City Five",
                     "revert_strategy": "partial", "revert_to": "Bulls", "revert_certified": "yes"}],
               ["dataset", "graph", "id", "strategy", "source", "from", "current_to",
                "revert_strategy", "revert_to", "revert_certified"])
    return {"tmp": tmp_path, "ds": ds, "manifest": man, "bench": bench, "vdir": vdir, "prior": pf}


def _argv(w, extra=()):
    return ["--key", str(w["vdir"] / "verification_key.csv"),
            "--annotations", str(w["vdir"] / "returns" / "annotator_*" / "*.REPAIRED.csv"),
            "--calibration",                                   # bare: no calibration exclusion
            "--prior-forms", str(w["prior"]),
            "--manifest-in", str(w["manifest"]),
            "--manifest-out", str(w["tmp"] / "m22.jsonl"),
            "--benchmarks-dir", str(w["bench"]),
            "--export-dir", str(w["tmp"] / "export"),
            "--version", "v2.2-test", *extra]


def test_end_to_end_freeze(world, monkeypatch, capsys):
    w = world
    monkeypatch.chdir(w["tmp"])
    rc = fz.main(_argv(w))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "REBUILD VERIFIED" in out

    # decisions
    dec = {r["id"]: r for r in csv.DictReader(open(w["tmp"] / "export" / "decisions.csv", encoding="utf-8-sig"))}
    assert dec["cypherbench:0"]["action"] == "keep:valid"
    assert dec["cypherbench:1"]["action"] == "revert:prior_algorithmic"
    assert dec["cypherbench:2"]["action"] == "remove:source_error"
    assert dec["cypherbench:3"]["action"] == "keep:unsampled"

    # released rows: 3 of 4, renumbered, the reverted one re-derived
    rows = json.load(open(w["bench"] / w["ds"] / "test.json", encoding="utf-8"))
    assert [r["id"] for r in rows] == ["u0", "u1", "u3"]
    reverted = rows[1]
    e = reverted["_aug_meta"]["edits"][0]
    assert e["strategy"] == "partial" and e["to"] == "Bulls" and e["source"] == "algorithmic"
    assert e["reverted_from"]["to"] == "Windy City Five" and e["reverted_from"]["source"] == "llm"
    assert reverted["nl"] == _q("Chicago Bulls", "Bulls")
    assert "Windy City Five" not in reverted["nl"]
    probed = json.load(open(w["bench"] / w["ds"] / "test.probed.json", encoding="utf-8"))
    assert probed[1]["_aug_meta"]["edits"][0]["grounding_probe"]["class"] == "substring"

    # manifest: positions renumbered, provenance retained, verifies independently
    h, recs = rb.load_manifest(w["tmp"] / "m22.jsonl")
    assert h["version"] == "v2.2-test" and h["row_count"] == 3
    assert [r["position"] for r in recs] == [0, 1, 2]
    assert [r["v21_position"] for r in recs] == [0, 1, 3]
    assert recs[1]["verification"]["action"] == "revert:prior_algorithmic"
    assert recs[1]["verification"]["raters"]["A"]["validity"] == "invalid"
    datasets = {d: str(w["bench"] / d / "test.json") for d in ("cypherbench", "mindthequery", "zograscope")}
    assert rb.verify(h, rb.build_rows(recs), datasets=datasets)
    assert dec["cypherbench:3"]["v22_position"] == "2"


def test_pending_blocks_the_freeze(world, monkeypatch, capsys):
    w = world
    # make raters disagree on row 0
    p = w["vdir"] / "returns" / "annotator_B" / "verification_annotator_B.REPAIRED.csv"
    txt = p.read_text(encoding="utf-8-sig").replace("cypherbench:0,valid", "cypherbench:0,invalid", 1)
    p.write_text(txt, encoding="utf-8-sig")
    monkeypatch.chdir(w["tmp"])
    rc = fz.main(_argv(w))
    out = capsys.readouterr().out
    assert rc == 4 and "await adjudication" in out
    assert not (w["tmp"] / "m22.jsonl").exists()
    # provisional build with the conservative bound drops it
    rc = fz.main(_argv(w, ["--pending", "drop"]))
    assert rc == 0
    rows = json.load(open(w["bench"] / w["ds"] / "test.json", encoding="utf-8"))
    assert [r["id"] for r in rows] == ["u1", "u3"]


def test_dry_run_writes_nothing_but_the_plan(world, monkeypatch):
    w = world
    monkeypatch.chdir(w["tmp"])
    before = (w["bench"] / w["ds"] / "test.json").read_bytes()
    assert fz.main(_argv(w, ["--dry-run"])) == 0
    assert (w["bench"] / w["ds"] / "test.json").read_bytes() == before
    assert not (w["tmp"] / "m22.jsonl").exists()
    assert (w["tmp"] / "export" / "decisions.preview.csv").exists()


def test_calibration_key_invalid_is_removed(world, monkeypatch):
    w = world
    _write_csv(w["vdir"] / "calibration_50.csv", [{"id": "cypherbench:0"}], ["id"])
    _write_csv(w["vdir"] / "calibration_key.csv",
               [{"id": "cypherbench:0", "ref_validity": "invalid"}], ["id", "ref_validity"])
    monkeypatch.chdir(w["tmp"])
    argv = _argv(w)
    argv.remove("--calibration")                                   # let auto-detect find the file
    assert fz.main(argv) == 0
    dec = {r["id"]: r for r in csv.DictReader(open(w["tmp"] / "export" / "decisions.csv", encoding="utf-8-sig"))}
    assert dec["cypherbench:0"]["action"] == "remove:calibration_key_invalid"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
