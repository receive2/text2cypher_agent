# Datasheet — entity-perturbed text-to-Cypher benchmark (v2.3)

Three open-source text-to-Cypher test sets — CypherBench, Mind-the-Query and
ZOGRASCOPE — in which the entity mention of each question has been rewritten
into a realistic variant (abbreviation, alias, typo, partial name or re-casing)
while the gold Cypher and the graph are unchanged. Every number in this
document is produced by `scripts/render_datasheet_tables.py` from the released
files; the sections between `AUTOGEN` markers are never edited by hand.

## 1. Motivation

In the source benchmarks the entity a question mentions almost always matches
a graph value verbatim, so a system can succeed by exact string matching and
reported accuracy overstates robustness. Real users abbreviate, nickname,
shorten and mistype. Perturbing the mention creates a **grounding gap**: the
system must map the surface form it sees to the value the database stores.

<!-- AUTOGEN:HEADLINE -->
**Headline:** across 4,590 perturbed examples, a baseline case-insensitive exact-match no longer recovers the canonical entity on **89.9%** of them (90.8 / 89.5 / 88.9% on the three datasets independently).
<!-- /AUTOGEN:HEADLINE -->

## 2. Composition

<!-- AUTOGEN:COMPOSITION -->
3 source datasets, 13 property graphs, **4,590** perturbed questions.

| dataset | graphs | examples |
|---|---|--:|
| CypherBench | company, fictional_character, flight_accident, geography, movie, nba, politics | 2,090 |
| Mind-the-Query | bloom, covid, er, healthcare, wwc | 1,217 |
| ZOGRASCOPE | pole | 1,283 |
<!-- /AUTOGEN:COMPOSITION -->

Each question is one record in `benchmarks/<dataset>_augmented_v2/test.json`:

| field | contents |
|---|---|
| `nl` | the perturbed question |
| `gold_cypher` | the original gold query, unchanged |
| `graph`, `id` | the graph and the source question's identifier |
| `_source_row` | the original source row, verbatim |
| `_aug_meta.edits[0]` | the single edit: `strategy`, `from` (database value), `to` (perturbed mention), `source` (provenance), `label`/`prop` (the property the value is compared against), and for LLM-proposed edits `proposer_model` and `evidence` |

`test.probed.json` adds `grounding_probe`, the surface-relation class of §2.3.

### 2.1 Perturbation strategies

One edit per question. Casing is a control (a case-insensitive match still
recovers it); the other four are the informative strategies and were designed
to be equal in share. Released shares differ from the design where a graph's
entities simply have no abbreviations or aliases (§6).

<!-- AUTOGEN:STRATEGY -->
| strategy | what changes | example | design share | released share |
|---|---|---|--:|--:|
| `casing` | re-case the mention (lower / UPPER) | `Sacramento Kings` → `SACRAMENTO KINGS` | 10.0% | 10.1% |
| `typo` | one keyboard slip, transposition, deletion or doubling | `Barletta` → `Balretta` | 22.5% | 31.4% |
| `partial` | drop words, keep a fragment that still identifies it | `Los Angeles Lakers` → `Lakers` | 22.5% | 17.8% |
| `abbrev` | acronym or standard short form | `Golden State Warriors` → `GSW` | 22.5% | 22.5% |
| `alias` | a different name for the same referent | `Tocilizumab` → `Actemra` | 22.5% | 18.3% |
<!-- /AUTOGEN:STRATEGY -->

### 2.2 Provenance

Where the perturbed surface forms come from, and how many of each kind were
checked by human annotators (§4). "Measured" excludes the 48-item calibration
set; counts before and after verification differ because verification removed
or reverted some edits.

<!-- AUTOGEN:PROVENANCE -->
| provenance | pre-verification rows | queued for verification | measured | released rows |
|---|--:|--:|--:|--:|
| algorithmic (rules for casing / typo / partial) | 2,673 | 450 | 448 | 2,668 |
| attested (Wikidata aliases shipped with CypherBench, curated tables, RxNorm) | 1,052 | 400 | 393 | 1,043 |
| LLM-proposed (abstention-first proposer, evidence required) | 916 | 916 | 898 | 879 |
| **all** | 4,641 | 1,766 | 1,739 | 4,590 |
<!-- /AUTOGEN:PROVENANCE -->

### 2.3 Grounding classes

How the perturbed mention relates to the stored value — computed from the two
strings alone, without a model or the database. `semantic` is the tier that
needs world knowledge; its share follows the availability of aliases and
abbreviations in each domain.

