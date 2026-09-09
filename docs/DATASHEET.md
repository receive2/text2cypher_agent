# Datasheet — Entity-Perturbed text2cypher Benchmark

A robustness benchmark for natural-language→Cypher question answering. Built by
perturbing the **entity mention** in each question of three existing
text2cypher datasets, while leaving the gold Cypher (and thus the answer)
unchanged. Status: **v2 staging** (pre-human-verification; see §7).

## 1. Motivation

Existing text2cypher benchmarks are unrealistically clean: the entity a user
mentions almost always matches a graph value verbatim, so a system can succeed
by exact string matching and reported accuracy overstates real-world
robustness. Real users abbreviate, nickname, shorten, and mistype entities.
This benchmark restores that realism by rewriting the entity mention into a
plausible variant, creating a **grounding gap** that a value-grounding step
must close.

<!-- AUTOGEN:HEADLINE -->
**Headline:** across 4,641 perturbed examples, a baseline case-insensitive exact-match no longer recovers the canonical entity on **90.0%** of them (90.9 / 89.6 / 88.9% on the three datasets independently).
<!-- /AUTOGEN:HEADLINE -->

## 2. Composition

<!-- AUTOGEN:COMPOSITION -->
3 datasets, 13 graphs, **4,641** perturbed examples (test split, post-curation; see §7 curation log).

| dataset | graphs | examples |
|---|---|--:|
| CypherBench | company, fictional_character, flight_accident, geography, movie, nba, politics | 2,115 |
| Mind-the-Query | bloom, covid, er, healthcare, wwc | 1,227 |
| ZOGRASCOPE | pole | 1,299 |
<!-- /AUTOGEN:COMPOSITION -->

Each example preserves the original row (`_source_row`), the unchanged
`gold_cypher`, the perturbed question (`nl`), and `_aug_meta` recording the
single edit: `strategy`, `from` (canonical DB value), `to` (perturbed surface),
`source` (provenance), `needs_verification`, `(label, prop)`, and the
`grounding_probe` difficulty signals.

## 3. Perturbation taxonomy

One edit per example. Five strategies, each a distinct grounding challenge:

| strategy | what it does | example | target share |
|---|---|---|--:|
| `casing` | re-case (lower/UPPER) — difficulty floor / control | `Sacramento Kings`→`SACRAMENTO KINGS` | 10% |
| `typo` | one keyboard-slip / transposition / deletion / doubling | `Barletta`→`Balretta` | 22.5% |
| `partial` | drop words, keep the distinctive head | `Los Angeles Lakers`→`Lakers` | 22.5% |
| `abbrev` | acronym / short form | `Golden State Warriors`→`GSW` | 22.5% |
| `alias` | replacement nickname / brand–generic (no surface overlap) | `Tocilizumab`→`Actemra` | 22.5% |

(`paraphrase` was excluded by design — it leaves the entity verbatim and so
poses no value-grounding challenge.)

## 4. Difficulty spectrum (objective, model-independent)

Each edit is classified by how the perturbed surface relates to the canonical
value (DB- and model-free):

<!-- AUTOGEN:DIFFICULTY -->
| class | meaning | all | cypherbench | mtq | zograscope |
|---|---|--:|--:|--:|--:|
| `exact_ci` | case-insensitive exact still matches (trivial) | 10.0% | 9.1% | 10.4% | 11.1% |
| `edit_distance` | within Damerau ≤2 (fuzzy-recoverable) | 32.1% | 15.0% | 31.5% | 60.6% |
| `substring` | perturbed ⊆ canonical (fulltext-recoverable) | 25.6% | 29.8% | 23.2% | 21.0% |
| `semantic` | no surface overlap (needs world knowledge / vector) | 32.2% | 46.1% | 34.8% | 7.3% |
<!-- /AUTOGEN:DIFFICULTY -->

`semantic` is the hardest tier and is where value-grounding / vector retrieval
is required; its share tracks alias/abbrev availability per domain.

## 5. Generation method

