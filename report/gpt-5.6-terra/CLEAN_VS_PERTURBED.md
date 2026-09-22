# Clean vs. perturbed — `gpt-5.6-terra`

Execution accuracy on **paired** questions: every perturbed question scored next to its clean original (same gold Cypher, same graph); clean questions without a perturbed counterpart are excluded. Errored questions score 0. Δ = perturbed − clean.

## By dataset

| method | CypherBench clean | CypherBench pert. | Δ | MindTheQuery clean | MindTheQuery pert. | Δ | ZOGRASCOPE clean | ZOGRASCOPE pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.608 | 0.094 | -0.514 | 0.381 | 0.246 | -0.136 | 0.270 | 0.031 | -0.239 |
| n | 2090 | |  | 1217 | |  | 1283 | | |

## All datasets pooled

| method | all clean | all pert. | Δ |
|---|---:|---:|---:|
| No Val Link | 0.454 | 0.117 | -0.337 |
| n | 4590 | | |

## Question flips (pooled)

| method | clean ✓ → pert. ✗ | clean ✗ → pert. ✓ | both ✓ | both ✗ | n |
|---|---:|---:|---:|---:|---:|
| No Val Link | 1597 | 50 | 485 | 2458 | 4590 |

## By perturbation strategy (pooled)

| method | casing clean | casing pert. | Δ | typo clean | typo pert. | Δ | partial clean | partial pert. | Δ | abbrev clean | abbrev pert. | Δ | alias clean | alias pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.447 | 0.229 | -0.218 | 0.323 | 0.078 | -0.245 | 0.504 | 0.118 | -0.387 | 0.494 | 0.115 | -0.379 | 0.582 | 0.121 | -0.461 |
| n | 463 | |  | 1439 | |  | 815 | |  | 1033 | |  | 840 | | |

## By query difficulty (pooled)

| method | easy clean | easy pert. | Δ | medium clean | medium pert. | Δ | hard clean | hard pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.594 | 0.079 | -0.515 | 0.438 | 0.115 | -0.323 | 0.434 | 0.134 | -0.300 |
| n | 495 | |  | 2815 | |  | 1280 | | |

## PSJS (pooled)

| method | clean | perturbed | Δ |
|---|---:|---:|---:|
| No Val Link | 0.658 | 0.140 | -0.519 |

## Per graph

| dataset | graph | n | No Val Link clean | No Val Link pert. |
|---|---|---:|---:|---:|
| CypherBench | company | 303 | 0.617 | 0.106 |
| CypherBench | fictional_character | 322 | 0.571 | 0.081 |
| CypherBench | flight_accident | 168 | 0.845 | 0.179 |
| CypherBench | geography | 331 | 0.595 | 0.094 |
| CypherBench | movie | 359 | 0.485 | 0.050 |
| CypherBench | nba | 251 | 0.669 | 0.084 |
| CypherBench | politics | 356 | 0.615 | 0.107 |
| MindTheQuery | bloom | 24 | 0.583 | 0.250 |
| MindTheQuery | covid | 326 | 0.071 | 0.028 |
| MindTheQuery | er | 184 | 0.565 | 0.293 |
| MindTheQuery | healthcare | 418 | 0.670 | 0.471 |
| MindTheQuery | wwc | 265 | 0.162 | 0.125 |
| ZOGRASCOPE | pole | 1283 | 0.270 | 0.031 |
