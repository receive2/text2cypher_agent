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

These files are the **v2.2 verified release (2026-09-09): 4,611 perturbed
questions**. Experiment results can only be pooled across people if everyone
ran on this exact release, so verify first — the check takes a second and exits
non-zero on any mismatch.

> **If you have an older copy, discard it.** A checkout from before 2026-09
> carried the *pre-curation* set (4,875 rows); one from 2026-08-22 … 2026-09-09
> carried the *pre-verification* v2.1 set (4,641 rows). Numbers from those
> copies are not comparable with anything produced now. Runs made on v2.1 can
> be re-derived on the released rows without re-running:
> `scripts/rescore_on_verified.py --decisions audit/verification/decisions.csv`.

**Human verification is complete.** Five annotators double-labelled every
LLM-proposed edit (916, full census) and stratified samples of the other tiers;
30 rows were removed and 20 reverted to a certified earlier form (per-row
decisions: `audit/verification/decisions.csv`; statistics and protocol:
`docs/VERIFICATION_PROTOCOL.md`, `docs/DATASHEET.md` §7).

## Layout (per dataset, `*_augmented_v2/`)

| file | what |
|---|---|
| `test.json` | the benchmark — one record per question: `nl` (perturbed question), `gold_cypher`, `graph`, `id`, `_aug_meta` (perturbation provenance). |
| `needs_verification.jsonl` | historical: the worklist the human verification was drawn from (`qid`, `graph`, `strategy`, `nl`, `from` → `to`, `source`); the verdicts live in `audit/verification/`. |
| `test.probed.json` | the same records plus `grounding_probe` difficulty signals (`exact_ci`, `damerau`, `substring`, …) used for the difficulty breakdown. |
| `report.json` | per-graph augmentation statistics. |
| `verify.py` | release check (canonical sha256 per file, key-order independent). |

**Row counts (v2.2):** cypherbench 2,099 · mindthequery 1,222 · zograscope 1,290
= **4,611**.

**Provenance.** Every perturbation is a deterministic function of the frozen
decision manifest `release_manifest_v2.2.jsonl` (in this directory);
`scripts/rebuild_from_manifest.py` re-derives all 4,611 questions from it and
checks the same six canonical hashes.

## For auditors

- Verification instructions: [`../docs/REVIEW_GUIDE.md`](../docs/REVIEW_GUIDE.md)
- How the perturbations are produced: [`../docs/AUGMENTATION_METHODS.md`](../docs/AUGMENTATION_METHODS.md)