1. **Entity extraction** — the entity is the gold-Cypher string literal that
   appears in the question; the `(label, property)` it is compared against is
   parsed from the Cypher so checks can be scoped. Dates, times, emails, and
   structured IDs/postcodes are excluded (low grounding value, collision-dense).
2. **Strategy selection** — a deficit-greedy quota sampler targets the shares
   in §3; `casing` is capped at its target so the trivial control never
   inflates. A row is dropped (with reason) if no eligible strategy yields a
   valid edit — never silently substituted.
3. **Surface generation** — `casing`/`typo`/`partial` are algorithmic;
   `abbrev`/`alias` prefer **attested sources** (CypherBench's shipped
   Wikidata aliases; curated tables; RxNorm for drugs) and fall back to an
   **LLM proposer** (gpt-4.1) only when attested misses. LLMs *propose*; they
   never *judge* validity.
4. **Validity gates (DB-grounded, model-free)** — every edit must (a) not
   collide with a *different* value of the same `(label, prop)`, (b) for
   `partial`, resolve uniquely by containment, (c) for `typo`, leave the
   canonical the unique value within Damerau-1 (margin). A splice grammar guard
   repairs article/word-doubling at the insertion seam.
5. **Synthetic-domain rule** — fabricated graphs (`pole`, `bloom`, `er`) have
   no real-world aliases, so the `alias` strategy is disabled there (preventing
   hallucinated aliases for fabricated entities).
6. **Reproducibility** — per-row RNG seeded from `(seed, dataset, row_id)`;
   generation only reads the graph DB. Proposer model: `gpt-4.1`
   (pin the exact snapshot used).

## 6. Realized distribution (per graph)

<!-- AUTOGEN:REALIZED -->
Post-curation realized mix (regenerate with `scripts/render_datasheet_tables.py`; canonical figures are post-adjudication). `census` = LLM- + attested-provenance edits (all human-verified, Tier 1).

| dataset | graph | n | casing | typo | partial | abbrev | alias | census |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| cypherbench | company | 306 | 10.1 | 14.1 | 20.6 | 26.5 | 28.8 | 171 |
| cypherbench | fictional_character | 326 | 10.7 | 23.0 | 26.1 | 9.2 | 31.0 | 152 |
| cypherbench | flight_accident | 169 | 8.9 | 5.3 | 10.7 | 53.8 | 21.3 | 129 |
| cypherbench | geography | 335 | 10.7 | 14.3 | 16.1 | 23.6 | 35.2 | 199 |
| cypherbench | movie | 367 | 8.7 | 16.3 | 19.1 | 28.6 | 27.2 | 212 |
| cypherbench | nba | 251 | 10.0 | 2.8 | 23.5 | 25.9 | 37.8 | 173 |
| cypherbench | politics | 361 | 5.0 | 5.8 | 13.6 | 47.9 | 27.7 | 273 |
| mindthequery | bloom *(synthetic)* | 24 | 16.7 | 16.7 | 45.8 | 20.8 | 0.0 | 5 |
| mindthequery | covid | 327 | 10.7 | 54.4 | 11.0 | 8.9 | 15.0 | 78 |
| mindthequery | er *(synthetic)* | 186 | 9.1 | 32.3 | 14.0 | 44.6 | 0.0 | 83 |
| mindthequery | healthcare | 420 | 10.5 | 18.8 | 10.2 | 30.7 | 29.8 | 256 |
| mindthequery | wwc | 270 | 10.4 | 22.6 | 30.4 | 21.5 | 15.2 | 99 |
| zograscope | pole *(synthetic)* | 1299 | 11.1 | 59.8 | 18.5 | 10.6 | 0.0 | 138 |
| **ALL** | | 4641 | **10.0** | **30.6** | **18.0** | **23.0** | **18.4** | 1968 |

Within the alias-applicable stratum (67.5% of rows; synthetic graphs are alias-zero by design) alias = **27.2%**. Deviations from the §3 targets are supply ceilings, measured in `audit/APPLICABILITY_CEILING.md`; headline metrics macro-average over strategies.
<!-- /AUTOGEN:REALIZED -->

