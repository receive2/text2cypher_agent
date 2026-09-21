# Human verification of the perturbed benchmark

How the entity perturbations in the released benchmark (v2.2, 4,611 questions
over 13 graphs) were verified by human annotators, and what the verification
found. Annotator-facing instructions are in `ANNOTATION_QUICKSTART.md`; the
day-by-day record is in `ANNOTATION_PROCESS_LOG.md`; every number below can be
recomputed from `audit/verification/` with `scripts/verification_stats.py`.

## 1. What is verified

Each perturbation replaces one entity mention in a question (e.g. `Montana` →
`MT`) while the gold Cypher and the graph stay unchanged. Verification asks
whether the new mention still denotes the same database value, and whether the
question still reads naturally.

Perturbations come from three sources, which determine how they are verified:

| source | in release | verified | how |
|---|--:|--:|---|
| LLM-proposed (abbreviations, aliases, some partial names) | 916 | 916 (every item) | full census, two annotators per item |
| attested (aliases/abbreviations taken from a knowledge base or property table) | 1,052 | 400 | stratified random sample, two annotators per item |
| algorithmic (casing, typo, rule-based partial names) | 2,673 | 450 | stratified random sample: 240 items with two annotators, 210 with one |

The LLM tier is audited exhaustively because it carries the highest risk and
because the anti-circularity claim depends on it: no model ever judges its own
proposals. The other two tiers are sampled to *measure* their error rate; their
un-sampled items stay in the release unchanged.

## 2. Labels

Two labels per item, judged from the question, the original mention, the
perturbed mention and the database value:

- **validity** (decisive): `valid` — the perturbed mention still refers to the
  same, unique database value; `invalid` — it does not (wrong entity,
  ambiguous, or nonsensical); `source_error` — the original question or gold
  query is itself broken; `unsure`.
- **naturalness**: `natural` / `awkward` / `unnatural` — how the perturbed
  question reads to a fluent speaker.

Database-side facts (does the canonical value exist, is it unique) are checked
by machine before annotation; annotators judge reference and readability only.

## 3. Procedure

1. **Calibration.** All five annotators labelled the same 48 items spanning
   every strategy, received written feedback against a reference key, and the
   guideline was finalised. Calibration items are excluded from all statistics.
2. **Annotation.** The queue (1,766 items, 3,322 judgments) was split across
   the five annotators so that every double-annotated item is seen by a
   rotating pair and every pair shares roughly 150 items. Annotators worked
   independently from a blind CSV (no source, no model name, no other rater's
   label).
3. **Adjudication.** Items where the two annotators disagreed, or both marked
   `unsure`, were resolved by the first author from a worklist showing both
   labels and notes; no model was involved. 55 items were adjudicated
   (29 valid, 26 invalid).
4. **Verdicts** were applied by a script under fixed rules (§5) to produce the
   release.

Five annotators took part: graduate-student volunteers from the lab, not
authors of the paper, acknowledged with a small gift-card honorarium. They
appear in the released artifacts only as letters A–E.

## 4. Agreement

Agreement is computed on the validity label over the 1,524 double-annotated
items (1,739 items were measured in total).

| | overall | LLM-proposed | attested | algorithmic |
|---|--:|--:|--:|--:|
| double-annotated items | 1,524 | 898 | 393 | 238 |
| raw agreement | 96.5% | 96.2% | 97.7% | 95.8% |
| Gwet's AC1 | 0.964 | 0.961 | 0.977 | 0.956 |
| Krippendorff's α | 0.354 | 0.291 | 0.390 | 0.482 |

By strategy (raw agreement / α): casing 100% / 1.00 · typo 98.8% / 0.66 ·
alias 97.5% / 0.18 · abbrev 95.9% / 0.36 · partial 92.6% / 0.44. Pairwise
Cohen's κ over the ten annotator pairs ranges from 0.00 to 0.59 (~150 shared
items each); several pairs have no label variance at all.

**How to read these.** 97% of items are valid, so two annotators agreeing by
chance would already reach ~97%; chance-corrected coefficients such as α and
κ therefore have almost no room above zero and are uninformative here (the
"high agreement, low kappa" effect). Raw agreement and AC1, which is designed
to be robust to skewed label prevalence, are the figures that describe the
annotation: annotators disagreed on 3.5% of double-annotated items, and every
one of those disagreements was adjudicated by hand. Where a stratum has real
label variance (typo, partial), α is moderate as well.

## 5. Verdict rules

Applied by `scripts/freeze_verified_release.py`, fixed before adjudication:

| final label | LLM-proposed / attested (census or sampled item) | algorithmic (sampled item) |
|---|---|---|
| `source_error` | remove the question | remove the question |
| `invalid` | revert to the question's certified algorithmic perturbation if one exists, otherwise remove | keep (the tier is measured, not cleaned; reported as a rate) |
| `valid` + `unnatural` | remove | keep, reported as a rate |
| `valid` + `awkward` / `natural` | keep | keep |
| never sampled | keep | keep |

Calibration items follow the organiser's reference answer. A contingency stop
(halt and re-plan if more than 20% of no-prior census items were invalid) was
pre-set and not triggered (1.5%).

## 6. Results

Validity, with Wilson 95% confidence intervals:

| source | measured | valid | invalid | source error | validity |
|---|--:|--:|--:|--:|---|
| LLM-proposed | 898 | 870 | 25 | 3 | 97.2% [95.9, 98.1] |
| attested | 393 | 387 | 6 | 0 | 98.5% [96.7, 99.3] |
| algorithmic | 448 | 429 | 17 | 2 | 96.2% [94.0, 97.6] |

By strategy: casing 100.0% · typo 99.0% · alias 98.7% · abbrev 96.7% ·
partial 92.1% [87.4, 95.2].

Release: 4,641 questions in the pre-verification set → **4,611** released.
20 questions reverted to their certified algorithmic perturbation (19 LLM, 1
attested); 30 removed — 11 invalid without a prior form, 5 source errors, 12
valid but unnatural, 2 calibration items judged invalid by the reference key.
17 invalid and 12 unnatural algorithmic-tier items were kept and are reported
above as rates. Per dataset: CypherBench 2,099 · Mind-the-Query 1,222 ·
ZOGRASCOPE 1,290. The strategy mixture is unchanged (typo 31.3% · abbrev
22.4% · alias 18.2% · partial 18.1% · casing 10.0%).

## 7. Artifacts

`audit/verification/` ships with the data:

| file | contents |
|---|---|
| `verdicts_long.csv` | every judgment: item, annotator letter, validity, naturalness, note |
| `verification_key.csv` | the blind key: item → source, strategy, original and perturbed mention |
| `adjudicated.csv` | the 55 adjudicated items with both raters' labels and the final label |
| `calibration_ids.csv`, `calibration_key.csv` | the calibration set and its reference answers |
| `decisions.csv` | every pre-verification row → action (keep / revert / remove) and its position in the released files |
| `stats.json`, `stats.md`, `summary.json` | all statistics above, machine-readable and rendered |

`benchmarks/release_manifest_v2.2.jsonl` records, for every released
question, the perturbation applied, the proposer model and its evidence for
LLM-proposed edits, and the verification action; `scripts/rebuild_from_manifest.py`
regenerates the released files from it and checks their hashes.
