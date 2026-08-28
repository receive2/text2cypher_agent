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