<!-- AUTOGEN:GROUNDING -->
| class | relation of the perturbed mention to the database value | all | CypherBench | Mind-the-Query | ZOGRASCOPE |
|---|---|--:|--:|--:|--:|
| `exact_ci` | case-insensitive exact still matches (trivial) | 10.1% | 9.2% | 10.5% | 11.1% |
| `edit_distance` | within Damerau ≤2 (fuzzy-recoverable) | 32.9% | 15.3% | 31.7% | 62.6% |
| `substring` | perturbed ⊆ canonical (fulltext-recoverable) | 25.4% | 29.8% | 23.0% | 20.4% |
| `semantic` | no surface overlap (needs world knowledge / vector) | 31.7% | 45.7% | 34.8% | 5.8% |
<!-- /AUTOGEN:GROUNDING -->

### 2.4 Query-difficulty tiers

A rule-based classifier over the gold Cypher (`eval/difficulty.py`: pattern
reach, operations, filtering) assigns each question to one of three tiers;
results are reported per tier.

<!-- AUTOGEN:TIERS -->
| dataset | n | easy | medium | hard |
|---|--:|--:|--:|--:|
| CypherBench | 2,090 | 16.1% | 53.1% | 30.8% |
| Mind-the-Query | 1,217 | 6.3% | 61.8% | 31.9% |
| ZOGRASCOPE | 1,283 | 6.3% | 74.4% | 19.3% |
| **all** | 4,590 | **10.8%** | **61.3%** | **27.9%** |
<!-- /AUTOGEN:TIERS -->

### 2.5 Per-graph mix

<!-- AUTOGEN:REALIZED -->
Strategy shares per graph (%); `LLM+attested` counts the edits whose surface form came from a knowledge base or a language model rather than a rule.

| dataset | graph | n | casing | typo | partial | abbrev | alias | LLM+attested |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| cypherbench | company | 303 | 10.2 | 14.2 | 20.1 | 26.4 | 29.0 | 170 |
| cypherbench | fictional_character | 322 | 10.9 | 23.6 | 25.8 | 9.3 | 30.4 | 149 |
| cypherbench | flight_accident | 168 | 8.9 | 6.0 | 10.7 | 53.0 | 21.4 | 127 |
| cypherbench | geography | 331 | 10.9 | 14.5 | 16.6 | 23.9 | 34.1 | 194 |
| cypherbench | movie | 359 | 8.9 | 16.7 | 18.4 | 28.1 | 27.9 | 208 |
| cypherbench | nba | 251 | 10.0 | 2.8 | 23.5 | 25.9 | 37.8 | 173 |
| cypherbench | politics | 356 | 5.1 | 5.9 | 12.6 | 48.6 | 27.8 | 272 |
| mindthequery | bloom *(synthetic)* | 24 | 16.7 | 16.7 | 45.8 | 20.8 | 0.0 | 5 |
| mindthequery | covid | 326 | 10.7 | 54.3 | 11.0 | 8.9 | 15.0 | 78 |
| mindthequery | er *(synthetic)* | 184 | 9.2 | 32.6 | 13.6 | 44.6 | 0.0 | 82 |
| mindthequery | healthcare | 418 | 10.5 | 18.9 | 10.0 | 30.9 | 29.7 | 255 |
| mindthequery | wwc | 265 | 10.6 | 23.0 | 30.2 | 21.9 | 14.3 | 96 |
| zograscope | pole *(synthetic)* | 1283 | 11.1 | 61.8 | 18.2 | 8.8 | 0.0 | 113 |
| **ALL** | | 4590 | **10.1** | **31.4** | **17.8** | **22.5** | **18.3** | 1922 |

Within the alias-applicable stratum (67.5% of rows; synthetic graphs are alias-zero by design) alias = **27.1%**. Where a graph's mix departs from the design shares, the cause is the measured supply of attested forms (`audit/APPLICABILITY_CEILING.md`), not allocation.
<!-- /AUTOGEN:REALIZED -->

## 3. How the questions were produced

1. **Entity.** The entity is a string literal of the gold Cypher that also
   occurs in the question; the `(label, property)` it is compared against is
   parsed from the query so every check can be scoped to that property's
   values. Dates, times, e-mail addresses and structured identifiers are never
   perturbed (they are lookup keys, and collision-dense).
2. **Strategy.** A quota sampler picks the strategy with the largest deficit
   against the design shares among those that yield a valid edit for the
   question; casing is capped at its share; a question with no valid edit is
   dropped, never given a trivial edit instead.
