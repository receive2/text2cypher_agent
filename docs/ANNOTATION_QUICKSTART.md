# Annotation Task — Step-by-Step Guide

## What you will do

Each row of the spreadsheet shows:

| column | what it is |
|---|---|
| `original_entity` | a name stored in a database |
| `perturbed_form` | a rewritten version of that name — **this is what you judge** |
| `augmented_question` | the question sentence, with the rewritten name inside it |
| `property` | where the name lives (e.g. `Team.name`) — context only, just look |

Your job, for every row: **decide whether the rewritten name still refers to
the same thing**, then fill in three cells. That's the whole task.

## Steps

**Step 1.** Open the CSV — **Google Sheets is recommended** (it reads the
file correctly by default). If you use Excel: don't double-click the file;
use *Data → From Text/CSV* and pick **UTF-8**, otherwise accented names
(e.g. `Dòngtíng Hú`, `Caché`) will display as garbage like `DÃ²ngtÃ­ng`
and be impossible to judge.

**Step 2.** Do `2_calibration_50.csv` first (48 rows). Send it back and wait
for my short feedback email before starting the big file.

**Step 3.** For each row, read `original_entity`, `perturbed_form`, and the
`augmented_question` sentence. Then fill:

### Cell 1 — `validity` (the important one)

Type exactly one of: `valid` / `invalid` / `unsure` (lowercase).

| type | when |
|---|---|
| `valid` | the rewritten name clearly means the **same single thing** |
| `invalid` | it names a **different** thing, or a different member of the same family, or you **cannot confirm** it's a real way to refer to this thing |
| `unsure` | you genuinely cannot decide either way |

Examples:

| original | rewritten | answer | why |
|---|---|---|---|
| Los Angeles Lakers | LAL | `valid` | standard abbreviation, same team |
| United Kingdom | Britain | `valid` | real common name, same country |
| Central Division | Midwest Division | `invalid` | a **different** division |
| George Lehmann | Stormin' George | `invalid` | can't confirm this nickname is real |
| CLOZAPINE | Clozaril | `valid` | real brand name of this drug (quick web search confirms) |
| Pontiac | Pontiaac | `valid` | an intentional typo — still clearly the same thing |
| Muller | Miller | `invalid` | the typo turned it into a *different* real name |

Four judging rules:

1. **A quick web search is allowed and encouraged** for nicknames,
   abbreviations, and drug names you don't recognize.
2. **If you can't confirm a nickname/name is real → `invalid`.** When torn
   between valid and invalid, choose `invalid`.
3. **Misspellings are intentional.** Many rewrites are deliberate typos
   (`Pontiac` → `Pontiaac`). A typo is `valid` as long as you can still
   clearly tell what it refers to; it is `invalid` only when the typo turns
   it into a *different* real name (`Muller` → `Miller`).
4. **Judge within the question's context only.** Don't mark `invalid` just
   because the name could mean other things elsewhere in the world (many
   airlines have a "Flight 383" — that alone is not a reason to reject).

### Cell 2 — `naturalness`

Type exactly one of: `natural` / `awkward` / `unnatural` (lowercase).

| type | when |
|---|---|
| `natural` | a real person could write this in a question — incl. casual all-lowercase typing (`myers`, `france 2019`) and typos |
| `awkward` | understandable but stilted or odd in a sentence |
| `unnatural` | no one would write this; or the sentence reads broken |

### Cell 3 — `source_error` (rare)

Type `no` (almost always) or `yes` — `yes` only if the **question itself** is
broken regardless of the rewrite (nonsense question, gibberish entity).

### Optional cells

- `corrected_form`: if the rewrite is *almost* right and you know the better
  form, write it here (e.g. rewrite "the CHI" → you suggest "the Bulls").
- `notes`: anything you want to flag.

**Step 4.** When done: save as **CSV**, **keep the original file name**, send
it back.

## Rules

- **Work alone.** Do not discuss rows with the other annotators until the
  task is finished.
- **Fill every row.** An empty `validity` cell counts as missing, not as valid.
- **Exact spelling, lowercase.** Only the listed words are accepted
  (`valid`, not `Valid` / `V` / `ok`).
- Don't edit any other columns.

Expected pace: 20–40 seconds per row. Questions about the task → ask the
organizer, not the other annotators.
