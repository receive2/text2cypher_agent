# NER Improvement Proposal — fixing `full` < `node_only`

**Context.** On the perturbed CypherBench benchmark, enabling relation tools
(`full`) *underperforms* node-only NER on geography (EA 0.158 vs 0.199) and
politics (0.134 vs 0.193); see `docs/NER_ABLATION_REPORT.md`. This document
proposes fixes. **No code changed yet — this is a design doc for sign-off.**

## Root cause (one sentence)

Relation tools occupy slots in the fixed FAISS **top-K (=15)** tool selection,
crowding out the node-name tool the agent needs, so the perturbed entity surface
form is never canonicalized — confirmed by 93% (geography) / 81% (politics) of
regressions emitting a non-canonical string literal that node_only got right.

The NER system prompt is **identical** across modes (only the runtime
`{tool_list}` = selected tools differs), so this is a **tool-availability**
problem, not a prompt-quality problem.

## Options

### Option A — separate retrieval budgets (node always full-K, relation additive)
Retrieve top-K over the **node index** (exactly what node_only does) **and**
top-K relation tools, then union.

- **Fixes:** retrieval dilution. node_only behavior becomes a guaranteed floor;
  relation tools are pure addition.
- **Does not fix:** residual *agent-level* confusion (with both tool classes in
  context, the ReAct agent can still mis-pick) — but this is the smaller effect.
- **Cost:** ~1× NER (one agent call). **Effort:** small — reuse the two existing
  indexes (`tools_auto_node_only` = node half; filter `tools_auto` to relations).
- **Optional adaptive:** only add a relation tool if its FAISS score ≥ τ, so
  relation-irrelevant questions get no relation tools (soft, threshold-based).

### Option B — two-stage NER (node-then-relation), relation stage conditional
Run node-NER (node tools only) → then relation-NER (relation tools only) →
merge entity dicts. Entity keys are disjoint (`Label.prop` vs `RelType.prop`),
so the merge is clean.

- **Fixes:** BOTH retrieval dilution AND agent-level confusion (each stage sees
  only its tool class). node_only is the exact stage-1 floor.
- **Synergy:** stage-1's resolved node labels can scope stage-2's
  `filter_connectivity`, sharpening relation selection.
- **Cost:** up to ~2× NER (two agent loops) — **must make stage 2 conditional**
  (skip when no relation tool clears a relevance threshold, or when the graph
  has no groundable relation properties) or you pay 2× on graphs where relations
  carry no values. **Effort:** medium — orchestration + a relation-only retrieval.
- Highest quality of the options.

### Option C — schema-aware relation-tool pruning (generation-time)
Don't generate/index relation tools for relations whose properties are not
groundable strings (e.g. structural `flowsThrough`, `locatedIn`). geography's 12
relation tools and politics' 15 all fall in this bucket.

- **Fixes:** the noise at the source; geography/politics `full` collapses to
  `node_only` automatically, while movie (groundable `winners`,
  `character_role`) keeps its useful relation tools.
- **Cost:** 1× NER. **Effort:** small-medium, in the tool-generation step.
- **Coarse:** per-graph/per-relation, not per-question.

### Option D — raise top-K (quick hypothesis check only)
15 → 30. Lets node + relation tools both fit.

- **Use:** cheapest way to *confirm* the dilution diagnosis (full should rebound
  to ≥ node_only). **Not a production fix** — adds agent latency/cost/confusion.

## Recommendation

- **Best single combined fix:** **Option C + Option B**. C removes the
  zero-value structural relation tools (so geography/politics never pay), and B's
  stage 2 then triggers only where relation tools survive pruning (movie) — C
  effectively becomes B's "stage-2 on/off switch." Highest quality, no wasted 2×.
- **Cheapest 80%-of-the-gain:** **Option A** (separate budgets) or **C alone**.
- The ~10–20% of regressions that are *same-literal* (edge-direction errors,
  e.g. gold `(Politician)<-[:headedBy]-(Party)` vs predicted reverse) are a
  Cypher-generation issue, fixable independently via TEXT2CYPHER_SP few-shots —
  unrelated to NER mode.

## Validation plan (for whichever option)

Re-run **geography `full`** (new logic), expect EA to rebound from 0.158 to
≥ 0.199 (the node_only floor), **and** confirm **movie `full` PSJS** stays
≈ 0.468 (relation grounding preserved). One run confirms both "floor held" and
"relation upside kept."
