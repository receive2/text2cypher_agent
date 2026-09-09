# LLM-proposer A/B — abstention-first prompting (2026-08-09)

**Question:** would regenerating the LLM-proposed tier with an abstention-first +
evidence-required prompt (and/or a stronger model) fix the ~50% invalid rate the
colleague pilot measured?

**Setup.** 50 items sampled from the pilot's decisive verdicts (30 human-invalid
/ 20 human-valid, stratified alias 36 / abbrev 9 / partial 5, seed 42). Each
entity re-prompted: *"propose a REAL, attested form or NONE; most obscure
entities have NONE; must be unambiguous; output JSON {form, evidence}"*.
Arms: **A = gpt-4.1** (current proposer, new prompt); **B = claude-opus-5**
(direct Anthropic SDK — the repo's langchain path injects `temperature`, which
Opus 5 rejects with a 400; a regen pipeline must strip it). Baseline = the
pilot itself (old prompt, gpt-4.1): ~51% invalid.

## Results

| | A (gpt-4.1 + new prompt) | B (opus-5 + new prompt) |
|---|---|---|
| human-INVALID (n=30): correctly abstained | 20 (67%) | 15 (50%) |
| — proposed a NEW form | 8 | 14 |
| — repeated the bad form | 2 | 1 |
| human-VALID (n=20): abstained (lost) | 11 (55%) | 11 (55%) |
| — kept/proposed a form | 9 | 9 |
| overall proposal rate | 38% | 48% |
| est. precision of proposals (hand-judged) | ~75–80% | **~85–88%** |

## Findings

1. **The abstention prompt works on both models**: proposal precision jumps from
   ~50% (pilot baseline) to ~75–88%. Fabricated nicknames ("Stormin' George"
   class) essentially disappear — both arms abstain on obscure people.
2. **Opus 5 does not merely abstain — it REPAIRS.** On human-invalid items it
   produced genuinely attested replacements: `Cordillera Principal` (the actual
   Spanish name), `NICOTINIC ACID → niacin`, `Peripheral artery occlusion →
   PAOD`, `Night's Watch → the Watch`, `Dorne → Principality of Dorne`,
   `AEGERION → Aegerion Pharmaceuticals`. Higher yield (48% vs 38%) at higher
   precision.
3. **It even corrected a human error**: pilot judged `Cai Yong → Cai Bojie`
   invalid; Bojie (伯喈) is Cai Yong's real courtesy name — Opus 5 re-proposed
   it. → calibration material for the formal round.
4. **The 55% "over-abstain" on human-valid items is inflated by lenient pilot
   labels**: many lost "valids" are themselves invented nicknames a lenient
   annotator kept (`Hank Clark`, `Andy Sommer`, `JP Martins`) — under the
   guideline's "unverifiable invented → drop" rule those labels are wrong, and
   abstaining on them is correct behavior.
5. Residual model errors exist but are rare (`Star Wars → ANH` — names a film,
   not the franchise) — the human census still catches these.

## Cost/yield projection (if the 814-slot LLM tier is regenerated with B)

- ~48% propose → ~390 proposals at ~85% valid → **~330 survive** census
  (status quo: annotate all 814 → ~410 survive at 51% precision).
- **Annotation cost −~50%** (390 vs 814 items to double-annotate); final N
  slightly lower (~330 vs ~410); declined slots fall back to algorithmic
  strategies (rows stay in the benchmark). Evidence strings attach to each
  proposal → faster per-item verification.

## Recommendation

Regenerate the LLM tier with **claude-opus-5 + abstention-first + evidence**,
via the direct Anthropic SDK (no `temperature`). Caveats to record in the
datasheet: (a) pin the proposer model id; (b) Claude models appear in the eval
matrix → keep the LLM-proposed vs attested provenance ablation and 100% human
census (the anti-circularity design already covers this); (c) langchain path
needs the temperature fix if reused.

Decision owner: user + advisor (scope/budget call). Raw run artifacts:
scratchpad `ab_test.py` / `armB_results.json` (session-local; per-call outputs
cached in `data_augmentation/llm` cache).
