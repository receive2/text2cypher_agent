# Clean vs. perturbed — `gpt-5.6-terra`

Execution accuracy on **paired** questions: every perturbed question scored next to its clean original (same gold Cypher, same graph); clean questions without a perturbed counterpart are excluded. Errored questions score 0. Δ = perturbed − clean.

## By dataset

| method | CypherBench clean | CypherBench pert. | Δ | MindTheQuery clean | MindTheQuery pert. | Δ | ZOGRASCOPE clean | ZOGRASCOPE pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.737 | 0.110 | -0.627 | 0.617 | 0.254 | -0.363 | 0.465 | 0.044 | -0.422 |
| n | 2090 | |  | 1217 | |  | 1283 | | |

## All datasets pooled

| method | all clean | all pert. | Δ |
|---|---:|---:|---:|
| No Val Link | 0.629 | 0.130 | -0.500 |
| n | 4590 | | |

## Question flips (pooled)

| method | clean ✓ → pert. ✗ | clean ✗ → pert. ✓ | both ✓ | both ✗ | n |
|---|---:|---:|---:|---:|---:|
| No Val Link | 2347 | 53 | 542 | 1648 | 4590 |

## By perturbation strategy (pooled)

| method | casing clean | casing pert. | Δ | typo clean | typo pert. | Δ | partial clean | partial pert. | Δ | abbrev clean | abbrev pert. | Δ | alias clean | alias pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.609 | 0.272 | -0.337 | 0.507 | 0.083 | -0.424 | 0.667 | 0.120 | -0.547 | 0.700 | 0.137 | -0.562 | 0.727 | 0.131 | -0.596 |
| n | 463 | |  | 1439 | |  | 815 | |  | 1033 | |  | 840 | | |

## By query difficulty (pooled)

| method | easy clean | easy pert. | Δ | medium clean | medium pert. | Δ | hard clean | hard pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.848 | 0.101 | -0.747 | 0.610 | 0.123 | -0.487 | 0.588 | 0.155 | -0.433 |
| n | 495 | |  | 2815 | |  | 1280 | | |

## PSJS (pooled)

| method | clean | perturbed | Δ |
|---|---:|---:|---:|
| No Val Link | 0.658 | 0.140 | -0.519 |

## Per graph

| dataset | graph | n | No Val Link clean | No Val Link pert. |
|---|---|---:|---:|---:|
| CypherBench | company | 303 | 0.743 | 0.129 |
| CypherBench | fictional_character | 322 | 0.612 | 0.087 |
| CypherBench | flight_accident | 168 | 0.875 | 0.190 |
| CypherBench | geography | 331 | 0.716 | 0.112 |
| CypherBench | movie | 359 | 0.666 | 0.064 |
| CypherBench | nba | 251 | 0.777 | 0.092 |
| CypherBench | politics | 356 | 0.846 | 0.135 |
| MindTheQuery | bloom | 24 | 0.917 | 0.250 |
| MindTheQuery | covid | 326 | 0.304 | 0.028 |
| MindTheQuery | er | 184 | 0.707 | 0.293 |
| MindTheQuery | healthcare | 418 | 0.816 | 0.488 |
| MindTheQuery | wwc | 265 | 0.600 | 0.136 |
| ZOGRASCOPE | pole | 1283 | 0.465 | 0.044 |
