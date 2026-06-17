# Docs index

Current, canonical documents. Superseded / historical drafts live in
[`archive/`](archive/) (see the bottom of this file).

## Benchmark & dataset (entity-perturbed text2cypher)

| doc | role |
|---|---|
| [DATASHEET.md](DATASHEET.md) | **Release-facing** dataset description — composition, perturbation taxonomy, intended use, limitations. Start here to *use* the benchmark. |
| [AUGMENTATION_METHODS.md](AUGMENTATION_METHODS.md) | **Methodology spec** (paper appendix) — exactly how each perturbation category is produced & validated. The authoritative "how it was built" reference. |
| [DATASET_WORK.md](DATASET_WORK.md) | **Internal master narrative** — the decision log / running record of the augmentation work (audit findings, design principles, status). |
| [REVIEW_GUIDE.md](REVIEW_GUIDE.md) | **Human-verification instructions** — handed to annotators verifying perturbation batches. |

> Which augmentation doc is which? **AUGMENTATION_METHODS.md** is the final
> methodology. The old planning draft (`AUGMENTATION_REDESIGN.md`, "proposal
> pending sign-off") is superseded by it and now lives in `archive/`.

## Evaluation

| doc | role |
|---|---|
| [DIFFICULTY_REDESIGN.md](DIFFICULTY_REDESIGN.md) | Design-of-record for `eval/difficulty.py` (graded query-difficulty rubric). Status: implemented. |
| [NER_ABLATION_HEAD_BASELINE.md](NER_ABLATION_HEAD_BASELINE.md) | Clean HEAD 3-mode ablation (`full` / `node_only` / `no_ner`) on movie · geography · politics. Supersedes the gated-integration-era `NER_ABLATION_REPORT.md`. |
| [NER_GROUNDING_RETENTION_STUDY.md](NER_GROUNDING_RETENTION_STUDY.md) | Funnel diagnosis + tool-result **backfill** fix + retrieval-mode ablation (fuzzy / vector / RRF / cascade) on flight_accident. |

## Infrastructure

| doc | role |
|---|---|
| [GRAPHS.md](GRAPHS.md) | Live reference for the deployed Neo4j graphs (labels, rel types, ports). |
| [DEPLOY_LOG.md](DEPLOY_LOG.md) | GCP VM / Neo4j deployment record. |

## archive/

Superseded or rejected drafts, kept for provenance:

| doc | why archived |
|---|---|
| [archive/AUGMENTATION_REDESIGN.md](archive/AUGMENTATION_REDESIGN.md) | Original redesign proposal; superseded by `AUGMENTATION_METHODS.md` (final) + the implemented pipeline. |
| [archive/NER_ABLATION_REPORT.md](archive/NER_ABLATION_REPORT.md) | Gated-integration-era ablation numbers; superseded by `NER_ABLATION_HEAD_BASELINE.md`. |
| [archive/NER_IMPROVEMENT_PROPOSAL.md](archive/NER_IMPROVEMENT_PROPOSAL.md) | Gated-integration / C-pruning proposal; the direction was validated to break movie and **rejected** (see the HEAD-baseline study). |
