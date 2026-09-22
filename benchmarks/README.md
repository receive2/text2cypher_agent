# Perturbed text-to-Cypher benchmarks

Entity-perturbation benchmarks built over three open-source text-to-Cypher
datasets — **CypherBench**, **MindTheQuery**, **ZOGRASCOPE**. Each natural-language
question has its entity mentions perturbed (the gold Cypher and the underlying
graph are unchanged), to test whether a system grounds the perturbed surface form
back to the canonical database value.

**Perturbation strategies:** `casing` · `typo` · `partial` · `abbrev` · `alias`.

## ⚠️ Before you run anything

```bash
python benchmarks/verify.py     # must print VERIFIED
```

These files are the **v2.3 verified release (2026-09-22): 4,590 perturbed
questions**. Experiment results can only be pooled across people if everyone
ran on this exact release, so verify first — the check takes a second and exits
non-zero on any mismatch.

> **If you have an older copy, discard it.** A checkout from before 2026-09
> carried the *pre-curation* set (4,875 rows); one from 2026-08-22 … 2026-09-09
> carried the *pre-verification* v2.1 set (4,641 rows); one from 2026-09-09 …
> 2026-09-22 carried v2.2 (4,611 rows). Numbers from those copies are not
> comparable with anything produced now, with one exception: **runs made on
> v2.2 stay valid** — v2.3 only removes 21 of its rows, and every reader of
> evaluation records (the sweep driver, the report scripts) drops those rows
> (`removed_rows.jsonl`), so such runs are scored on exactly the released
> questions. Runs made on v2.1 can be re-derived the same way:
> `scripts/rescore_on_verified.py --decisions audit/verification/decisions.csv`.

**Human verification is complete.** Five annotators double-labelled every
LLM-proposed edit (916, full census) and stratified samples of the other tiers;
51 rows were removed and 20 reverted to a certified earlier form (per-row
decisions: `audit/verification/decisions.csv`; statistics and protocol:
`docs/VERIFICATION_PROTOCOL.md`, `docs/DATASHEET.md` §4).

## Layout (per dataset, `*_augmented_v2/`)

| file | what |
|---|---|
| `test.json` | the benchmark — one record per question: `nl` (perturbed question), `gold_cypher`, `graph`, `id`, `_aug_meta` (perturbation provenance). |
| `needs_verification.jsonl` | historical: the worklist the human verification was drawn from (`qid`, `graph`, `strategy`, `nl`, `from` → `to`, `source`); the verdicts live in `audit/verification/`. |
| `test.probed.json` | the same records plus `grounding_probe` difficulty signals (`exact_ci`, `damerau`, `substring`, …) used for the difficulty breakdown. |
| `report.json` | per-graph augmentation statistics. |
| `verify.py` | release check (canonical sha256 per file, key-order independent). |
| `removed_rows.jsonl` | the 51 questions verification removed, as they stood before verification (graph, id, text, action) — readers of evaluation records drop these rows. |

**Row counts (v2.3):** cypherbench 2,090 · mindthequery 1,217 · zograscope 1,283
= **4,590**.

**Provenance.** Every perturbation is a deterministic function of the frozen
decision manifest `release_manifest_v2.3.jsonl` (in this directory);
`scripts/rebuild_from_manifest.py` re-derives all 4,590 questions from it and
checks the same six canonical hashes.

## For auditors

- How the perturbations were verified: [`../docs/VERIFICATION_PROTOCOL.md`](../docs/VERIFICATION_PROTOCOL.md); the guide annotators worked from: [`../docs/ANNOTATION_QUICKSTART.md`](../docs/ANNOTATION_QUICKSTART.md)
- How the perturbations are produced: [`../docs/AUGMENTATION_METHODS.md`](../docs/AUGMENTATION_METHODS.md)
