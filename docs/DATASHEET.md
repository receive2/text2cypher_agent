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

**Headline:** across 4,875 perturbed examples, a baseline case-insensitive
exact-match no longer recovers the canonical entity on **89.9%** of them
(89.8 / 89.9 / 90.0% on the three datasets independently).

## 2. Composition

3 datasets, 13 graphs, **4,875** perturbed examples (test split).

| dataset | graphs | examples |
|---|---|--:|
| CypherBench | nba, flight_accident, fictional_character, company, geography, movie, politics | 2,136 |
| Mind-the-Query | bloom, covid, er, healthcare, wwc | 1,298 |
| ZOGRASCOPE | pole | 1,441 |

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

| class | meaning | all | cypherbench | mtq | zograscope |
|---|---|--:|--:|--:|--:|
| `exact_ci` | case-insensitive exact still matches (trivial) | 10.1% | 10.1% | 10.2% | 10.0% |
| `edit_distance` | within Damerau ≤2 (fuzzy-recoverable) | 38.3% | 25.5% | 41.1% | 54.7% |
| `substring` | perturbed ⊆ canonical (fulltext-recoverable) | 30.2% | 31.6% | 27.3% | 30.7% |
| `semantic` | no surface overlap (needs world knowledge / vector) | 21.4% | 32.8% | 21.3% | 4.6% |

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

`kept/total` examples and realized strategy %; `verify` = LLM-proposed edits
queued for human verification.

| dataset | graph | kept/total | casing | typo | partial | abbrev | alias | verify |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| cypherbench | nba | 258/270 | 10.1 | 22.9 | 22.1 | 22.1 | 22.9 | 75 |
| cypherbench | flight_accident | 170/189 | 10.0 | 22.4 | 22.4 | 22.4 | 22.9 | 24 |
| cypherbench | fictional_character | 326/385 | 10.1 | 29.4 | 28.5 | 2.8 | 29.1 | 88 |
| cypherbench | company | 308/347 | 10.1 | 22.7 | 22.4 | 22.1 | 22.7 | 42 |
| cypherbench | geography | 339/366 | 10.0 | 23.0 | 23.0 | 20.9 | 23.0 | 87 |
| cypherbench | movie | 370/401 | 10.0 | 22.7 | 22.2 | 22.4 | 22.7 | 78 |
| cypherbench | politics | 365/390 | 10.1 | 22.5 | 22.5 | 22.5 | 22.5 | 37 |
| mindthequery | bloom *(synthetic)* | 40/58 | 10.0 | 50.0 | 27.5 | 12.5 | 0.0 | 6 |
| mindthequery | covid | 342/438 | 10.2 | 63.5 | 20.2 | 0.0 | 6.1 | 22 |
| mindthequery | er *(synthetic)* | 202/421 | 10.4 | 37.6 | 17.8 | 34.2 | 0.0 | 30 |
| mindthequery | healthcare | 439/460 | 10.0 | 26.9 | 26.4 | 10.0 | 26.7 | 174 |
| mindthequery | wwc | 275/452 | 10.2 | 33.5 | 33.1 | 2.5 | 20.7 | 60 |
| zograscope | pole *(synthetic)* | 1441/2117 | 10.0 | 54.0 | 30.0 | 6.0 | 0.0 | 91 |

**Honest accounting.** `casing` is pinned at 10% everywhere. Where entities have
abbreviations/aliases (all CypherBench except fictional_character; healthcare),
the four informative strategies reach ~22.5% each. Where they do not
(fictional_character, covid, wwc, and synthetic graphs where `alias` is off),
the realized mix is `typo`/`partial`-heavy by supply, not by design — we report
the per-graph mix rather than forcing abbreviations/aliases that do not exist.

## 7. Quality control & known limitations

- **Human verification.** Every LLM-proposed edit (814 total: alias 403,
  abbrev 225, partial 186) is queued for human verification
  (`review_queue_ALL.csv` + `docs/REVIEW_GUIDE.md`); algorithmic and
  attested-source edits are trusted. Verdicts (keep/fix/drop) are applied to
  produce the released version. **This v2 is pre-verification.**
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

## 8. Files

```
~/datasets/<dataset>_augmented_v2/
  test.json              # augmented examples (+ _aug_meta, gold_cypher, _source_row)
  test.probed.json       # + grounding_probe difficulty signals
  report.json            # per-graph realized distribution + drop reasons
  needs_verification.jsonl  # LLM-proposed edits for human review
~/datasets/review_queue_ALL.csv     # consolidated review sheet (814 edits)
docs/REVIEW_GUIDE.md                # human-verification instructions
```

Generated by `scripts/generate_augmented.py`; probed by
`scripts/grounding_probe.py`; pipeline in `data_augmentation/` (see
`docs/archive/AUGMENTATION_REDESIGN.md`).
