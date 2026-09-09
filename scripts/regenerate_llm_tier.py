#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regenerate_llm_tier.py
======================
Regenerate the LLM-proposed perturbations (source == "llm": alias / abbrev /
partial) with an **abstention-first + evidence-required** prompt on
**claude-opus-5**, per the A/B result in ``audit/llm_proposer_ab_results.md``
(~50% -> ~85%+ proposal precision; the model repairs rather than fabricates).

Two phases (separate runs, so the expensive API pass is resumable):

  propose  (default)   Call the proposer once per LLM-tier row; append results
                       to ``audit/llm_regen_proposals.jsonl`` (resume-safe:
                       rows already present are skipped).
  --apply              Apply the proposals to test.json/test.probed.json:
                         * proposal passes guards + DB validity + splice ->
                           replace the edit (still ``needs_verification`` ->
                           Tier-1 census), record evidence + proposer model;
                         * abstained/failed -> fall back to ALGORITHMIC
                           strategies (partial -> typo -> casing; never
                           attested/LLM, so the census does not grow);
                         * nothing works -> drop the row (logged).

Direct Anthropic SDK — the langchain path injects ``temperature``, which
claude-opus-5 rejects (400). Guards per strategy: alias must be
replacement-style (must not contain the original), partial must reuse the
surface's own words and keep the distinctive token, all must pass the DB
collision/uniqueness checks. Backups: *.bak-llm-regen. Log: audit/llm_regen_log.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_REPO / ".env")

import eval_config as cfg  # noqa: E402
from data_augmentation import validity as V  # noqa: E402
from data_augmentation.augmenters import STRATEGY_REGISTRY, AugContext  # noqa: E402
from data_augmentation.augmenters.partial_name import (  # noqa: E402
    _TOKEN_RE, _clean, _distinctive_token, partial_eligible,
)
from data_augmentation.config import DEFAULT_SEED, SYNTHETIC_GRAPHS  # noqa: E402
from data_augmentation.pipeline import _replace_all, row_rng  # noqa: E402
from grounding_probe import _classify as probe_classify  # noqa: E402
from regenerate_partials import Providers  # noqa: E402

PROPOSER_MODEL = "claude-opus-5"
_DATASETS = {
    "cypherbench":  cfg.CYPHERBENCH_AUGMENTED_PATH,
    "mindthequery": cfg.MINDTHEQUERY_AUGMENTED_PATH,
    "zograscope":   cfg.ZOGRASCOPE_AUGMENTED_PATH,
}
PROPOSALS = _REPO / "audit" / "llm_regen_proposals.jsonl"
LOG = _REPO / "audit" / "llm_regen_log.csv"
_NL_KEYS = ("nl", "question", "nl_question")
_LLM_OFF = SimpleNamespace(enabled=False)

KIND = {
    "alias":  "a nickname or colloquial alternative name",
    "abbrev": "an abbreviation, acronym, or short form",
    "partial": "a natural shortened form (using only words from the name)",
}
SYSTEM = (
    "You help build a benchmark of realistic entity mentions. Given an entity "
    "from a knowledge graph, propose a REAL, attested alternative surface form "
    "that people actually use for EXACTLY this entity — or NONE.\n"
    "Rules:\n"
    "- Only output a form that is genuinely in real-world use (news, Wikipedia, "
    "common speech). Never invent, translate, or embellish.\n"
    "- Most obscure entities have no such form. For them, NONE is the correct "
    "answer. When unsure, answer NONE.\n"
    "- The form must be unambiguous: it must not equally refer to a different "
    "entity.\n"
    'Output strict JSON only: {"form": "..." or null, "evidence": "one short '
    'sentence naming where/how this form is attested"} — form must be null for NONE.'
)


def _canon(s: str) -> str:
    s = (s or "").strip().lower()
    return re.sub(r"^the\s+", "", s).strip(" '\"")


def _llm_rows():
    """Yield (row_id, dataset, row, edit) for every LLM-proposed edit."""
    for ds, path in _DATASETS.items():
        rows = json.load(open(path, encoding="utf-8"))
        for i, x in enumerate(rows):
            e = ((x.get("_aug_meta") or {}).get("edits") or [{}])[0]
            if e.get("source") == "llm":
                yield f"{ds}:{i}", ds, x, e


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — propose
# ──────────────────────────────────────────────────────────────────────────────

