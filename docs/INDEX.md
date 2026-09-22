# Docs index

Canonical documentation for the entity-perturbed text2cypher benchmark and
the CyANCHOR method.

## Benchmark & dataset (entity-perturbed text2cypher)

| doc | role |
|---|---|
| [DATASHEET.md](DATASHEET.md) | **Release-facing** dataset description — composition, perturbation taxonomy, intended use, limitations. Start here to *use* the benchmark. |
| [AUGMENTATION_METHODS.md](AUGMENTATION_METHODS.md) | **Methodology spec** (paper appendix) — exactly how each perturbation category is produced & validated. The authoritative "how it was built" reference. |
| [VERIFICATION_PROTOCOL.md](VERIFICATION_PROTOCOL.md) | **Human-verification methodology** — coverage by provenance class, double annotation, IAA, adjudication, reporting. |
| [ANNOTATION_QUICKSTART.md](ANNOTATION_QUICKSTART.md) | **Annotator guide as shipped** — the step-by-step instructions the five annotators worked from (frozen); column semantics in [ANNOTATION_SHEET.md](ANNOTATION_SHEET.md). |
| [GOLD_ERROR_AUDIT.md](GOLD_ERROR_AUDIT.md) | **Dataset-audit guide** — eval scores broken golds as failures (no assumptions); `audit_gold_errors.py` lists them + step-by-step fix/remove workflow. |
| [DIFFICULTY_DESIGN.md](DIFFICULTY_DESIGN.md) | Design-of-record for `eval/difficulty.py` (graded query-difficulty rubric). Status: implemented. |

## Method & results

| doc | role |
|---|---|
| [CYANCHOR_IMPLEMENTATION.md](CYANCHOR_IMPLEMENTATION.md) | **The method reference** for CyANCHOR — every stage traced to file/line (PLAN, EXECUTE's 3 retrieval arms + escalation + abstain judge, GENERATE injection, Cypher gen/error-retry/semantic repair, value-snap), the full config surface, safety/fairness invariants, and ablation axes. |
| [multi_agent_graphrag.md](multi_agent_graphrag.md) | **Baseline writeup** — the Multi-Agent GraphRAG baseline (`METHOD=graphrag`): no pre-grounding; generate → execute → evaluate → structural/semantic repair loop, validating node labels, property values **and pairwise edge patterns** with normalized-Levenshtein value replacement. |
| [report/](../report/) | **Current results** — one folder per generator model: `report/<model>/<Dataset>/<graph>.md` (per-graph tables), `<Dataset>/_summary.md` (pooled per dataset) and `SWEEP.md` (completeness verdict + every paper table); `report/gpt-4.1/` is the committed reference. |
| clean vs perturbed | `scripts/clean_vs_perturbed.py` writes `report/<model>/CLEAN_VS_PERTURBED.md` — the paired clean-vs-perturbed comparison for one model. The 2026-06 two-graph snapshot is kept in [archive/](archive/). |

## Infrastructure

| doc | role |
|---|---|
| [EXPERIMENT_HANDOUT.md](EXPERIMENT_HANDOUT.md) | **Runner checklist** — the only procedure for the model sweep (one generator model per person): prerequisites, dataset check, model choice, smoke test, full run, `--publish`. |
| [RUNNING_EXPERIMENTS.md](RUNNING_EXPERIMENTS.md) | **Harness reference (developers & coordinator)** — what happens when a cell runs, the guards, config knobs, where results land, reports, publishing the artifact set, pre-flight words. Not a procedure. |
| [GRAPHS.md](GRAPHS.md) | Live reference for the deployed Neo4j graphs (labels, rel types, ports). |
