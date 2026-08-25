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
| 2026-08-25 | First returned calibration file identified as the **legacy** calibration set (retired 08-22/23 packages). 27 legacy items overlap the current queue (26 identical) → exclusion extended to the union of both calibration rounds (91 ids, 70 in-queue) → **1,696 measured items / 3,191 judgments**. Row-level review of the return: 9 of 12 `invalid` labels trace to the three known §3 issues; 2–3 flag genuinely weak algorithmic partials (`List`, `World Jurassic Park`) — real signal the Tier-2 sample is designed to measure. |

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
effect of rebuilding the queue, so the two package generations carried
different calibration sets — costing extra exclusions (70 in-queue ids
instead of 27). Future iterations should **pin the calibration set across
queue rebuilds**, and ideally draw it **disjoint from the measured queue** so
feedback contamination requires no exclusions at all. (Kept as-is here:
1,696 measured items retain per-stratum IAA power, and a third same-day
package rebuild carried more version-confusion risk than the ~2.4% gain.)

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
  automatically. The exclusion covers **both** the current 48-item set and the
  48-item legacy set from the retired 2026-08-22/23 packages (all five
  annotators received those packages; 27 legacy items sit in the current
  queue, 26 with the identical perturbation) → union 91 ids, 70 in-queue →
  **1,696 measured items / 3,191 judgments**.

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
