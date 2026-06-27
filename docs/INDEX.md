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

## Method & results (current)

| doc | role |
|---|---|
| [plan_exec_hybrid.md](plan_exec_hybrid.md) | **Method writeup** — how *CyANCHOR* (`METHOD=cyanchor`; lives in `plan_exec.py`), the shipped value-linking grounder, works end to end (PLAN → EXECUTE with the LLM corrective loop → GENERATE). |
| [CYANCHOR_IMPLEMENTATION.md](CYANCHOR_IMPLEMENTATION.md) | **Code-level implementation reference** for CyANCHOR — every stage traced to file/line (PLAN, EXECUTE's 3 retrieval arms + escalation + abstain judge, GENERATE injection, Cypher gen/error-retry/semantic repair, value-snap), the full config surface, safety/fairness invariants, and ablation axes. Read alongside the conceptual writeup when working in the code. |
| [multi_agent_graphrag.md](multi_agent_graphrag.md) | **Method writeup** — the Multi-Agent GraphRAG baseline (`METHOD=graphrag`): no pre-grounding; generate → execute → evaluate → structural/semantic repair loop, validating node labels, property values **and pairwise edge patterns** with normalized-Levenshtein value replacement. |
| [report/](../report/) | **Current results** — per-graph entity-perturbation ablations at `report/<dataset>/<graph>.md` (flight format: Overall + by perturbation strategy + by difficulty, EA & PSJS) over the 5 methods (No Val Link · FCAV · ReAct · GraphRAG · CyANCHOR), plus per-dataset cross-graph summaries. CyANCHOR leads on every clean-schema graph. |
| [CLEAN_VS_PERTURBED.md](CLEAN_VS_PERTURBED.md) | **Robustness snapshot** — clean (original) vs entity-perturbed EA/PSJS for all 5 methods on CypherBench `flight_accident` + Mind-the-Query `bloom50`. Clean benchmarks overestimate robustness; CyANCHOR loses the least under perturbation (highest "retained %"). |
| [GOLD_ERROR_AUDIT.md](GOLD_ERROR_AUDIT.md) | **Dataset-audit guide** — eval scores broken golds as failures (no assumptions); `audit_gold_errors.py` lists them + step-by-step fix/remove workflow. |
| [DIFFICULTY_DESIGN.md](DIFFICULTY_DESIGN.md) | Design-of-record for `eval/difficulty.py` (graded query-difficulty rubric). Status: implemented. |

## Earlier studies (pre-Plan&Exec; ReAct-agent era)

| doc | role |
|---|---|
| [NER_GROUNDING_RETENTION_STUDY.md](NER_GROUNDING_RETENTION_STUDY.md) | Funnel diagnosis of the ReAct agent (retrieval recovers ~74%, only ~23% survives) — the loss that motivated Plan&Exec; plus the tool-result backfill fix and the fuzzy/vector/RRF/cascade retrieval ablation. |
| [NER_ABLATION_HEAD_BASELINE.md](NER_ABLATION_HEAD_BASELINE.md) | ReAct-agent relation-tool ablation (now *ReAct Node* vs *Node + Rel* vs *No Val Link*) on movie · geography · politics. |

## Infrastructure

| doc | role |
|---|---|
| [RUNNING_EXPERIMENTS.md](RUNNING_EXPERIMENTS.md) | **Operational guide for collaborators** — how to run multi-dataset / multi-graph eval batches safely. The single-live-tree swap trap, the `verify_setup.py` pre-flight, and how to recognise + fix a contaminated archive. Read before running a batch. |
| [GRAPHS.md](GRAPHS.md) | Live reference for the deployed Neo4j graphs (labels, rel types, ports). |
| [DEPLOY_LOG.md](DEPLOY_LOG.md) | GCP VM / Neo4j deployment record. |

## archive/

Superseded or rejected drafts, kept for provenance:

| doc | why archived |
|---|---|
| [archive/AUGMENTATION_REDESIGN.md](archive/AUGMENTATION_REDESIGN.md) | Original redesign proposal; superseded by `AUGMENTATION_METHODS.md` (final) + the implemented pipeline. |
| [archive/NER_ABLATION_REPORT.md](archive/NER_ABLATION_REPORT.md) | Gated-integration-era ablation numbers; superseded by `NER_ABLATION_HEAD_BASELINE.md`. |
| [archive/NER_IMPROVEMENT_PROPOSAL.md](archive/NER_IMPROVEMENT_PROPOSAL.md) | Gated-integration / C-pruning proposal; the direction was validated to break movie and **rejected** (see the HEAD-baseline study). |
| [archive/NER_ABLATION_RESULTS_TABLES.md](archive/NER_ABLATION_RESULTS_TABLES.md) | Old 3-mode (`full`/`node_only`/`no_ner`) result tables; superseded by `ablation_flight_accident.md` + the Plan&Exec method. |
| [archive/NER_ablation_movie_geography.md](archive/NER_ablation_movie_geography.md) | Old movie/geography ReAct-mode ablation; pending re-run with the Plan&Exec modes. |
| [archive/NER_ablation_flight_accident.md](archive/NER_ablation_flight_accident.md) | Old flight_accident ReAct-mode ablation; superseded by `ablation_flight_accident.md`. |
| [archive/ablation_flight_accident.md](archive/ablation_flight_accident.md) | First draft of the new flight_accident ablation (pre-final mode labels). |
