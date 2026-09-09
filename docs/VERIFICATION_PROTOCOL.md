# Human Verification Protocol — Entity-Perturbed text2cypher Benchmark

The release-grade protocol for human-validating the benchmark's entity
perturbations. It supersedes the annotator-facing [`REVIEW_GUIDE.md`](REVIEW_GUIDE.md)
(which it keeps as the per-row instruction sheet) by adding the methodology a
benchmark paper needs: coverage of **all** provenance classes, double
annotation, inter-annotator agreement (IAA), adjudication, and a fixed
reporting schedule.

Tooling: [`scripts/verification_sample.py`](../scripts/verification_sample.py)
builds the (seeded, stratified) annotation queues; after annotation,
[`scripts/verification_stats.py`](../scripts/verification_stats.py) computes IAA
+ validity rates with confidence intervals.

---

## 0. Why this exists

Each test question's entity mention is rewritten to a realistic variant while
the gold Cypher (which uses the **canonical** value) is left unchanged. The
benchmark is only valid if every rewrite **still refers to the same database
entity** — otherwise the gold answer is silently wrong (*referent corruption*).
Automatic checks (DB grounding, attested aliases, collision filters) catch most
cases but not all (a typo can land on another real value; a KB alias can be
ambiguous). Human verification measures the residual corruption rate and makes
it defensible.

## 1. What each item is judged on (three independent labels)

| field | values | meaning |
|---|---|---|
| **validity** *(decisive)* | `valid` / `invalid` / `unsure` | Does the perturbed surface form still refer to the **same, unique** DB entity? `invalid` if it (a) names a *different* entity, (b) names a *sibling* in the same family, or (c) is **ambiguous** (could resolve to several entities). Because the gold Cypher uses the unchanged canonical value, **validity = gold correctness**. |
| **naturalness** *(quality)* | `natural` / `awkward` / `unnatural` | Would a real user plausibly write it in a question? |
| **source_error** *(side-channel)* | `yes` / `no` | Is the *source dataset's own gold* already wrong here (independent of the perturbation)? Flag → excluded from the release, **not** counted as perturbation corruption. |

The `keep / fix / drop` action is **derived** from the three (see §6); annotators
record the three primitives so validity rate and naturalness rate can be reported
cleanly and separately.

## 2. Annotators

- **≥ 3 annotators** (3 enables Krippendorff's α / Fleiss κ; 2 only supports
  Cohen κ).
- Domain familiarity matching the datasets (NBA, geography, politics, aviation,
  biomedical…). Each row carries a one-line KB description of the canonical
  entity to aid judgment.
- **Independent**: no communication during annotation; item order **randomised
  per annotator**.
- **Blind to provenance** (annotators are not told whether a row is LLM- / KB- /
  rule-generated) and **blind to any system output** (never show model
  predictions). The sampler enforces this — provenance lives only in the key
  file, never in the annotator CSVs.
  *Disclosure:* the annotator CSVs do show the **intended strategy**
  (typo/alias/abbrev/partial/casing). This is deliberate and load-bearing — the
  typo rule ("a deliberate misspelling is `valid` if still recognizable")
  cannot be applied without knowing the row is a typo. Strategy does not reveal
  the generation provenance that the anti-circularity claim depends on
  (LLM vs KB vs rule for alias/abbrev/partial stays hidden).

## 3. Coverage — what gets verified (all provenance classes)

The benchmark (4,641 perturbations at the v2.1 freeze the queue was drawn
from; 4,611 in the verified v2.2 release — §9) splits by **provenance**, which
determines how each part is verified. Counts are for the v2.1 freeze and
already reflect the coverage revision of 2026-08-25 (§6):

| provenance | in release | verified | how |
|---|--:|--:|---|
| **LLM-proposed** (alias/abbrev/partial) | 916 | **916 (100%)** | **Full census** — every item, double-annotated |
| **Attested / KB** (alias/abbrev from a knowledge base) | 1,052 | 400 (38%) | Stratified sample, double-annotated |
| **Algorithmic / rule** (casing, typo, rule-based partial) | 2,673 | 450 (17%) | Powered stratified sample |

- **Tier 1 — full census of all 916 LLM-proposed edits.** Non-negotiable: this
  tier carries the highest corruption risk and underpins the anti-circularity
  claim (no model judges its own proposals). A census *cleans* — every invalid
  item is identified and removed, which sampling cannot do.
- **Tier 1b — stratified sample of the 1,052 attested/KB edits.** These carry
  external provenance and are lower-risk, so their validity is *measured*
  (reported with a Wilson CI) rather than exhaustively cleaned; un-sampled
  attested rows remain in the release.
- **Tier 2 — powered sample of the 2,673 purely-algorithmic edits.** "Trusted by
  construction" is an assumption; *measure* it. This tier estimates a rate and
  triggers no removals. Typo is the largest strategy (1,422) **and** the most
  collision-prone, so it carries the largest share of the sample.

Stratify (and report) on three axes: **strategy × provenance × source dataset**
(CypherBench / Mind-the-Query / ZOGRASCOPE) — corruption risk differs by domain.

