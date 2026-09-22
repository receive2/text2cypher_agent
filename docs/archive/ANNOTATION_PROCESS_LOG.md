# Annotation process log — recruitment, communications, and lessons

Running record of the human-verification effort: what was sent to annotators,
what the calibration round revealed, and how the design changed in response.
Kept for two reasons — reproducibility of the *process* (not just the data),
and source material for the paper's Limitations / Responsible-NLP sections.

Methodology of record: `docs/VERIFICATION_PROTOCOL.md`.
Annotator-facing instructions: `docs/ANNOTATION_QUICKSTART.md`.

---

## 1. Timeline

| date | event |
|---|---|
| 2026-08-22 | Generation side frozen (4,641 rows). First queue built: 4 annotators, 2,618 items, full double annotation → **1,309 judgments/person (~1.5–2 days)**. |
| 2026-08-23 | A 5th volunteer became available → queue re-cut 5 ways (~1,047 each). Packages shipped as per-person zips. |
| 2026-08-25 | First calibration file returned. Review surfaced three systematic issues (§3) → instructions revised, packages rebuilt. |
| 2026-08-25 | Volunteer response rate low; deadlines not enforceable for unpaid lab volunteers → **coverage revised** (§4) to cut per-person load to ~664 judgments (~3–4 h). Token gift-card honorarium introduced. |
| 2026-08-25 | Pre-collection audit: calibration items found to overlap the main queue → exclusion implemented in `verification_stats.py`; registered counts corrected (3,322 shipped judgments); instruction wording fixed → packages rebuilt as LEAN v2.1 (CSVs byte-identical to v2); calibration answer key frozen (`verification/calibration_key.csv`, organizer-only). |
| 2026-08-25 | First returned calibration file identified as the **original** (08-22/23) calibration set — the rebuilt packages had silently re-drawn a different one. Row-level review of the return: 9 of 12 `invalid` labels trace to known §3 issues (plus one new: world-ambiguity, added as feedback point 4); 2–3 flag genuinely weak algorithmic partials (`List`, `World Jurassic Park`) — real signal the Tier-2 sample is designed to measure. |
| 2026-08-25 | **Package v2.2:** since no new-set package had been sent, the calibration file was reverted to the original 48-item set for all five annotators (main CSVs unchanged). Single shared calibration set; 27 in-queue ids excluded → **1,739 measured items / 3,268 judgments**. Answer key frozen for this set (`verification/calibration_key.csv`, organizer-only; 2 ref-invalid teaching items). |
| 2026-08-28 | All 5 warm-ups returned (one attribution pending). Graded against the key: judge-in-context 15/15 miss, typo intent 22/30 miss, casing naturalness 4/5 — all strict-direction. Guide updated with warm-up-mistakes box and **frozen**; **package v2.3** (per-annotator calibration filenames + `annotator` column; `identify_return.py` files returns automatically). Main CSVs still byte-identical to v2. |
| 2026-09-01 | First main file returned (E). Came back cp1252 from Excel's plain "CSV" save: 10 rows' non-Latin characters replaced by `?`, labels intact — repaired by restoring source columns from the shipped queue; `identify_return.py` gained encoding fallbacks and the guide now says "CSV UTF-8". |
| 2026-09-07 | A, B, D returned main files (UTF-8, complete). |
| 2026-09-09 | C returned main file (UTF-8, 664/664, 0 illegal values). **Collection complete: 5/5.** Five-annotator statistics computed; 55 items pending adjudication (worklist issued); release freeze tooling ready (§7). |
| 2026-09-09 | Adjudication of the 55 pending items by the first author (29 valid / 26 invalid). **Release frozen as v2.2:** 4,641 → 4,611 rows (20 reverted, 30 removed); manifest + decision log + anonymised verdicts released in `audit/verification/`. |
| 2026-09-22 | The rule-based tier's exception withdrawn (§9): its sampled items had been kept when judged invalid or unnatural and reported only as a rate; the same verdict rules now apply to every tier. 21 further questions removed (17 invalid, 4 unnatural — all from the 450-item rule-based sample; 8 of the 12 items only marked *awkward* stay, as in the other tiers). **Release frozen as v2.3:** 4,590 rows. Evaluation runs made on v2.2 are read against `benchmarks/removed_rows.jsonl` and scored on the v2.3 rows; nothing was re-run. |