3. **Surface form.** Casing, typo and partial names are generated by rules.
   Abbreviations and aliases come first from attested sources — Wikidata
   aliases shipped with CypherBench, curated tables, RxNorm for drugs — and
   only where none exists from an LLM proposer that must abstain unless a
   real form exists and must cite one-sentence evidence. Aliasing is disabled
   on the synthetic graphs (`pole`, `bloom`, `er`), whose entities have no
   real-world names.
4. **Database gates** (model-free, on the live graph): the new form must not
   equal a different value of the same property; a partial name must resolve
   to exactly one value; a typo must leave the original the unique value
   within edit distance 1; the splice into the question is grammar-checked.
5. **Proposer models.** LLM-proposed edits were produced by `claude-opus-5`
   (852 released edits, each carrying `proposer_model` and `evidence`); 27
   released edits come from an earlier `gpt-4.1` pass and carry no per-edit
   pin. No LLM judged validity at any point.

Generation is deterministic given the seed and reads the graph only; the
full specification is `docs/AUGMENTATION_METHODS.md`. The release is frozen
as a decision manifest (`benchmarks/release_manifest_v2.3.jsonl`);
`scripts/rebuild_from_manifest.py` regenerates every question from it and
checks the released files' hashes.

## 4. Human verification

Five annotators (graduate volunteers, not authors) checked whether perturbed
mentions still denote the original value and whether the questions read
naturally. Every LLM-proposed edit was labelled by two annotators; the
attested and algorithmic tiers were labelled on stratified samples.
Disagreements were adjudicated by the first author. The protocol, the
agreement statistics and how they should be read, the verdict rules and the
released artifacts are in `docs/VERIFICATION_PROTOCOL.md`.

<!-- AUTOGEN:VERIFICATION -->
**Release v2.3-verified-2026-09-22** — 4,641 rows in → **4,590** released (51 removed, 20 reverted to a certified prior algorithmic form, 0 pending). Naturalness policy: `drop-unnatural`. Verdicts from 5 annotators over 1,739 measured items: 1,529 labelled by two annotators and 210 by one; 27 calibration items excluded.

Inter-annotator agreement (validity): Krippendorff's α = **0.354**, Gwet's AC1 = **0.964**, disagreement rate 3.5%.

| provenance | n | validity % [95% CI] | α | AC1 | raw agr (n₂) | action |
|---|--:|---|--:|--:|---|---|
| algorithmic | 448 | 96.2% [94.0, 97.6] | 0.482 | 0.956 | 95.8% (238) | invalid → remove |
| attested | 393 | 98.5% [96.7, 99.3] | 0.390 | 0.977 | 97.7% (393) | invalid → revert/remove |
| llm | 898 | 97.2% [95.9, 98.1] | 0.291 | 0.961 | 96.2% (898) | invalid → revert/remove |

| strategy | n | validity % [95% CI] | α | AC1 | raw agr (n₂) |
|---|--:|---|--:|--:|---|
| abbrev | 728 | 96.7% [95.1, 97.8] | 0.357 | 0.957 | 95.9% (728) |
| alias | 520 | 98.7% [97.2, 99.3] | 0.178 | 0.975 | 97.5% (520) |
| casing | 99 | 100.0% [96.2, 100.0] | 1.000 | 1.000 | 100.0% (79) |
| partial | 192 | 92.1% [87.4, 95.2] | 0.438 | 0.921 | 92.6% (122) |
| typo | 200 | 99.0% [96.4, 99.7] | 0.664 | 0.987 | 98.8% (80) |

Per-row verdicts (annotators as letters A–E), the blind key, the calibration reference answers and the statistics report ship in `audit/verification/`; `decisions.csv` maps every pre-verification row to its action and its position in the released files.
<!-- /AUTOGEN:VERIFICATION -->

## 5. Curation history

