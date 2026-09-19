# Clean vs. perturbed — `gpt-5.6-terra`

Execution accuracy on **paired** questions: every perturbed question scored next to its clean original (same gold Cypher, same graph); clean questions without a perturbed counterpart are excluded. Errored questions score 0. Δ = perturbed − clean.

## By dataset

| method | CypherBench clean | CypherBench pert. | Δ | MindTheQuery clean | MindTheQuery pert. | Δ | ZOGRASCOPE clean | ZOGRASCOPE pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.608 | 0.094 | -0.515 | 0.381 | 0.246 | -0.135 | 0.271 | 0.031 | -0.240 |
| n | 2099 | |  | 1222 | |  | 1290 | | |

## All datasets pooled

| method | all clean | all pert. | Δ |
|---|---:|---:|---:|
| No Val Link | 0.454 | 0.117 | -0.337 |
| n | 4611 | | |

## Question flips (pooled)

| method | clean ✓ → pert. ✗ | clean ✗ → pert. ✓ | both ✓ | both ✗ | n |
|---|---:|---:|---:|---:|---:|
| No Val Link | 1604 | 50 | 488 | 2469 | 4611 |

## By perturbation strategy (pooled)

| method | casing clean | casing pert. | Δ | typo clean | typo pert. | Δ | partial clean | partial pert. | Δ | abbrev clean | abbrev pert. | Δ | alias clean | alias pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.447 | 0.229 | -0.218 | 0.323 | 0.078 | -0.245 | 0.505 | 0.119 | -0.386 | 0.494 | 0.115 | -0.379 | 0.582 | 0.121 | -0.461 |
| n | 463 | |  | 1441 | |  | 834 | |  | 1033 | |  | 840 | | |

## By query difficulty (pooled)

| method | easy clean | easy pert. | Δ | medium clean | medium pert. | Δ | hard clean | hard pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.593 | 0.078 | -0.515 | 0.438 | 0.115 | -0.323 | 0.434 | 0.134 | -0.299 |
| n | 499 | |  | 2825 | |  | 1287 | | |

## PSJS (pooled)

| method | clean | perturbed | Δ |
|---|---:|---:|---:|
| No Val Link | 0.658 | 0.140 | -0.519 |

## Per graph

| dataset | graph | n | No Val Link clean | No Val Link pert. |
|---|---|---:|---:|---:|
| CypherBench | company | 305 | 0.616 | 0.105 |
| CypherBench | fictional_character | 324 | 0.571 | 0.083 |
| CypherBench | flight_accident | 168 | 0.845 | 0.179 |
| CypherBench | geography | 331 | 0.595 | 0.094 |
| CypherBench | movie | 360 | 0.483 | 0.050 |
| CypherBench | nba | 251 | 0.669 | 0.084 |
| CypherBench | politics | 360 | 0.619 | 0.106 |
| MindTheQuery | bloom | 24 | 0.583 | 0.250 |
| MindTheQuery | covid | 327 | 0.070 | 0.028 |
| MindTheQuery | er | 185 | 0.568 | 0.297 |
| MindTheQuery | healthcare | 419 | 0.671 | 0.473 |
| MindTheQuery | wwc | 267 | 0.161 | 0.124 |
| ZOGRASCOPE | pole | 1290 | 0.271 | 0.031 |
