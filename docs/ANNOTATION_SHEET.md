# Annotation sheet — entity-perturbation verification (blind, release-grade)

Per-row instructions for the **blind, double-annotated** verification queue
(`verification/verification_annotator_<X>.csv`). This is the release-grade
companion to `docs/VERIFICATION_PROTOCOL.md`; it supersedes the older
keep/fix/drop `docs/REVIEW_GUIDE.md` **for these CSVs** — here you record three
independent primitive labels and the keep/fix/drop action is *derived*
downstream by `scripts/verification_stats.py`. Fill the columns exactly as
named; the stats tool matches these value vocabularies literally.

## What each row is

Each test question mentions an entity stored in a graph database. We rewrote the
mention to a realistic variant (abbreviation, nickname, shortened form, typo,
re-casing) **while leaving the gold answer query unchanged** — the gold uses the
*canonical* stored value. The benchmark is only valid if the rewrite still points
at the **same, unique** database entity. You are the check on that.

You do **not** see how the rewrite was produced (LLM / knowledge-base / rule) —
this is deliberate. Judge the surface forms only.

Columns you read: `original_entity` (what the DB stores), `perturbed_form` (the
rewrite you judge), `property` (`Label.prop` context), `augmented_question` (the
full question with the rewrite spliced in).

## What has already been machine-checked (so you don't have to)

Every row in your sheet has **already passed automated database checks**: the
rewritten form does not clash with any other stored value, and (for shortened
forms) it maps back to exactly one stored value. You cannot see the database —
and you don't need to. Two practical consequences:

- **Do not fail an item for real-world ambiguity.** "Flight 383" exists at
  many airlines in the real world, but if it appears in your sheet, the
  database it queries contains exactly one — the item is fine on that account.
  Judge whether the form *means the same entity in this question's context*,
  not whether it is globally unique.
- **Your job is the part machines can't do**: is this nickname/abbreviation
  a real, attested way to refer to this entity (not invented)? Does the
  question still read like something a person would write? When you cannot
  verify a nickname is real, mark it `invalid`.

## Fill these three labels (each independent)

**1. `validity`** — *the decisive one.* Does `perturbed_form` still refer to the
**same, unique** entity as `original_entity`?

| value | when |
|---|---|
| `valid` | it unambiguously means the same single entity |
| `invalid` | it names a **different** entity, a **sibling** in the same family, **or** is **ambiguous** (could resolve to several entities) |
| `unsure` | you genuinely cannot decide (goes to adjudication) |

- ✅ `Los Angeles Lakers` → `LAL` = `valid` (standard abbreviation, same team).
- ❌ `Central Division` → `Midwest Division` = `invalid` (different division).
- ❌ `All-NBA Team` → `NBA All-Star Team` = `invalid` (different award).
- ❌ `Wagner` (a person surname) → `the Wagner Group` = `invalid` (different real-world entity).

When torn between `valid` and `invalid`, prefer `invalid` — a corrupted label
hurts the benchmark more than a dropped row.

**2. `naturalness`** — would a real user plausibly write it in a question?

| value | when |
|---|---|
| `natural` | a real person could type this (`the Lakers`, `Britain`, `two guard`) |
| `awkward` | understandable but stilted (`the CHI` for the Bulls — a standings code in prose) |
| `unnatural` | no one would write it |

Naturalness does **not** override validity — a form can be `valid` + `awkward`.

**3. `source_error`** — is the *source dataset's own gold already wrong here*,
independent of our perturbation? (e.g. the original question/gold mismatch.)

| value | when |
|---|---|
| `no` | default |
| `yes` | the underlying item is broken regardless of the rewrite |

`yes` rows are **excluded** from the release and are **not** counted as
perturbation corruption — flag them, don't try to fix them.

## Optional columns

- `corrected_form` — if the rewrite is *almost* right (right idea, awkward/slightly
  off form) and a clean fix exists, put the better surface form here. Leave blank
  otherwise.
- `notes` — anything you want to flag (ambiguity, a suspected source bug, a
  strategy that keeps producing bad forms).

## Rules of the road

- **Independent & silent.** Do not discuss items with other annotators during
  annotation. Your file is yours alone.
- **Fill every row** you are assigned. Blank `validity` is treated as missing,
  not as `valid`.
- **Value spelling matters.** Use exactly `valid`/`invalid`/`unsure`,
  `natural`/`awkward`/`unnatural`, `yes`/`no`. The stats tool is literal.
- **Calibration first.** Everyone labels the shared `calibration_50.csv` first;
  we discuss disagreements and freeze this guideline before the real queue.

## What happens to your labels

Each item is labeled by **two** annotators. `scripts/verification_stats.py`
computes inter-annotator agreement (Krippendorff's α, Cohen's κ), resolves
disagreements via adjudication, drops `invalid`/`source_error`, and reports the
validity rate with a 95% CI per stratum and the final retained N — the numbers
that go in the paper's datasheet.