## 4. Procedure (order matters)

1. **Calibration round.** All annotators jointly label ~50 items spanning every
   strategy; discuss disagreements; refine the guideline. The calibration set is
   **excluded** from the measured release (prevents data-snooping).
2. **Freeze the guideline** (pre-registration). It is not edited mid-annotation.
3. **Double annotation.** Every queued item (Tier 1 census + Tier 2 sample) is
   labeled by **≥ 2 independent annotators**. The sampler assigns each item to a
   rotating annotator pair, so coverage is even and every pair co-annotates a
   share (enabling pairwise κ and a missing-data-tolerant Krippendorff α).
4. **Compute IAA** (§5). If a stratum's α/κ is low, the guideline is unclear for
   it → refine and **re-annotate that stratum**; never silently accept.
5. **Adjudication.** Items where the two annotators disagree (incl. any `unsure`)
   are resolved to a single gold label by a third annotator / expert, or by
   consensus discussion. Record the **disagreement rate** and the method.
6. **Apply outcomes** (§6) and report (§7).

## 5. Inter-annotator agreement (the reliability evidence)

Computed on the **validity** label (the decisive one):

- **Krippendorff's α** (nominal) over the full item×rater matrix — handles 2
  raters/item with missing cells, so it fits the rotating-pair design. **Primary.**
- **Pairwise Cohen's κ** per annotator pair (on co-annotated items) — reported
  for transparency.
- **Fleiss' κ** if (and only if) a fully-overlapped subset exists.

Report **overall + per strategy + per dataset**. Acceptance: **α/κ ≥ 0.6**
acceptable, **≥ 0.8** strong. (Naturalness IAA may go in an appendix.)

## 6. Applying the verdicts

- `invalid` or `source_error` → **drop** from the release. The released
  benchmark is the cleaned set; report the **final N**.
- `valid` + (`awkward`/`unnatural`) → either **drop** (cleanest — introduces no
  unverified surface form) or **fix** to a better form *and re-verify the fixed
  form* in a second pass. State which policy was used.
- `valid` + `natural` → **keep**.

**IAA reporting under the revised coverage (2026-08-25).** The
double-annotation budget for the algorithmic tier is allocated **evenly across
strategies** (not proportionally), so every stratum has comparable power for
per-stratum agreement: abbrev 740 / alias 527 / partial 129 / typo 80 /
casing 80 double-annotated items in the shipped queue (abbrev 728 / alias 520 /
partial 122 / typo 80 / casing 79 **measured**, after the pre-registered
exclusion of calibration items — see below), plus ~155 co-annotated items per
annotator pair for Cohen's kappa. Per-stratum tables report **raw pairwise agreement
alongside Krippendorff's alpha**, because alpha is deflated by construction in
high-prevalence strata: when ~97% of items share one label, chance agreement is
already ~97%, and alpha can approach zero despite near-perfect agreement (the
"kappa paradox"). Acceptance is judged on alpha where label variance permits and
on raw agreement otherwise, with the stratum's `n_2` reported so readers can see
the power behind each figure.

**Coverage revision (2026-08-25, pre-annotation).** Annotator availability
(volunteer lab members) required reducing per-person load. Revised design:
**LLM-proposed edits keep a full double-annotated census** (916 items — the
highest-risk tier, and the basis of the anti-circularity claim); the
**attested/KB tier moves from census to a strategy-stratified sample**
(400 of 1,052, double-annotated) and is therefore *measured* rather than
exhaustively cleaned — its validity rate is reported with a Wilson CI and
un-sampled attested rows remain in the release; the **algorithmic Tier-2
sample** is reduced to 450 items, of which 240 are double-annotated (weighted
evenly across strategies for per-stratum IAA) and the remaining 210
single-annotated (this tier estimates a rate; it triggers no removals). Total
shipped queue: **1,766 items / 3,322 judgments** (1,556 double + 210 single;
~664 judgments per annotator). This remains well above comparable released
benchmarks (e.g. VeriTaS, ACL 2026, validated 25k claims with ~816 human
annotations).

**Calibration exclusion (pre-registered).** Calibration items may overlap the
main queue, and annotators receive guideline feedback on them before the main
pass, so their main-queue labels are not independent first judgments. All
annotators share a **single 48-item calibration set** (the set from the first
package generation, retained across rebuilds — see the process log for why);
27 of its items sit in the main queue. `verification_stats.py` excludes these
ids from **all** reported measurements automatically (auto-detected from
`verification/calibration_50.csv` / `calibration_legacy_ids.csv`, which now
list the same set), leaving **1,739 measured items / 3,268 judgments**.
Excluded items' main-queue labels are retained only as an informal
intra-annotator consistency check, never in any reported figure. A
transiently used alternative calibration set (drawn 2026-08-25, packaged but
**never sent to anyone**) was retired the same day; having reached no
annotator, it requires no exclusion
(`verification/retired_newset_2026-08-25/`).

**Pre-registered rejection handling for converted rows** (fixed before
annotation; see the datasheet curation log, 2026-08-22): a rejected edit on a
row with a logged prior valid form reverts to that form; rows without one
follow the rules above. Canonical dataset figures are post-adjudication.