**Honest accounting.** `casing` is pinned at 10% everywhere. Where entities have
abbreviations/aliases (all CypherBench except fictional_character; healthcare),
the four informative strategies reach ~22.5% each. Where they do not
(fictional_character, covid, wwc, and synthetic graphs where `alias` is off),
the realized mix is `typo`/`partial`-heavy by supply, not by design — we report
the per-graph mix rather than forcing abbreviations/aliases that do not exist.

## 7. Quality control & known limitations

- **Human verification.** All **916 LLM-proposed edits (100%)** undergo a full double-annotated census — the tier that underpins the anti-circularity claim, and the only tier where verification *removes* items. The lower-risk tiers are *measured* by stratified sample rather than exhaustively cleaned: **400 of 1,052** attested/KB edits (double-annotated) and **450 of 2,673** algorithmic edits, each reported as a validity rate with a Wilson 95% CI; un-sampled rows of those two tiers remain in the release. Total queue 1,766 items / 3,322 judgments across 5 annotators. Queues are built blind by `scripts/verification_sample.py` (annotator instructions: `docs/ANNOTATION_QUICKSTART.md`; internal guideline: `docs/ANNOTATION_SHEET.md`; methodology: `docs/VERIFICATION_PROTOCOL.md`). Adjudication rules are pre-registered (§7 curation log, 2026-08-22); calibration items are excluded from all reported measurements. **Canonical figures are post-adjudication; this v2.1 freeze is pre-verification.**

<!-- AUTOGEN:VERIFICATION -->
_Verification results not yet frozen — run `scripts/freeze_verified_release.py` after adjudication._
<!-- /AUTOGEN:VERIFICATION -->
- **Residual LLM noise** caught by verification: standings-code abbreviations
  (`the CHI`) and invented nicknames for obscure entities. Closed-set categories
  (≤30 distinct values: divisions, conferences, positions, awards) are excluded
  from LLM aliasing to prevent sibling-swaps.
- **Layout.** v2 is a consolidated `test.json`; converting to each source's
  eval layout (Mind-the-Query per-graph files; ZOGRASCOPE CSV) is pending before
  harness consumption (`_source_row` preserved, so conversion is lossless).
- **Difficulty ranks.** `fulltext_rank`/`vector_rank` are not computed (the
  benchmark graphs ship without those indexes); the §4 class spectrum is
  index-free.

### Curation log

- **2026-08-09 — unchecked-edit backfill & entity-pool leak removal.** 356 edits
  had shipped with `validity="unchecked"` (generation-time (label, prop)
  resolution failed, so the DB checks never ran — and, same root cause, the
  entity-pool type filter never ran either). A post-hoc backfill
  (`scripts/backfill_unchecked_validity.py`) re-resolved each canonical value
  across all node/relationship scalar and array string properties on the live
  graphs and re-ran the §5 validity checks. Outcome: **147 confirmed valid**
  (110 passed all checks, 37 casing — `validity` flipped to `ok` with
  `validity_backfill` provenance); **186 rows removed** — their "entities" were
  out-of-scope pool leaks, not stored DB values (structured-ID/descriptor
  phrases 136, schema words & common nouns 32, dates/datetimes 10,
  CONTAINS-fragments 8); **23 held** for hand-check (suspected format/unicode
  drift). Every check that could be resolved passed (0 hard failures).
