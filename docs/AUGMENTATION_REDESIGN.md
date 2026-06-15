# Data Augmentation Redesign Plan

**Status:** proposal — pending sign-off on the Open Decisions at the bottom.
**Date:** 2026-06-12

## 1. Context

The paper (NAACL submission) claims: existing text2cypher benchmarks are
unrealistically clean — user-mentioned entities almost always match DB values
verbatim — so reported accuracies overestimate real-world robustness. We
(a) quantify this with entity-perturbed versions of CypherBench /
Mind-the-Query / ZOGRASCOPE, (b) show all evaluated LLMs degrade on them, and
(c) show a value-grounding NER agent recovers most of the loss across LLMs.
The perturbed datasets are released as a contribution, so they must survive
dataset-track review.

A code + shipped-data audit (2026-06-11) found the current pipeline unfit for
release. Highlights:

- **Realized ≠ configured distribution.** First-success fallback over
  strategies lets always-succeeding ones absorb the share of frequently
  declining ones: cypherbench is 47.8% casing + 42.8% paraphrase; typo is 0%.
- **`_validate_edit` contradicts the strategies it gates.** Plain Levenshtein
  rejects the typo augmenter's transpositions (typo → 0%); the
  substring-survives rule kills replacement-style synonyms (the surviving
  "synonym" edits are 100% scaffold-style, i.e. de-facto paraphrases).