| date | change | questions |
|---|---|--:|
| 2026-06 | first complete perturbed set (v2) | 4,875 |
| 2026-08-09 | edits whose validity checks had never run were re-checked; 186 out-of-scope "entities" (identifiers, schema words, dates) and 19 hand-checked defects removed | 4,670 |
| 2026-08-09 | partial-name rule rewritten (distinctive-token requirement); all rule-based partials regenerated | 4,664 |
| 2026-08-09 | LLM-proposed tier regenerated with an abstention-first, evidence-required proposer (`claude-opus-5`) | 4,648 |
| 2026-08-22 | mid-word replacement bug fixed (`us` inside `users`); 47 questions repaired | 4,641 |
| 2026-08-22 | strategy mix rebalanced to the measured supply of attested forms; no questions removed | 4,641 |
| 2026-08-22 | generation frozen: decision manifest v2.1 | 4,641 |
| 2026-09-09 | human-verification verdicts applied: 20 edits reverted to their rule-based form, 30 questions removed (v2.2) | 4,611 |
| 2026-09-22 | the verdict rules applied uniformly to every tier: the 21 sampled rule-based edits that annotators had judged invalid or unnatural, until then kept and reported as a rate, removed — **v2.3, the released set** | 4,590 |

Row-level logs for each step are in `audit/`; the day-by-day record of the
annotation campaign is `docs/archive/ANNOTATION_PROCESS_LOG.md`.

## 6. Known limitations

- **Supply-driven mix.** Where entities have no abbreviations or aliases
  (fictional characters, contact-tracing places, the synthetic graphs), the
  mix is typo/partial-heavy. The attainable supply per graph and strategy was
  measured (`audit/APPLICABILITY_CEILING.md`) and the mix filled to it;
  headline metrics are macro-averaged over strategies.
- **Gold queries that do not execute.**

<!-- AUTOGEN:GOLD -->
31 of the 4,590 released gold queries (0.7%) do not execute (gold verdicts recorded by the evaluation harness in a complete run over the released rows, 30 s server-side timeout; 2026-09-22). They are kept as shipped and score 0 for every system, so they lower every method equally.

| dataset | graph | questions | non-executing golds |
|---|---|--:|--:|
| mindthequery | covid | 326 | 14 |
| mindthequery | er | 184 | 3 |
| mindthequery | healthcare | 418 | 4 |
| mindthequery | wwc | 265 | 10 |
<!-- /AUTOGEN:GOLD -->

- **Gold queries with empty results.** On the Mind-the-Query graphs a
  noticeable share of golds legitimately return no rows (healthcare 45%,
  er 29%, bloom 21%, wwc 12%, covid 3%; `report/empty_gold_rates.md`). An
  evaluation that compares result sets should treat empty-vs-empty
  deliberately.
- **Verification depth.** Only the LLM-proposed tier was checked
  exhaustively; the attested and algorithmic tiers were sampled, so their
  validity is an estimate with a confidence interval, and un-sampled rows of
  those tiers were not individually inspected.
- **Curated tables are small** (a few dozen acronym and nickname pairs);
  the primary attested source is the Wikidata aliases shipped with
  CypherBench.
- **Synthetic graphs have no aliases**, so the `alias` strategy is absent
  there by design.
- **Only one perturbation per question**, always of one entity mention.

## 7. Intended use and distribution

The benchmark measures whether a text-to-Cypher system grounds a user's
surface form to the stored value; it is not a test of Cypher generation on
its own. Evaluate on the released rows exactly (`python benchmarks/verify.py`
pins their hashes) so results are comparable across papers; compare against
the original questions to isolate the effect of perturbation
(`scripts/clean_vs_perturbed.py`). The source datasets' licences apply to
the questions and graphs (`audit/LICENSE_AUDIT.md`); the perturbations,
manifest and verification artifacts are released with this repository.

## 8. Files

```
benchmarks/<dataset>_augmented_v2/test.json      the benchmark
benchmarks/<dataset>_augmented_v2/test.probed.json  + grounding classes
benchmarks/verify.py                              release check (hashes)
benchmarks/release_manifest_v2.3.jsonl            decision manifest, one record per question
benchmarks/removed_rows.jsonl                     the 51 questions verification removed, as they stood before it
audit/verification/                               verdicts, blind key, adjudications, statistics
audit/gold_executability.json                     which golds do not execute
docs/AUGMENTATION_METHODS.md                      how each strategy is generated and gated
docs/VERIFICATION_PROTOCOL.md                     how the data was verified
docs/ANNOTATION_QUICKSTART.md                     the guide the annotators worked from
docs/LLM_USE_DISCLOSURE.md                        the role of LLMs in constructing the data
```

## 9. Maintenance

`v2.3-verified-2026-09-22` is the current release; `benchmarks/verify.py`
names the version and pins the file hashes, and any later release will carry
a new version string, manifest and hashes. Issues with individual questions
can be reported against the question's `graph` and `id`; the manifest and
`audit/verification/decisions.csv` trace every released question back to its
source row and to the decisions that produced it.