def propose(workers: int) -> int:
    import anthropic
    client = anthropic.Anthropic()
    done = set()
    if PROPOSALS.exists():
        for line in open(PROPOSALS, encoding="utf-8"):
            done.add(json.loads(line)["row_id"])
    todo = [(rid, ds, (x.get("_aug_meta") or {}).get("graph", ""), e)
            for rid, ds, x, e in _llm_rows() if rid not in done]
    print(f"LLM-tier rows: todo {len(todo)} (already proposed: {len(done)})")
    lock = threading.Lock()

    def one(item):
        rid, ds, graph, e = item
        prompt = (f"Entity: {e['from']}\nDomain: a '{graph}' knowledge graph\n"
                  f"Wanted: {KIND[e['strategy']]}\nJSON:")
        rec = {"row_id": rid, "dataset": ds, "graph": graph,
               "strategy": e["strategy"], "from": e["from"], "old_to": e["to"]}
        try:
            resp = client.messages.create(model=PROPOSER_MODEL, max_tokens=1200,
                                          system=SYSTEM,
                                          messages=[{"role": "user", "content": prompt}])
            if resp.stop_reason == "refusal":
                rec.update(status="error", form=None)
            else:
                out = "".join(b.text for b in resp.content if b.type == "text")
                m = re.search(r"\{.*\}", out, re.DOTALL)
                d = json.loads(m.group(0)) if m else {}
                form = d.get("form")
                if form is None or str(form).strip().lower() in ("", "none", "null"):
                    rec.update(status="abstain", form=None)
                else:
                    rec.update(status="proposed", form=str(form).strip(),
                               evidence=str(d.get("evidence") or "")[:300])
        except Exception as exc:  # noqa: BLE001
            rec.update(status="error", form=None, error=str(exc)[:120])
        with lock:
            with open(PROPOSALS, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec["status"]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        statuses = list(ex.map(one, todo))
    print("propose done:", dict(Counter(statuses)))
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — apply
# ──────────────────────────────────────────────────────────────────────────────

def _guards_ok(strategy: str, frm: str, form: str, label, prop, provider):
    """Strategy-specific shape guards + DB validity. Returns (ok, reason)."""
    if _canon(form) == _canon(frm) or not form.strip():
        return False, "no_change"
    if strategy == "alias":
        # replacement-style: must not contain the original verbatim
        if _canon(frm) and _canon(frm) in _canon(form):
            return False, "contains_original"
    if strategy == "partial":
        toks = _TOKEN_RE.findall(frm)
        if not partial_eligible(frm):
            return False, "not_partial_eligible"
        surf_words = {t.strip("()[]{}\"',;:").lower() for t in toks}
        if not all(w.strip("()[]{}\"',;:").lower() in surf_words for w in form.split()):
            return False, "not_subset_of_words"
        cleaned = _clean(form.split(), frm)
        if cleaned != form:
            return False, "output_guards"
        vals = provider.values(label, prop) if provider else None
        distinctive = _distinctive_token(toks, vals)
        if distinctive and distinctive.lower() not in form.lower():
            return False, "drops_distinctive_token"
    ok, reason = V.check_validity(strategy, form, frm, label, prop, provider)
    if not ok or reason == V.UNCHECKED:
        return False, reason
    return True, reason


def apply_() -> int:
    proposals = {}
    for line in open(PROPOSALS, encoding="utf-8"):
        r = json.loads(line)
        proposals[r["row_id"]] = r

    providers = Providers()
    log, actions = [], Counter()
    try:
        for ds, path in _DATASETS.items():
            p = Path(path)
            probed_p = p.with_name("test.probed.json")
            rows = json.load(open(p, encoding="utf-8"))
            probed = json.load(open(probed_p, encoding="utf-8"))
            keep, keep_pr = [], []
            for i, (x, xp) in enumerate(zip(rows, probed)):
                rid = f"{ds}:{i}"
                meta = x.get("_aug_meta") or {}
                e = (meta.get("edits") or [{}])[0]
                if e.get("source") != "llm":
                    keep.append(x); keep_pr.append(xp)
                    continue
                graph = meta.get("graph", "")
                frm, old_to = e.get("from", ""), e.get("to", "")
                label, prop = e.get("label"), e.get("prop")
                original_nl = meta.get("original_nl") or ""
                prop_rec = proposals.get(rid)
                if not (frm and original_nl and prop) or prop_rec is None \
                        or prop_rec.get("from") != frm:
                    actions["kept_no_meta"] += 1     # cannot re-check; already census-bound
                    keep.append(x); keep_pr.append(xp)
                    continue
                provider = providers.get(graph)

                new_edit = None   # (strategy, to, nl, validity, source, evidence)
                if prop_rec["status"] == "proposed":
                    form = prop_rec["form"]
                    ok, reason = _guards_ok(e["strategy"], frm, form, label, prop, provider)
                    if ok:
                        new_nl = _replace_all(original_nl, frm, form)
                        if new_nl is not None:
                            new_edit = (e["strategy"], form, new_nl, reason,
                                        "llm", prop_rec.get("evidence", ""))
                        else:
                            reason = "splice_failed"
                    if new_edit is None:
                        actions[f"proposal_rejected:{reason}"] += 1

                if new_edit is None:
                    # fallback to algorithmic strategies — census does not grow
                    rng = row_rng(DEFAULT_SEED, ds, x.get("id") or x.get("qid") or frm)
                    ctx = AugContext(nl=original_nl, rng=rng, llm=_LLM_OFF,
                                     label=label, prop=prop, entity_type="name",
                                     graph=graph,
                                     synthetic_domain=graph in SYNTHETIC_GRAPHS,
                                     values=provider, aliases=None)
                    for strat in ("partial", "typo", "casing"):
                        po = STRATEGY_REGISTRY[strat]().apply(frm, ctx)
                        if po is None or po.surface == frm or po.source == "llm":
                            continue
                        ok, reason = V.check_validity(strat, po.surface, frm,
                                                      label, prop, provider)
                        if not ok or reason == V.UNCHECKED:
                            continue
                        new_nl = _replace_all(original_nl, frm, po.surface)
                        if new_nl is None:
                            continue
                        new_edit = (strat, po.surface, new_nl, reason, "algorithmic", "")
                        break

                if new_edit is None:
                    actions["dropped"] += 1
                    log.append([ds, graph, rid, e["strategy"], frm, old_to,
                                "dropped", "", "", ""])
                    continue
                strat, new_to, new_nl, reason, source, evidence = new_edit
                act = ("llm_regen" if source == "llm"
                       else f"fallback_{strat}")
                actions[act] += 1
                log.append([ds, graph, rid, e["strategy"], frm, old_to,
                            act, new_to, source, reason])
                for obj in (x, xp):
                    m = obj.get("_aug_meta") or {}
                    ed = (m.get("edits") or [{}])[0]
                    ed.update({"strategy": strat, "to": new_to, "validity": reason,
                               "source": source,
                               "needs_verification": source == "llm",
                               "regenerated": "llm_tier_opus5_2026-08"})
                    if source == "llm":
                        ed["proposer_model"] = PROPOSER_MODEL
                        ed["evidence"] = evidence
                    else:
                        ed.pop("proposer_model", None)
                        ed.pop("evidence", None)
                    if "grounding_probe" in ed:
                        ed["grounding_probe"] = probe_classify(frm, new_to)
                    for k in _NL_KEYS:
                        if isinstance(obj.get(k), str) and obj[k] != original_nl:
                            obj[k] = new_nl
                keep.append(x); keep_pr.append(xp)

            print(f"{ds}: {len(rows)} -> {len(keep)}")
            for src, data in ((p, keep), (probed_p, keep_pr)):
                bak = src.with_suffix(src.suffix + ".bak-llm-regen")
                if not bak.exists():
                    shutil.copy2(src, bak)
                json.dump(data, open(src, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
    finally:
        providers.close()

    with open(LOG, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dataset", "graph", "row_id", "old_strategy", "from",
                    "old_to", "action", "new_to", "source", "validity"])
        w.writerows(log)
    print("\nactions:", dict(actions))
    print(f"log: {LOG}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    return apply_() if args.apply else propose(args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