- **Referent corruption in shipped data.** POLE surnames hallucinated into
  real-world entities (`Wagner` → "the Wagner Group", `Hanson` → "the band
  Hanson"); UK dates re-read as US format (`6/08/2017` → "June 8, 2017");
  typos colliding with *other* real DB values (`WN5` → `NW5`, both UK
  postcode areas). Gold cypher unchanged ⇒ silent label corruption.
- **Splice artifacts.** 25–92 rows per dataset contain "the the" /
  word-doubling ("the the Nile River River"); `.title()` produces
  `"Night'S Watch"`.
- **Non-entities perturbed.** Dates/times/IDs leak through the numeric filter
  (`/` and `:` not stripped; LLM-fallback path has no filter at all) — 566
  date/time edits in zograscope alone.
- **Three pipeline eras mixed.** mtq/zog were generated before the current
  validator (edits exist that today's code cannot produce); cypherbench after.
  The three sets are not comparable and must all be regenerated.
- **Config drift.** Three mutually inconsistent proportion tables
  (`config.DEFAULT_PROPORTIONS`, runner `AUG_PROPORTIONS`/`_TARGET_PCT`, and a
  hard-coded "~18% each" report header).

## 2. Design principles

1. **Role decoupling kills circularity.** LLMs may *propose* surface forms;
   they may never *judge* validity. Judges are: construction guarantees,
   the graph DB itself, attested alias resources, and human annotation.
   Then any LLM (including eval subjects) can be used for generation without
   contaminating the benchmark.
2. **The DB is the oracle we already have.** Every entity span comes from a
   gold-cypher literal, so the canonical value `v` is known per sample.
   Every perturbation `s` must pass DB-grounded checks: no collision with
   another value, unique recoverability of `v` from `s`.
3. **Each category is a rung on a measured difficulty ladder** (casing floor →
   typo/partial → abbrev → alias crown). A post-hoc probe records, per sample,
   whether exact / fulltext / vector lookup still recovers `v` — used for
   stratified analysis and to prove the grounding gap exists, never as an
   LLM-judged gate.
4. **Honest accounting.** Configured targets live in exactly one place;
   realized distribution + drop reasons are reported per dataset; deviations
   are explained by eligibility, not hidden.
5. **Reproducibility.** Per-row seeding from stable row IDs; no nlpaug
   (version-dependent RNG); pinned generation model; one pipeline version for
   all three datasets.

## 3. New taxonomy and targets

| Category | Definition (perturb the entity mention only) | Source of forms | Validity gate | Target |
|---|---|---|---|---|
| `casing` | lower/UPPER re-casing (drop `.title()`) | algorithmic | by construction + collision check | 10% |
| `typo` | exactly one keyboard-adjacent substitution, adjacent transposition, deletion, or doubled letter; never word-initial chars | algorithmic (in-house; no nlpaug) | Damerau-Levenshtein = 1; first char of every word preserved; **margin check**: `v` is the unique DB value within Damerau distance 1 of `s`, next-nearest ≥ 2 | 22.5% |
| `partial` | contiguous token span keeping the most distinctive token; natural reductions (surname-only, drop corporate/type suffix, drop leading descriptor) | algorithmic + per-property token document frequency | must start/end on token boundary; must not start with stopword/preposition; **DB uniqueness**: case-insensitive containment matches exactly one value of that (label, property) | 22.5% |
| `abbrev` | acronym/initialism/short form, both directions | (1) dataset-shipped aliases (CypherBench simplekg `aliases`, Wikidata-derived), (2) curated per-domain tables (ranks: Sergeant→Sgt; existing `_PAIRS`), (3) LLM proposal **flagged for human verification** | attested source OR human-verified; collision check; expansion must be attested alias of the same entity | 22.5% |
| `alias` | replacement-style nickname / colloquial / brand–generic; must NOT contain the original verbatim (modulo articles) — the inverse of today's rule | (1) dataset-shipped aliases, (2) RxNorm brand↔generic for mtq drugs, (3) curated tables, (4) LLM proposal flagged for human verification | attested source OR human-verified; collision check; **synthetic domains (POLE, fraud) ineligible** unless the DB itself stores the alias | 22.5% |
| `paraphrase` | **removed.** Replacement-style outputs are `alias`; scaffold-style ("the actor Tom Hanks") leaves the entity verbatim ⇒ no value-grounding challenge | — | — | 0% |

**Rationale for the mixture (reviewer-facing):** balanced design — the four
informative categories get equal share for uniform per-category statistical
power, with `casing` held at 10% as the control/floor. A balanced mixture also
preempts the objection that the mixture was weighted toward the category where
a grounding agent shines most (`alias`); and since per-category results are
mixture-independent and the datasheet ships per-category counts, readers can
recompute any weighted aggregate. Where attested-source coverage caps
`abbrev`+`alias` below target (e.g. geography; synthetic domains where `alias`
is ineligible), the quota sampler redistributes the surplus to `typo`/`partial`
— per-dataset realized profiles will differ and are reported, not hidden.

Entity-pool rules (extractor level): dates/times excluded everywhere;
emails excluded; postcodes / structured IDs excluded by default
(Open Decision 2). Numeric filter generalized to strip `[\s./:-]`; the same
filter applies to the LLM-fallback extraction path.

## 4. What stays, what changes

**Keep (working assets):** gold-cypher literal extraction & span machinery
(`entity_extractor.py` core), right-to-left span replacement, `_aug_meta`
provenance, dataset adapters, distribution report skeleton,
`MAX_EDITS_PER_ROW = 1` (clean per-sample attribution).

**Rewrite / add:**

| Component | Change |
|---|---|
| `data_augmentation/entity_extractor.py` | generalize numeric/date filter; apply to LLM-fallback path; parse (label, property) context for each literal from the gold cypher (e.g. `x1.surname = "Hanson"` → `(Person, surname)`), fallback = fulltext probe across properties; entity typing (name-like / date / id / email) |
| `data_augmentation/validity.py` **(new)** | DB-grounded judge: distinct-value loader per (label, property) (reuse the distinct-value Cypher from `embedding/embedding_helper.py`), collision check, uniqueness/margin checks, plus the **splice grammar guard** (article dedup "the the"/"a the", a/an agreement, boundary word-doubling) applied to every strategy's output in context |
| `data_augmentation/kb_aliases.py` **(new)** | alias provider: CypherBench simplekg `aliases` lookup (by entity name per graph), curated per-domain tables, optional RxNorm table for mtq; returns (form, source) so provenance lands in `_aug_meta` |
| `data_augmentation/pipeline.py` | delete `_validate_edit` (per-strategy invariants move into augmenters; cross-strategy DB validity into `validity.py`); replace `_strategy_order` first-success fallback with a **deficit-greedy quota sampler** (per row: compute eligible strategies per entity from cheap checks, pick the eligible strategy with the largest target-minus-realized deficit, stochastic tie-break; if every eligible candidate fails validity → drop the row and record the reason — never silently substitute casing); replace **all** occurrences of the entity in the NL with the same perturbed form; per-row RNG `random.Random((SEED, dataset, row_id))` |
| `augmenters/casing.py` | lower/UPPER only |
| `augmenters/typo.py` | in-house generator (keyboard map + transposition + deletion + doubling); drop nlpaug |
| `augmenters/partial_name.py` | head-preserving reductions driven by token document-frequency over the property's values; person-name surname rule; allow 2-token entities |
| `augmenters/abbreviation.py` | sources via `kb_aliases.py`; LLM path becomes proposer-only and flags output for human verification |
| `augmenters/synonym.py` → `augmenters/alias.py` | replacement-style enforced; sources via `kb_aliases.py`; synthetic-domain ineligibility |
| `augmenters/paraphrase.py` | deleted |
| `data_augmentation/config.py` + `run_data_augmentation.py` | single `PROPORTIONS` dict in `config.py`; runner and report header both derive from it; report adds drop-rate table per (dataset, strategy, reason) |
| `scripts/grounding_probe.py` **(new)** | post-hoc annotator: for every edit, probe exact (cs/ci) hit, Lucene fulltext rank of `v` given `s`, vector rank under one pinned documented embedder, Damerau distance; writes `_aug_meta.grounding_probe`; reuses `eval_config.GRAPH_CONNS` + `neo4j_lib` |
| `data_augmentation/STRATEGIES.md` | rewritten to match; plus a datasheet template for release |
| `tests/` | unit tests: Damerau metric, quota-sampler convergence on synthetic decline rates, splice guard, extractor filters, golden small-sample regeneration with fixed seed |

## 5. Regeneration & release

1. Freeze pipeline version; regenerate **all three** datasets in one run
   (same seed scheme, same generation model, documented).
2. Run `grounding_probe.py` against each graph (containers per
   `eval_config.GRAPH_CONNS` / `docs/GRAPHS.md`).
3. Emit per-dataset reports: realized distribution vs targets, drop reasons,
   probe-based difficulty spectrum (expected: casing gap ≈ 0 → alias gap max —
   this figure is itself a paper exhibit).
4. **Human verification** (helpers): stratified sample ≈ 100 rows per dataset
   ≈ balanced over strategies; 2 annotators + adjudication; questions:
   (a) does the perturbed question still uniquely refer to the original
   entity/answer? (b) is the mention plausible real-user input? Report κ.
   All LLM-proposed abbrev/alias forms that survive gating are verified at
   100%, not sampled.
5. Release artifacts: datasets + datasheet (per-domain × per-strategy counts,
   generation method & model, validity gates, verification protocol & κ,
   license), loaders unchanged.

## 6. Paper artifacts this unlocks

- Headline: clean vs perturbed vs perturbed+grounding × N LLMs.
- Per-strategy robustness breakdown (now meaningful — labels are clean).
- Difficulty spectrum from the probe vector (objective, agent-independent).
- Proposer-LLM ablation: performance on LLM-proposed vs attested-source
  samples, by eval model — directly answers the circularity review question.

## 7. Phases & division of labor

| Phase | Work | Owner |
|---|---|---|
| 0 | Sign off taxonomy/targets/open decisions | user |
| 1 | Core infra: extractor fixes, `validity.py`, quota sampler, splice guard, seeding | main |
| 2 | Strategy rewrites + `kb_aliases.py` | main; curated tables + RxNorm extraction → helpers |
| 3 | Regenerate ×3, probe, reports | main |
| 4 | Human verification, datasheet | helpers |
| 5 | Eval matrix + paper tables | helpers run, user analyzes |

## 8. Open decisions

1. **Scaffold/context-add class**: **DECIDED (2026-06-13) — cut entirely.** It
   leaves the entity verbatim ⇒ tests no value-grounding; it was the source of
   the "the the" / date-misread / robotic-phrasing artifacts. Span-boundary
   robustness, if ever wanted, becomes a separate clearly-labeled class later.
2. **Structured IDs / postcodes**: **DECIDED (2026-06-13) — excluded** (along
   with dates/times/emails) from the entity pool. Low grounding value (exact
   lookups, no world-knowledge alias), collision-dense (the `WN5→NW5` bug),
   cleaner scope statement. ID format-normalization, if wanted, becomes a
   deliberate future strategy — never leaked through the numeric filter.
3. **Generation/proposer LLM**: **DECIDED (2026-06-13) — gpt-4.1** (not mini;
   not open-weight). Defensible because every LLM-proposed abbrev/alias form is
   100% human-verified and provenance-tagged in `_aug_meta`, and gpt-4.1 is not
   the headline eval model. Datasheet must pin the exact model id/snapshot used
   at generation time, since an API model can later be retired.
4. **Targets**: balanced 10 / 22.5 / 22.5 / 22.5 / 22.5 as above — sign off?
