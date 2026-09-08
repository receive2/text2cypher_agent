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

These files are the **v2.1 freeze (2026-08-22): 4,641 perturbed questions**.
Experiment results can only be pooled across people if everyone ran on this
exact release, so verify first — the check takes a second and exits non-zero on
any mismatch.

> **If you have an older copy, discard it.** A pre-2026-09 checkout of this
> directory carried the *pre-curation* set (4,875 rows); 234 rows were removed
> or repaired during curation, so numbers from that copy are not comparable
> with anything produced now.

Human verification of the release is in progress; per-item verdicts will drop
`invalid` / source-error rows. That does **not** require re-running experiments:
keep your `records.jsonl` and the metrics are re-derived on the verified subset
with `scripts/rescore_on_verified.py`.

## Layout (per dataset, `*_augmented_v2/`)

| file | what |
|---|---|
| `test.json` | the benchmark — one record per question: `nl` (perturbed question), `gold_cypher`, `graph`, `id`, `_aug_meta` (perturbation provenance). |
| `needs_verification.jsonl` | the **human-verification worklist** — items the auto-pipeline flagged as uncertain: `qid`, `graph`, `strategy`, `nl`, `from` → `to` (original → perturbed surface form), `source`. |
| `test.probed.json` | the same records plus `grounding_probe` difficulty signals (`exact_ci`, `damerau`, `substring`, …) used for the difficulty breakdown. |
| `report.json` | per-graph augmentation statistics. |
| `verify.py` | release check (canonical sha256 per file, key-order independent). |

**Row counts (v2.1):** cypherbench 2,115 · mindthequery 1,227 · zograscope 1,299
= **4,641**.

**Provenance.** Every perturbation is a deterministic function of a frozen
decision manifest; `scripts/rebuild_from_manifest.py` re-derives all 4,641
questions from it and checks the same six canonical hashes.

## For auditors

- Verification instructions: [`../docs/REVIEW_GUIDE.md`](../docs/REVIEW_GUIDE.md)
- How the perturbations are produced: [`../docs/AUGMENTATION_METHODS.md`](../docs/AUGMENTATION_METHODS.md)