## 2. Recruitment context

Annotators are graduate students from the authors' lab, participating
voluntarily. No institutional funding route was available on the project's
timeline (university disbursement approval exceeds the submission window), so
participation is acknowledged with a small personal gift-card honorarium on
completion. This constrained the design in a way worth stating plainly: **the
verification scope was set by annotator availability, not chosen freely.**

## 3. What the calibration round caught

One returned calibration file (48 items) surfaced three issues that would have
corrupted whole strata had annotation proceeded directly:

| issue | evidence | fix |
|---|---|---|
| **Typo intent not conveyed** — all 6 typo items marked `invalid` | annotator treated deliberate misspellings as errors to reject | guide now states typos are intentional, with a `valid`/`invalid` typo pair (`Pontiac→Pontiaac` vs `Muller→Miller`) |
| **Lowercase judged `unnatural`** — casing items marked unnatural | would have deleted the control stratum via the valid+unnatural rule | guide states casual lowercase typing counts as `natural` |
| **UTF-8 mangled by Excel** — `Dòngtíng Hú` displayed as `DÃ²ngtÃ­ng`, then judged `invalid` | annotator's Excel guessed the wrong encoding | shipped CSVs now carry a UTF-8 BOM (correct on double-click); guide recommends Google Sheets; return-file integrity check added |

**Lesson:** the calibration round paid for itself on the first returned file.
Any future iteration of this pipeline should treat calibration as
non-optional, and should ship BOM-marked CSVs from the start.

**Lesson (added 2026-08-25):** the calibration set was re-drawn as a side
effect of rebuilding the queue, so two package generations transiently
carried different calibration sets — which would have cost extra exclusions
(70 in-queue ids instead of 27). Caught before any new-set package was sent:
the shipped set was reverted to the original 48-item set for everyone
(package v2.2), restoring 43 items to measurement and giving all five
annotators an identical calibration set. Future iterations should **pin the
calibration set across queue rebuilds**, and ideally draw it **disjoint from
the measured queue** so feedback contamination requires no exclusions at all.

## 3b. Warm-up round 2 — all five annotators returned (2026-08-28)

All five warm-up files came back (the shared 48-item set; one annotator's
attribution pending sender confirmation). Graded against the frozen organizer
key (`verification/calibration_key.csv`):

| annotator | validity agreement with key | signature issues |
|---|---|---|
| A | 43/48 | judge-in-context (3), 2 typo rejections |
| B | 39/48 | all 6 typos rejected; judge-in-context (3); found a genuine source-grammar error (good catch) |
| C | 39/48 | all 6 typos rejected; judge-in-context (3); excellent evidence notes on 29 rows; self-fixed the encoding issue |
| D | 40/48 | judge-in-context (3); over-lenient on 2 degenerate partials; researched an acronym to a *different* referent |
| E* | 38/48 | all 6 typos rejected; judge-in-context (3); encoding victim (pre-BOM package) |

*attribution presumed by elimination; confirming via sender.

**Systematic findings (drove the guideline update, then freeze):**

1. **Judge-in-context failed 15/15** — every annotator rejected the three
   machine-verified partial forms (`Canada`, `Zoo`) as "ambiguous in the
   world". The guide now leads with a warm-up-mistakes box using these exact
   items, and states that every row already passed a DB-uniqueness check.
2. **Typo intent failed 22/30** — deliberate misspellings were treated as
   errors by 3 annotators fully and 2 partially.
3. **Re-casing naturalness** — lowercase/all-caps still judged
   awkward/unnatural by 4 of 5.
4. Disagreement is *directional*, not random: annotators are uniformly
   stricter than the guideline, which is the safe failure mode for a
   benchmark (false rejections cost coverage, not correctness).