## 7. What to report in the paper (fixed schedule)

A "Human Verification" subsection with:

1. Annotator count + qualifications + calibration.
2. Verification scope: Tier 1 census size, Tier 2 sample sizes.
3. **IAA**: validity α (and κ), **overall + per strategy + per dataset**.
4. **Validity (and corruption = 1−validity) rate**: overall + per stratum, each
   with a **Wilson 95% CI** (e.g. `alias valid 96.5% [94.8, 97.8]`).
5. **Sampled validity rate + CI for the attested and algorithmic tiers**
   (justifies trusting the 652 un-sampled attested and 2,223 un-sampled
   algorithmic rows).
6. **Disagreement rate** + adjudication method.
7. **Final released N** after dropping invalid / source-error rows.

## 8. Ethics & reproducibility

- Annotator recruitment, informed consent, and compensation (Responsible-NLP
  section).
- Release the verification artifacts: anonymised per-item verdicts, the key file,
  and the `verification_stats.py` output, so reviewers can recompute every number.

## 9. Results and release freeze

**Collection** completed 2026-09-09: 5/5 annotators, 3,322 judgments, every
`validity` cell filled. **Adjudication** of the 55 unresolved items (raters
disagreed, or agreed on `unsure`) was done on 2026-09-09 by the first author
from the worklist (`scripts/adjudication_worklist.py`; both raters' labels
and notes visible, no model involved): 29 valid / 26 invalid (LLM 16/18,
attested 6/3, algorithmic 7/5). Recorded in `audit/verification/adjudicated.csv`.

**Final figures** (1,739 measured items; `audit/verification/stats.md`):

| tier | n | validity [95% CI] | α | AC1 | raw agr (n₂) |
|---|--:|---|--:|--:|---|
| LLM-proposed | 898 | **97.2% [95.9, 98.1]** | 0.291 | 0.961 | 96.2% (898) |
| attested / KB | 393 | 98.5% [96.7, 99.3] | 0.390 | 0.977 | 97.7% (393) |
| algorithmic | 448 | 96.2% [94.0, 97.6] | 0.482 | 0.956 | 95.8% (238) |
| all | 1,739 | 97.3% | 0.354 | 0.964 | 96.5% (1,524) |

By strategy: casing 100.0 · typo 99.0 · alias 98.7 · abbrev 96.7 · partial
92.1% [87.4, 95.2]. Disagreement 3.5%; source-error flags 5. α is deflated by
prevalence exactly as anticipated in §6; AC1 and raw agreement are the
readable reliability figures, and the strata with real label variance (typo
α 0.66, partial 0.44) show the annotators were engaged.

**Release freeze** (`scripts/freeze_verified_release.py`, 2026-09-09, rules of
§6 and the 2026-08-22 pre-registration applied verbatim): 4,641 → **4,611**
rows (cypherbench 2,099 · mindthequery 1,222 · zograscope 1,290). Actions:
20 reverted to a certified prior algorithmic form (LLM 19, attested 1), 30
removed — 11 invalid without a prior form (LLM 6, attested 5), 5
source-error, 12 valid-but-unnatural (LLM 9, attested 3), 2 calibration items
judged invalid by the organizer key; 17 algorithmic-tier rejections and 12
naturalness flags kept and reported as rates (§3). Contingency rate 1.5% (stop
threshold 20%). Policy choices the protocol leaves open, fixed before
adjudication: `valid`+`unnatural` **dropped**, `valid`+`awkward` **kept** in
the census tiers (a single rater's flag suffices — flags never co-occurred on a
double-annotated item); Tier-2 rejections **kept**; calibration items follow
the organizer reference answer. Manifest `release_manifest_v2.2.jsonl`
verifies against the released files with `rebuild_from_manifest.py`
(three-way: rebuilt = frozen hash = file on disk); every v2.1 row's fate is in
`audit/verification/decisions.csv`, and `rescore_on_verified.py --decisions`
re-derives evaluation metrics from runs made on v2.1 without re-running any
model.

---

## Appendix — running the tooling

```bash
# 1. Build the seeded, stratified, blinded annotation queues.
python scripts/verification_sample.py \
    --out verification/ --annotators 3 --seed 42 \
    --sample-typo 300 --sample-partial 200 --sample-casing 150
# -> verification/verification_key.csv          (full metadata; NOT for annotators)
#    verification/verification_annotator_A.csv  (blind; A fills validity/naturalness/...)
#    verification/verification_annotator_B.csv
#    verification/verification_annotator_C.csv

# 2. Annotators fill their CSVs (validity, naturalness, source_error,
#    corrected_form, notes), then:
python scripts/verification_stats.py \
    --key verification/verification_key.csv \
    --annotations verification/verification_annotator_*.csv \
    --out verification/report.md
# -> Krippendorff alpha + pairwise Cohen kappa, validity rate + Wilson CI
#    per (strategy x provenance x dataset) and overall, disagreement rate,
#    final retained N.
```
