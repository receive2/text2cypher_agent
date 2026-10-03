# Clean vs. perturbed — `gpt-5.6-terra`

Execution accuracy on **paired** questions: every perturbed question scored next to its clean original (same gold Cypher, same graph); clean questions without a perturbed counterpart are excluded. Errored questions score 0. Δ = perturbed − clean.

## By dataset

| method | CypherBench clean | CypherBench pert. | Δ | MindTheQuery clean | MindTheQuery pert. | Δ | ZOGRASCOPE clean | ZOGRASCOPE pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.608 | 0.094 | -0.514 | 0.385 | 0.246 | -0.139 | 0.465 | 0.044 | -0.422 |
| n | 2090 | |  | 1217 | |  | 1283 | | |

## All datasets pooled

| method | all clean | all pert. | Δ |
|---|---:|---:|---:|
| No Val Link | 0.509 | 0.120 | -0.389 |
| n | 4590 | | |

## Question flips (pooled)

| method | clean ✓ → pert. ✗ | clean ✗ → pert. ✓ | both ✓ | both ✗ | n |
|---|---:|---:|---:|---:|---:|
| No Val Link | 1837 | 52 | 499 | 2202 | 4590 |

## By perturbation strategy (pooled)

| method | casing clean | casing pert. | Δ | typo clean | typo pert. | Δ | partial clean | partial pert. | Δ | abbrev clean | abbrev pert. | Δ | alias clean | alias pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.501 | 0.246 | -0.255 | 0.429 | 0.082 | -0.347 | 0.563 | 0.119 | -0.444 | 0.522 | 0.116 | -0.406 | 0.582 | 0.121 | -0.461 |
| n | 463 | |  | 1439 | |  | 815 | |  | 1033 | |  | 840 | | |

## By query difficulty (pooled)

| method | easy clean | easy pert. | Δ | medium clean | medium pert. | Δ | hard clean | hard pert. | Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| No Val Link | 0.711 | 0.089 | -0.622 | 0.495 | 0.117 | -0.378 | 0.462 | 0.139 | -0.323 |
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
| MindTheQuery | bloom | 24 | 0.750 | 0.250 |
| MindTheQuery | covid | 326 | 0.071 | 0.028 |
| MindTheQuery | er | 184 | 0.565 | 0.293 |
| MindTheQuery | healthcare | 418 | 0.670 | 0.471 |
| MindTheQuery | wwc | 265 | 0.162 | 0.125 |
| ZOGRASCOPE | pole | 1283 | 0.465 | 0.044 |