Instructions updated accordingly (warm-up-mistakes box; rule 4 strengthened
with the DB-uniqueness statement) and **frozen**; packages rebuilt as **LEAN
v2.3**. From v2.3 the calibration file is per-annotator
(`2_calibration_50_X.csv` with an `annotator` id column), and
`scripts/identify_return.py` auto-identifies and files any returned CSV
(annotator column -> id-set match -> filename letter -> optional local name
map kept out of git), eliminating hand-renaming of email attachments.

## 4. Coverage revision (registered pre-annotation)

Reduced from 2,618 items / 5,236 judgments to **1,766 items / 3,322
judgments** (1,556 double + 210 single; ~664 per person):

- **LLM-proposed tier (916): full double-annotated census — unchanged.**
  Highest-risk tier and the basis of the anti-circularity argument; not
  reducible.
- **Attested/KB tier: census → 400-item stratified sample**, double-annotated.
  Validity is now *measured* (reported with a Wilson CI) rather than
  exhaustively cleaned; un-sampled attested rows remain in the release.
- **Algorithmic Tier-2: 650 → 450 items**, 240 double-annotated (evenly
  weighted across strategies so per-stratum IAA is computable), 210
  single-annotated. This tier estimates a rate and triggers no removals.
- **Calibration exclusion (pre-registered):** calibration items overlap the
  main queue; since annotators receive feedback on them before the main pass,
  `verification_stats.py` drops these ids from all reported measurements
  automatically. All five annotators share the single 48-item calibration set
  first shipped on 2026-08-22/23 (27 of its items sit in the current queue) →
  **1,739 measured items / 3,268 judgments**.

Comparable released benchmarks validate far less (e.g. VeriTaS, ACL 2026 Best
Resource Paper: ~816 human annotations for 25,000 claims), so the revised
design remains substantially above the field norm.

## 5. Email templates as sent

### 5.1 Initial invitation (lean scope + honorarium)

> **Subject: Short annotation task (~3 hours) — help wanted**
>
> Hi [NAME],
>
> I'm reaching out about a small annotation task for a research dataset. I've
> scoped it down so it's genuinely short: **~600 rows, about 3 hours total**,
> and you can spread it over several days.
>
> The task is simple — each row shows a name and a rewritten version of it, and
> you decide whether the rewrite still refers to the same thing. No background
> knowledge needed; the attached guide takes 5 minutes to read.
>
> As a thank-you, **I'll send a [AMOUNT] gift card to everyone who completes
> it**. It's a small token, but I really appreciate the help.
>
> If you're in, please start with the short warm-up file
> (`2_calibration_50.csv`, 48 rows, ~30 min) and send it back — I'll check it
> and send a few pointers before you do the main file.
>
> Would you be able to help? Even a quick "yes/no" reply helps me plan. Thanks!

### 5.2 Calibration feedback (sent after reviewing a returned warm-up file)

> **Subject: Re: Annotation — great work! A few notes before the main file**
>
> Hi [NAME],
>
> Thank you for the quick turnaround — your warm-up answers are genuinely good;
> you caught several subtle cases exactly right.
>
> Before you start the main file, **three quick adjustments**:
>
> 1. **Misspellings are intentional.** Many rewrites are deliberate typos
>    (`Pontiac → Pontiaac`) — that's the point of the dataset. Mark a typo
>    **`valid`** as long as you can still clearly tell what it refers to; it's
>    `invalid` only when the typo becomes a *different* real name
>    (`Muller → Miller`).
> 2. **Lowercase is natural.** Forms like `myers` or `france 2019` are how
>    people casually type — treat plain re-casing as **`natural`** unless the
>    sentence itself reads broken.
> 3. **Open the file in Google Sheets** (or Excel via *Data → From Text/CSV*,
>    UTF-8). Your file showed `Dòngtíng Hú` as garbled text — an encoding
>    issue; the refreshed files fix this.
> 4. **Judge within the question, not the world.** A shortened name like
>    "the 'Canada' tournament" is fine — inside this question it clearly
>    means one specific tournament, even though many things are called
>    "Canada" out in the world. Mark such rows **`valid`**. (Your calls on
>    rows like "List" were good — that one really is too little to go on.)
>
> Attached is the updated instruction sheet. Since you've already done the
> warm-up, **skip the calibration file in the new package and start directly
> with the main file.** Everything else — go ahead exactly as you did.