- **2026-08-09 — E-class hand-check (DB-assisted).** Each of the 23 held items
  was adjudicated against the live graph and the row's gold Cypher. **4 kept**
  (typo/alias with a uniquely recoverable referent, DB-verified — e.g.
  `National Assembly of Armenia → Armenian Parliament`); **19 removed**:
  6 rows whose gold contains **no string literal** (the perturbation targeted a
  non-value word — seeding-invariant violation), 4 **quoted-spec corruptions**
  (the question quotes a literal, so aliasing/typoing it changes the query spec
  — e.g. `STARTS WITH 'Muller'` vs question saying `'Miller'`), 3 referent
  breaks, 2 DB-verified ambiguities (e.g. `TEVA` collides with a distinct
  company named `Teva`), 2 not-unique partials (63 awards contain
  `documentary`), 2 excluded-class postcode areas, 1 value lost entirely.
  Dataset size 4,875 → **4,670**; zero `unchecked` edits remain.
  Row-level log: `audit/unchecked_curation_log.csv` (verdicts + reasons also in
  `audit/unchecked_E_handcheck.csv`); method: `audit/unchecked_backfill_summary.md`.
- **2026-08-09 — partial-rule patch (v2.1) + regeneration of algorithmic
  partials.** A heuristic sweep had flagged 263/1,069 algorithmic partials with
  systematic defects (bare-number outputs like `Sweden 1995 → "1995"`, generic
  single words, dangling punctuation `→ "Event)"`, status-sentence sources).
  Root cause: the implementation lacked the designed distinctive-token logic and
  ranked maximal reductions first. `augmenters/partial_name.py` was patched
  (status/sentence-shape eligibility guard; edge-punctuation tokenization;
  bare-number/too-short/unbalanced output guards; **DB-grounded
  distinctive-token requirement** — every reduction must retain the token with
  the lowest document frequency across that (label, prop)'s values, and a
  single-token reduction may BE that token when capitalized). All algorithmic
  partials were then re-validated against the live graphs
  (`scripts/regenerate_partials.py`): **536 already compliant (kept), 264
  regenerated as better partials** (e.g. `"Event)" → "Important Medical Event"`,
  `"1363" → "Ontario Flight 1363"`), **121 fell back to algorithmic typo**
  (status values, year-only tournaments — no natural partial exists), **6
  removed** (bad outputs with no (label,prop) metadata to re-check), 33
  backfill-verified rows left as-is. Human-verification census unaffected
  (algorithmic edits are Tier-2-sampled, not censused). Defect-flag rate after:
  ~1% (from 24.6%). Dataset size → **4,664**. Log:
  `audit/partial_regen_log.csv`; existing unit tests (50) pass unchanged.
- **2026-08-09 — LLM-tier regeneration (abstention-first, claude-opus-5).** A
  pilot annotation of the LLM-proposed tier measured ~51% invalid proposals
  (fabricated nicknames for entities that have none). A 50-item A/B
  (`audit/llm_proposer_ab_results.md`) showed an **abstention-first +
  evidence-required** prompt raises proposal precision to ~85%+ on
  claude-opus-5, which also *repairs* invalid items with genuinely attested
  forms. All 792 LLM-proposed edits were re-proposed
  (`scripts/regenerate_llm_tier.py`; proposer model pinned: `claude-opus-5`,
  direct SDK): **527 proposed / 265 abstained**; after shape guards
  (replacement-style alias, partial word-subset + distinctive token) and DB
  validity (10 collisions and 20 contains-original caught), **455 accepted**
  — each carrying an `evidence` string and `proposer_model` in `_aug_meta`,
  all still routed to the human census (`needs_verification`); **293 fell back
  to algorithmic strategies** (typo 190 / partial 98 / casing 5 — DB-gated,
  Tier-2-sampled); **16 rows removed** (no valid perturbation); 28 kept as-is
  (no (label,prop) metadata to re-check). Dataset size 4,664 → **4,648**;
  LLM-tier census shrinks 792 → 483. Anti-circularity note: Claude models
  appear in the evaluation matrix; the proposer only *proposes* — every
  LLM-proposed form remains 100% human-verified, and the LLM-proposed vs
  attested provenance split supports the ablation. Log:
  `audit/llm_regen_log.csv`; raw proposals: `audit/llm_regen_proposals.jsonl`.

