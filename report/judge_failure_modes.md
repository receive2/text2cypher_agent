# Select-or-abstain judge — failure-mode measurement (gpt-5.6-terra)

Predicted queries of the reference run (judge on) and the `no_select_judge` run re-executed read-only; every question classified as correct / wrong-empty / wrong-nonempty (a confidently wrong answer) / error. The judge's designed effect is to turn confident wrong answers into abstentions; EA cannot see that, this table can.

| graph | n | correct ON / OFF | wrong-empty ON / OFF | **wrong-nonempty ON / OFF** | Δ confident-wrong (OFF−ON) |
|---|---|---|---|---|---|
| flight_accident | 168 | 145 / 146 | 7 / 6 | **16 / 16** | +0.0 pts |
| healthcare | 418 | 293 / 296 | 58 / 54 | **63 / 64** | +0.2 pts |
| pole | 400 | 143 / 135 | 59 / 59 | **198 / 206** | +2.0 pts |
| nba | 251 | 197 / 196 | 11 / 12 | **43 / 43** | +0.0 pts |
| **pooled** | 1237 | | | **320 / 329** (25.9% / 26.6%) | **+0.7 pts** |

Pre-committed decision rule: keep the judge if it lowers the confident-wrong rate by ≥3 points. Measured: +0.7 points → removed from the shipped configuration (also 0 on EA: pooled 52/57 flips, p=0.70).

Source: `scripts/tuning/measure_failure_modes.py`, per-question categories in `report/judge_failure_modes.json`.
