#!/usr/bin/env python3
"""Backfill run_config.llm in summary.json from the run dir's @<preset> tag.

Runs stamped before eval_run learned to resolve the generator preset recorded
config.py's static literals (gpt-4.1) even for @gpt-5.6-luna dirs. The dir tag
is the value the worker actually received, so it is the source of truth.
Dry-run by default; --apply rewrites. Idempotent.

    python scripts/backfill_summary_llm.py <runs_root> [<runs_root> ...] [--apply]
"""
import json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(REPO))
import config as _config          # noqa: E402
from eval_paths import split_method_seg as split_model  # noqa: E402

apply = "--apply" in sys.argv
roots = [Path(a) for a in sys.argv[1:] if a != "--apply"] or [REPO / "logs" / "runs"]
changed = same = skipped = 0
for root in roots:
    for s in sorted(root.rglob("summary.json")):
        method_seg = s.parent.name.split("__")[2] if s.parent.name.count("__") >= 2 else ""
        _, preset = split_model(method_seg)
        if not preset:
            skipped += 1; continue
        try:
            spec = _config.resolve_preset(preset)
        except KeyError:
            print(f"?? unknown preset {preset!r}: {s.parent.name}"); skipped += 1; continue
        params = spec.pop("params", None) or {}
        overlay = {**spec, **params}
        j = json.loads(s.read_text(encoding="utf-8"))
        rc = j.setdefault("run_config", {}); llm = rc.get("llm") or {}
        new = {"generator_llm": preset}
        for stage in ("NER", "CYPHER", "QA"):
            c = {**(getattr(_config, f"{stage}_LLM_CONFIG", None) or {}), **overlay}
            new[stage.lower()] = {k: c.get(k) for k in ("provider", "model") if k in c}
        if llm == new:
            same += 1; continue
        old_model = (llm.get("cypher") or {}).get("model")
        print(f"{'FIX ' if apply else 'would fix'} {s.parent.name[:70]:70s} cypher.model {old_model} -> {new['cypher']['model']}")
        if apply:
            rc["llm"] = new; s.write_text(json.dumps(j, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        changed += 1
print(f"\n{'applied' if apply else 'dry-run'}: {changed} to fix, {same} already correct, {skipped} untagged/unknown")
