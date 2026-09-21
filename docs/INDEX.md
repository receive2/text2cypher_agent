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
| [report/](../report/) | **Current results** — per-graph entity-perturbation tables at `report/<dataset>/<graph>.md` (Overall + by perturbation strategy + by difficulty, EA & PSJS) over the 5 methods (No Val Link · FCAV · ReAct · GraphRAG · CyANCHOR), plus per-dataset cross-graph summaries. |
| [CLEAN_VS_PERTURBED.md](CLEAN_VS_PERTURBED.md) | **Robustness snapshot** — clean (original) vs entity-perturbed EA/PSJS for all 5 methods on CypherBench `flight_accident` + Mind-the-Query `bloom50`. Clean benchmarks overestimate robustness; CyANCHOR loses the least under perturbation (highest "retained %"). |

## Infrastructure

| doc | role |
|---|---|
| [RUNNING_EXPERIMENTS.md](RUNNING_EXPERIMENTS.md) | **Operational guide** — how to run multi-dataset / multi-graph eval batches safely. The single-live-tree swap trap, the `verify_setup.py` pre-flight, and how to recognise + fix a contaminated archive. Read before running a batch. |
| [GRAPHS.md](GRAPHS.md) | Live reference for the deployed Neo4j graphs (labels, rel types, ports). |