### 5.3 Follow-up for non-responders

> Hi [NAME], just checking in — were you able to open the annotation package I
> sent? The warm-up file only takes ~30 minutes. If your schedule doesn't allow
> it, no worries at all — just let me know so I can plan accordingly. Thanks!

## 6. Draft text for the paper

### Limitations (draft)

> **Verification coverage and annotator constraints.** Human verification was
> carried out by volunteer graduate annotators, acknowledged with a token
> honorarium; no funded annotation route was available within the submission
> timeline. Annotator availability, rather than a purely statistical argument,
> therefore set the verification scope. We prioritised accordingly: every
> LLM-proposed perturbation received a full double-annotated census, since that
> tier carries the highest corruption risk and underpins our claim that no
> model judges its own proposals. The attested knowledge-base tier was verified
> by a stratified sample rather than exhaustively, so its validity rate is
> estimated with a confidence interval and a small number of unverified
> attested items remain in the release; the purely algorithmic tier was
> likewise sampled, as it informs a rate estimate rather than any removal
> decision. A calibration round preceded annotation and materially changed the
> guidelines: it revealed that annotators initially rejected deliberate
> typographical perturbations and judged casual lowercase forms unnatural, both
> of which would have distorted entire strata. We report inter-annotator
> agreement per stratum and exclude calibration items from all reported
> measurements.

### Responsible NLP checklist notes

- **Annotators:** graduate students from the authors' lab; voluntary
  participation; token gift-card honorarium on completion; no institutional
  funding available within the timeline. Effective rate ≈ [AMOUNT] for ~3 hours.
- **Instructions given to annotators:** `docs/ANNOTATION_QUICKSTART.md`
  (reproduced in the appendix).
- **Calibration and guideline freeze:** documented in §3–§4 above; guidelines
  frozen before the measured annotation began.
- **Blinding:** annotators saw no provenance information (LLM / KB / rule) and
  no system outputs. They did see the intended perturbation *strategy*
  (typo/alias/…), which is required to apply the typo rule; strategy does not
  identify the generator, so the anti-circularity blinding is preserved.
- **Calibration handling:** the 48 calibration items also appear in the main
  queue; they are excluded from all reported measurements
  (`verification_stats.py` does this automatically). Organizer-only reference
  answers with rationales: `verification/calibration_key.csv` (frozen with the
  guidelines; **never shipped to annotators**).

## 7. Collection outcome (2026-09-09, pre-adjudication)

All five annotators returned complete main files (3,322 judgments; every
`validity` cell filled, zero illegal values). Statistics from
`scripts/verification_stats.py` on the 1,739 measured items (27 calibration
overlaps excluded as pre-registered):

| | value |
|---|---|
| double-annotated items | 1,524 |
| disagreements (→ adjudication) | 53 (3.5%) |
| still pending after agreed-unsure | **55** (LLM 34 · attested 9 · algorithmic 12) |
| Krippendorff's α (all items) | 0.354 |
| Gwet's AC1 (all items) | 0.964 |
| raw agreement, by tier | LLM 96.2% · attested 97.7% · algorithmic 95.8% |
| validity, by tier (Wilson 95% CI) | LLM 99.2% [98.3, 99.6] · attested 99.2% [97.7, 99.7] · algorithmic 97.2% [95.2, 98.4] |
| validity, by strategy | casing 100 · alias 99.8 · typo 99.0 · abbrev 98.7 · partial 94.5 |
| source-error flags | 5 |

**Reading the agreement figures.** α is deflated exactly as pre-registered in
the protocol: with 97–99% of items `valid`, chance agreement is already ~0.96,
so α sits far below the raw agreement it summarises. Two pairwise κ values are
0.000 (A–B, A–D) because one rater in each pair never left `valid` on the
co-rated items — κ is 0 by construction when a rater has no variance — and
B–D is 1.000 because the pair agreed on every item including a shared
rejection; pairs that include the stricter raters (C, E) land at 0.33–0.59.
Per-rater rejection rates: A 0.9%, B 0.9%, C 4.1%, D 2.3%, E 6.1%. All
disagreement is in one direction (a stricter rater rejecting), which is the
safe failure mode for a benchmark.

