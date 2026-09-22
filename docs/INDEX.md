# Docs index

## Dataset release — what a reviewer or user of the benchmark reads

| doc | role |
|---|---|
| [../benchmarks/README.md](../benchmarks/README.md) | Entry point: files, row counts, `verify.py`. |
| [DATASHEET.md](DATASHEET.md) | The datasheet: composition, provenance, how the questions were produced, verification outcome, curation history, limitations, files. Every number is script-generated. |
| [AUGMENTATION_METHODS.md](AUGMENTATION_METHODS.md) | Paper appendix: exactly how each perturbation strategy is generated and gated. |
| [VERIFICATION_PROTOCOL.md](VERIFICATION_PROTOCOL.md) | How the data was verified by human annotators: coverage, labels, procedure, agreement, verdict rules, results, released artifacts. |
| [ANNOTATION_QUICKSTART.md](ANNOTATION_QUICKSTART.md) | The guide the five annotators worked from, frozen as shipped. |
| [LLM_USE_DISCLOSURE.md](LLM_USE_DISCLOSURE.md) | The role of LLMs in constructing the data (paper section + checklist answers). |

Released data artifacts: `benchmarks/` (questions, manifest, hashes) and
`audit/verification/` (verdicts, keys, statistics); `audit/gold_executability.json`.

## Method and results

| doc | role |
|---|---|
| [CYANCHOR_IMPLEMENTATION.md](CYANCHOR_IMPLEMENTATION.md) | The method reference for CyANCHOR, every stage traced to code. |
| [multi_agent_graphrag.md](multi_agent_graphrag.md) | The Multi-Agent GraphRAG baseline. |
| [../report/](../report/) | Results, one folder per generator model; `report/gpt-4.1/` is the committed reference. |

## Running experiments

| doc | role |
|---|---|
| [EXPERIMENT_HANDOUT.md](EXPERIMENT_HANDOUT.md) | The runner checklist for the model sweep — the only procedure. |
| [RUNNING_EXPERIMENTS.md](RUNNING_EXPERIMENTS.md) | Harness reference for developers and the coordinator. |
| [GRAPHS.md](GRAPHS.md) | The deployed Neo4j graphs (labels, relationship types, ports). |

## Engineering design records

| doc | role |
|---|---|
| [DIFFICULTY_DESIGN.md](DIFFICULTY_DESIGN.md) | Design of the query-difficulty classifier (`eval/difficulty.py`). |
| [GOLD_ERROR_AUDIT.md](GOLD_ERROR_AUDIT.md) | Why the harness scores non-executing golds as failures, and the audit tooling. |

## Archive

Superseded documents and the day-by-day records are kept under
[archive/](archive/) — among them the annotation campaign log
(`archive/ANNOTATION_PROCESS_LOG.md`) and the column-level annotation sheet
(`archive/ANNOTATION_SHEET_2026-08.md`).