- **2026-08-22 — mid-word replacement repair.** The consistent-replacement
  step matched surface strings without word boundaries, so a short value could
  be replaced *inside another word* (`us` -> "United States" also rewrote
  "users" into "United Statesers"). `pipeline._occurrences` is now
  word-boundary-aware (a trailing plural `s` still counts as the same mention:
  "shooting guards" -> "SGs"). All 4,648 question texts were recomputed from
  `original_nl`: **4,594 unchanged, 47 repaired, 7 removed** (the surface only
  ever occurred mid-word, so the question cannot carry the perturbation).
  Dataset size -> **4,641**. Log: `audit/midword_fix_log.csv`; unit tests (50)
  pass.

- **2026-08-22 — applicability-ceiling measurement + lossless mixture
  rebalance.** External review flagged the typo share (44.3% vs the 22.5%
  target). We measured the **applicability ceiling** per (graph, strategy)
  (`audit/APPLICABILITY_CEILING.md`; `scripts/measure_applicability_ceiling.py`):
  exact attested-KB scan over all rows + a claude-opus-5 abstention probe
  (~1,000 entities), all candidates passed through shape rules and the live-DB
  collision gate. Finding: large **unused attested supply** (e.g. nba alias
  ceiling 79.7% vs 20.3% realized) alongside true structural zeros (synthetic
  graphs have no aliases by design). `scripts/rebalance_mixture.py` then
  performed **scarcity-first lossless reallocation** (abbrev before alias;
  donors typo -> casing -> partial with 10%/18% floors; every conversion
  re-passed shape + DB validity + splice): **725 rows converted** (typo 541,
  partial 157, casing 27; 327 to attested forms, 398 to LLM-proposed forms
  with evidence, all census-bound). Mixture: typo 44.3->32.7%, abbrev
  12.8->21.9%, alias 10.9->17.4%, partial 18.0%, casing 10.0%. Alias remains
  below target because verified supply is exhausted (synthetic graphs = 32.5%
  of rows have zero alias ceiling) — the ceiling table is reported as a
  finding, and headline metrics use macro-averaging over strategies. No rows
  deleted. Log: `audit/rebalance_log.csv`.

- **2026-08-22 — partial backfill to supply exhaustion + PRE-REGISTERED
  adjudication rules (generation-side freeze).** Final mixture lever per
  external review: every typo row whose entity admits a fully-gated partial
  form was converted (`scripts/backfill_partial_from_typo.py`; diagnostic found
  **95 rows**, below the 208 needed for target — all 95 converted, algorithmic
  provenance, zero census growth). **Generation-side frozen mixture: typo
  30.6% / abbrev 21.9% / partial 20.1% / alias 17.4% / casing 10.0%.** Every
  deviation now has a stated mechanism: abbrev at target; partial and alias
  filled to measured supply exhaustion (`audit/APPLICABILITY_CEILING.md`);
  within the alias-applicable stratum (67.5% of rows; synthetic graphs are
  alias-zero by design) alias = **25.8%**, above the 22.5% design share — the
  global 17.4% is a composition effect, not supply shortfall. Headline metrics
  use macro-averaging over strategies.
  **Pre-registered adjudication rules** (canonical figures are
  POST-adjudication; these rules are fixed before annotation begins):
  (1) a census-rejected edit (`invalid`) on a row with a prior
  **algorithmic, machine-gated** form **reverts to that form** (provenance
  updated); revert targets are enumerated per row in `audit/prior_forms.csv`,
  rebuilt deterministically from the backup snapshot chain (this supersedes
  the partially-overwritten per-wave logs). Reverting to prior LLM- or
  KB-sourced forms is prohibited (they were never human-verified);
  `source_error` rows are always removed;
  **(1b, decision confirmed 2026-08-23)** rejected rows *without* a certified
  prior form are **removed** (no substitution — deletion preserves the mixture
  and difficulty shares better than any fill-in, and casing back-fill is
  explicitly prohibited per the §5 design rule). Expected loss ≈100–150 rows.
  **Contingency (pre-registered):** if the invalid rate among no-prior census
  rows exceeds **20%** (>2× expectation, indicating a systematic issue), the
  fallback switches to machine-generated algorithmic perturbations (full
  current gates), each single-verified during adjudication before retention; (2) rows without a prior valid form follow protocol §6
  (corrected_form supplied → fix + second-pass re-verify; otherwise drop and
  log); (3) per-strategy proposal acceptance rates and IAA are auto-reported
  post-adjudication as the generation-validation table; (4) all mixture/count
  tables are regenerated from the data by script after adjudication — no
  hand-edited numbers.

