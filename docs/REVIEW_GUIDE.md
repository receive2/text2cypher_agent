# Human Verification Guide — Augmented text2cypher Benchmark

Thanks for helping verify a batch of entity perturbations. This should take a
few seconds per row. Please read this once before starting.

## Background (1 paragraph)

We are building an open-source benchmark for text-to-Cypher question answering.
Each test question mentions an entity that exists in a graph database (e.g. a
team, a drug, a place). Real users rarely type the entity exactly as the
database stores it — they abbreviate it, nickname it, shorten it, or mistype
it. So we automatically rewrite the entity mention in each question to a
realistic variant, keeping the gold query (the correct answer) unchanged. Most
rewrites are produced by deterministic rules and trusted automatically. **The
rows in your file are the subset proposed by an LLM**, which is reliable for
common cases but sometimes wrong — so a human (you) confirms them.

## Your task

For each row, fill in **`review_verdict`** with one of:

| verdict | when | also fill |
|---|---|---|
| `keep` | the perturbed form is valid AND natural | — |
| `fix`  | right idea, wrong/awkward form | put the corrected form in `review_corrected_to` |
| `drop` | invalid — can't be salvaged | — |

Use **`review_notes`** for anything you want to flag.

## The two criteria

**1. Validity (most important): does the perturbed form still refer to the
SAME, UNIQUE entity as the original?**
The original entity is in the `original_entity` column. The rewrite is in
`perturbed_form`. If the perturbed form could mean a *different* entity, or a
*different* member of the same family, it is invalid.

- ✅ `Los Angeles Lakers` → `LAL` — same team, just the standard abbreviation.
- ❌ `Central Division` → `Midwest Division` — **a different division.** → `drop`
- ❌ `All-NBA Team` → `NBA All-Star Team` — **a different award.** → `drop`

**2. Naturalness: would a real person plausibly write it in a question?**

- ✅ `the Lakers`, `LAL`, `Britain`, `two guard` (slang for shooting guard).
- ⚠️ `the CHI` (for Chicago Bulls) — a standings code, awkward in a sentence.
  If you think no one would write it, `drop`; if a tweak makes it natural
  (e.g. `the Bulls`), `fix` with the better form.
- ⚠️ Invented nicknames for obscure people (e.g. `Walt Hazzard` → `Walt the
  Wizard`): if you can't confirm it's a real, recognized nickname, `drop`.

When in doubt about validity, prefer `drop` — a wrong label hurts the benchmark
more than a missing row.

## Reading a row

- `original_entity` — what the database actually stores (the ground truth).
- `perturbed_form` — the LLM's proposed rewrite (what you're judging).
- `augmented_question` — the full question with the rewrite spliced in; read it
  to judge naturalness in context.
- `strategy` — `abbrev` (acronym/short form), `alias` (nickname/other name),
  `partial` (dropped words). `source` is `llm` for every row here.

## A few worked examples

| original_entity | perturbed_form | verdict | corrected_to | why |
|---|---|---|---|---|
| Golden State Warriors | GSW | keep | | standard, unambiguous |
| shooting guard | two guard | keep | | real basketball slang |
| Chicago Bulls | CHI | fix | the Bulls | tricode is awkward in prose |
| Central Division | Midwest Division | drop | | different division |
| Walt Hazzard | Walt the Wizard | drop | | unverifiable invented nickname |
| Petyr Baelish | Baelish | keep | | natural surname shortening |

## Returning it

Fill in the three `review_*` columns and send the CSV back (same format). You
don't need to touch any other column. Rows you mark `drop` will be removed;
`fix` rows will use your `review_corrected_to` value.

If a sizable fraction of one strategy is `drop`, mention it — that tells us to
tighten that strategy's generation rather than rely on review.
