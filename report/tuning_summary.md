# CyANCHOR configuration sweep — summary (2026-09-10)

Protocol: all selection on the schema-disjoint dev graph (CypherBench train split,
terrorist_attack; perturbed dev set n=1,420, design mixture 23/23/22/22/10).
Test graphs were run ONCE with the dev-selected config as a transfer REPORT and
never fed back into selection. Every comparison is paired per question on the
same LIMIT prefix. Backbone gpt-4.1 for all stages.

## Stage 1 — coordinate screen, dev, n=200 (default EA 0.760)
| knob | values (default in bold) | EA |
|---|---|---|
| PLAN_EXEC_VALUES_PER_TOOL | 5 / **10** / 20 | 0.765 / 0.760 / 0.750 |
| PLAN_EXEC_TOOLS_PER_ENTITY | 1 / **2** / 3 | 0.735 / 0.760 / 0.750  (true peak) |
| RETRIEVAL_LEVENSHTEIN_K | 5 / **10** / 20 | 0.760 / 0.760 / 0.775 |
| PLAN_EXEC_ROUTE_FETCH | 3 / **6** / 10 | 0.760 / 0.760 / 0.735  (true peak) |

## Stage 2 — confirmation, dev, n=400 (default EA 0.762, PSJS 0.800)
| config | EA | Δ | PSJS | flips g/l | two-sided sign p |
|---|---|---|---|---|---|
| levk20 | 0.775 | +1.3 | 0.811 | 27/22 | 0.57 |
| combo = vpt5 + levk20 | 0.775 | +1.3 | 0.818 | – | – |
| budget_lean (3,2,1) | 0.772 | +1.0 | 0.804 | – | – |
| budget_deep (8,5,3) | 0.765 | +0.3 | 0.815 | – | – |
| vpt5 | 0.762 | 0.0 | 0.818 | – | – |
| maxiter2 | 0.752 | −1.0 | 0.801 | – | – |
| tuned_bundle = combo + budget_lean | 0.752* | −1.0 | 0.821 | vs combo 12/21 | 0.16 |

*one question lost to a SIGSTOP freeze artifact (timeout), excluded pairwise.
Bundle vs combo differ only in the escalation budget; the loss is alias-driven
(−7.8, n=90): trimming initial candidates AND the escalation budget starves
alias recovery. Candidate-trimming changes do not stack.

## Stage 3 — transfer report (dev-selected config = combo), v2.1 copies, n=400
| graph | family | default → combo | flips | p | typo bucket |
|---|---|---|---|---|---|
| healthcare | MTQ (11 rel) | 0.700 → 0.700 | 11/11 | 1.00 | 0.806 → 0.806 (n=72) |
| pole | ZOG (17 rel, 60% typo) | 0.325 → 0.328 | 13/12 | 1.00 | 0.328 → 0.311 (n=238) |

## Outcome
No swept setting beats the shipped defaults beyond noise on the dev graph
(best +1.3, p=0.57) and the dev-selected config transfers as exactly neutral
on two held-out graphs from other benchmark families. Two knobs are true peaks
at their defaults (TOOLS_PER_ENTITY=2, ROUTE_FETCH=6). **Defaults kept.**
The method's gains come from its structure (see the component ablations),
not from parameter search.

Runs: logs/tune/ (dev), logs/tune_transfer/ (test), baselines logs/verify_cols/.
Drivers: scripts/tuning/run_tune{,2,3_bundle,4_transfer}.py (idempotent).