- **2026-08-22 — alias census probe, freeze decision, and reproducibility
  manifest (FINAL generation-side state).** The 50-entity spot-check of the
  no-alias claim (external review item #3) surfaced that the LLM probe had been
  stratified-sampled, not exhaustive: 253 entities on alias-applicable rows had
  never been probed. A census probe closed the gap (78/253 proposed, 31%);
  coverage is now exhaustive (verified: zero unprobed alias-applicable rows;
  1,278 successful probe calls total). The spot-check also confirmed three
  DB-collision rejections were CORRECT (Coreg/Micardis/Hidden exist as other
  values). One operational error is disclosed: an intermediate reallocation ran
  against a stale strategy snapshot, causing redundant (but fully gated)
  conversions before being corrected against current data. Post-census
  reallocation converted 81 further rows. **Frozen mixture: typo 30.6 / abbrev
  23.0 / alias 18.4 / partial 18.0 / casing 10.0** (alias = 27.2% within its
  applicable stratum). Decision (documented): stop here — the combined
  attested+LLM supply for abbrev+alias is 41.3% of rows vs a 45% combined
  target; the residual gap is a measured supply ceiling, not an allocation
  choice. The abbrev ceiling is a lower bound (rows holding attested-alias
  forms were never abbrev-probed; immaterial as abbrev exceeds target).
  **Reproducibility:** the release is frozen as a decision manifest
  (`release_manifest_v2.1.jsonl`: per-row source row, unperturbed question,
  gold, and the full edit decision incl. LLM proposals + evidence).
  `scripts/rebuild_from_manifest.py` re-derives every perturbed question from
  the frozen decisions and verifies canonical-hash equality with the released
  files (verified: 6/6 files match). The manifest supersedes the per-wave
  curation logs as the complete row-level provenance record.

- **2026-09-09 — human verification collected (5/5 annotators); freeze
  pending adjudication.** 3,322 judgments over 1,766 queue items; 1,739
  measured after the pre-registered calibration exclusion. Validity: LLM
  99.2% [98.3, 99.6], attested 99.2% [97.7, 99.7], algorithmic 97.2% [95.2,
  98.4]; agreement AC1 0.964 / raw 95.8–97.7% (α 0.354, deflated by
  prevalence as pre-registered). 55 items await adjudication; the v2.1 files
  remain the released files until `scripts/freeze_verified_release.py`
  writes v2.2. Dry run on current verdicts: 3 removed as invalid, 7 reverted
  to certified prior forms, 5 source-error, 9 unnatural, 2 calibration —
  well under the ≈100–150 loss pre-registered; contingency rate 0.4%.
  Policy choices stated in `docs/VERIFICATION_PROTOCOL.md` §9. Artifacts:
  `audit/verification/`.

## 8. Files

```
~/datasets/<dataset>_augmented_v2/
  test.json              # augmented examples (+ _aug_meta, gold_cypher, _source_row)
  test.probed.json       # + grounding_probe difficulty signals
  report.json            # per-graph realized distribution + drop reasons
  needs_verification.jsonl  # LLM-proposed edits for human review
verification/verification_annotator_*.csv  # blind annotation queues (5 annotators)
verification/verification_key.csv          # provenance key — NOT for annotators
docs/ANNOTATION_QUICKSTART.md              # annotator-facing instructions
~/datasets/review_queue_ALL.csv            # superseded pilot sheet (814 edits)
```

Generated by `scripts/generate_augmented.py`; probed by
`scripts/grounding_probe.py`; pipeline in `data_augmentation/` (see
`docs/archive/AUGMENTATION_REDESIGN.md`).
