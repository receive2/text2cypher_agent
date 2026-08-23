# Annotation Task — Step-by-Step Guide

## 快速上手(中文摘要,详细规则见下方英文部分)

你的任务:表格里每一行有一个「原名字」和一个「改写后的名字」。判断改写后是否还指同一个东西,填 3 个格子。全部数据是英文。

**流程(共 4 步):**
1. 读完本页(约 5 分钟);
2. 打开 `2_calibration_50.csv`,填完 48 行(约 30 分钟),发回给组织者;
3. 参加一次简短的线上对齐会(组织者安排);
4. 会后打开 `verification_annotator_X.csv`(约 1,000 行),**独立**填完(共约 5–8 小时,可以分几天做),发回。

每行平均 20–40 秒。规则详见下文,拿不准的判法以对齐会结论为准。

---

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

**Step 1.** Open the CSV in Excel / Google Sheets / Numbers.

**Step 2.** Do `2_calibration_50.csv` first (48 rows). Send it back. Wait for
the short alignment call before starting the big file.

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

Three judging rules:

1. **A quick web search is allowed and encouraged** for nicknames,
   abbreviations, and drug names you don't recognize.
2. **If you can't confirm a nickname/name is real → `invalid`.** When torn
   between valid and invalid, choose `invalid`.
3. **Judge within the question's context only.** Don't mark `invalid` just
   because the name could mean other things elsewhere in the world (many
   airlines have a "Flight 383" — that alone is not a reason to reject).

### Cell 2 — `naturalness`

Type exactly one of: `natural` / `awkward` / `unnatural` (lowercase).

| type | when |
|---|---|
| `natural` | a real person could write this in a question |
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
