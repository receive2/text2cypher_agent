# Perturbed text-to-Cypher benchmarks

Entity-perturbation benchmarks built over three open-source text-to-Cypher
datasets — **CypherBench**, **MindTheQuery**, **ZOGRASCOPE**. Each natural-language
question has its entity mentions perturbed (the gold Cypher and the underlying
graph are unchanged), to test whether a system grounds the perturbed surface form
back to the canonical database value.

**Perturbation strategies:** `casing` · `typo` · `partial` · `abbrev` · `alias`.

> ⚠️ **Pre-audit snapshot** — shared for human verification; values may change
> once the audit completes.

## Layout (per dataset, `*_augmented_v2/`)

| file | what |
|---|---|
| `test.json` | the benchmark — one record per question: `nl` (perturbed question), `gold_cypher`, `graph`, `id`, `_aug_meta` (perturbation provenance). |
| `needs_verification.jsonl` | the **human-verification worklist** — items the auto-pipeline flagged as uncertain: `qid`, `graph`, `strategy`, `nl`, `from` → `to` (original → perturbed surface form), `source`. |
| `report.json` | per-graph augmentation statistics. |

## For auditors

- Verification instructions: [`../docs/REVIEW_GUIDE.md`](../docs/REVIEW_GUIDE.md)
- How the perturbations are produced: [`../docs/AUGMENTATION_METHODS.md`](../docs/AUGMENTATION_METHODS.md)