**Column misuse, logged not applied.** Annotator C filled `corrected_form` on
436 rows; 275 simply restate the canonical entity and 142 restate the
perturbed form, i.e. the column was read as "what is the correct name" rather
than "a better rewrite". The 19 substantive suggestions (e.g. `TAN → DNK` for
Denmark) are kept in `audit/verification/verdicts_long.csv`; none is applied,
because the pre-registered fix path requires a second verification pass that
did not take place.

**What happens to the release** (`scripts/freeze_verified_release.py`, rules
pre-registered 2026-08-22; policy choices stated here as the protocol
requires): `source_error` → removed in every tier; census-tier (LLM/attested)
`invalid` → reverted to the certified prior algorithmic form when one exists,
otherwise removed; algorithmic-tier `invalid` → kept, rate reported (§3: that
tier triggers no removals); `valid` + `unnatural` in the census tiers →
removed, `awkward` kept (`--naturalness drop-unnatural`); calibration items →
organizer reference answer (2 removed); items never sampled → kept. Dry run on
the current verdicts: 3 removed as invalid, 7 reverted, 5 source-error, 9
unnatural, 2 calibration; contingency rate 0.4% (threshold 20%). The freeze
refuses to run while 55 items await adjudication; the canonical v2.2 numbers
follow adjudication. Raw artifacts (blind key, anonymised per-item verdicts,
calibration set + reference answers, statistics) are in
`audit/verification/`.

**Adjudication and freeze (2026-09-09, final).** The 55 pending items were
adjudicated by the first author from the worklist (both raters' labels and
notes visible; no model involved): 29 valid / 26 invalid. The stricter rater
was upheld on 26 of the 55 splits, so the adjudicated LLM-tier validity
(97.2% [95.9, 98.1]) sits below the pre-adjudication 99.2% — the
pre-adjudication figure counted only unanimous verdicts and was therefore
optimistic; the final figure is the one to report. Freeze: 4,641 → 4,611
rows; 20 reverted to certified prior algorithmic forms, 30 removed (11
invalid, 5 source-error, 12 unnatural, 2 calibration). Final numbers and
policy statements: `docs/VERIFICATION_PROTOCOL.md` §5–6.

## 8. Adjudication outcome (2026-09-09)

Adjudication of the 55 unresolved items was completed on 2026-09-09 and the
verified release v2.2 (4,611 questions) was frozen the same day. The interim
(pre-adjudication) numbers in §7 above are superseded by the final figures in
`docs/VERIFICATION_PROTOCOL.md` §4–6.

## 9. Rule-based tier brought under the common rules (2026-09-22)

The 2026-08-22 rules treated the sampled rule-based edits as a measurement
only: an item the annotators judged invalid or unnatural stayed in the release
and entered a rate. While the paper's verification section was being written,
this was compared with how released benchmarks handle items their own
annotators reject (Dr.Spider, WikiSQL, SParC, CoSQL, HSCodeComp, ZOGRASCOPE:
removed or corrected; none keeps them), and the exception was withdrawn. The
freeze script now applies one rule table to every tier
(`docs/VERIFICATION_PROTOCOL.md` §5): a rejected rule-based edit is removed
(it has no verified replacement form to revert to), a valid edit that either
annotator marked *unnatural* is removed, *awkward* stays. Applied to the
existing labels this removed 21 questions (17 invalid: 4 rejected by both
annotators, 5 by adjudication, 8 by the single annotator who saw them; 4
unnatural) and changed nothing else — `audit/verification/decisions.csv`
differs from the v2.2 log in exactly those 21 rows plus 8 *awkward* rows whose
action is now `keep:valid`. No label, adjudication or agreement statistic
changed. The release is v2.3 (4,590 questions; CypherBench 2,090,
Mind-the-Query 1,217, ZOGRASCOPE 1,283). The freeze writes
`benchmarks/removed_rows.jsonl`, and every reader of evaluation records drops
those rows, so the experiments already run on v2.2 were re-read on the v2.3
rows rather than repeated (GPT-5.6, no grounding, 13 perturbed graphs:
538/4,611 → 535/4,590 execution accuracy).

