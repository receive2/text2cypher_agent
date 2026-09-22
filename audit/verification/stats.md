# Human Verification — Results

- Items annotated: **1739** (5 annotators: A, B, C, D, E)
- Calibration items excluded from all measurements (pre-registered): 48 ids on the exclusion list (27 present in the queue; 54 judgments dropped)
- Double-annotated: 1529; disagreements: 53 (3.5% of double-annotated) → adjudication
- Still **pending** adjudication: 0
- Source-error rows (dropped): 5
- **Final retained N (valid): 1686**

## Inter-annotator agreement (validity)

> Alpha and raw agreement are both reported per stratum. In high-prevalence strata (where nearly all items share one label) chance agreement is already very high, so alpha is deflated by construction. **Gwet's AC1** is chance-corrected but does not degenerate under high prevalence; it is however permissive in the opposite direction (random labelling of a highly skewed stratum still scores high). Read alpha and AC1 as a lower and upper bracket on reliability: alpha is the primary figure wherever labels genuinely vary, AC1 documents agreement where alpha is degenerate, and raw agreement is reported for transparency. `n_2` is the number of double-annotated items in that stratum.

- Krippendorff's alpha (nominal, all items): **0.354**
- Gwet's AC1 (nominal, all items): **0.964**
- Pairwise Cohen's kappa:
  - A–B: kappa=0.000 (n=156)
  - A–C: kappa=0.326 (n=153)
  - A–D: kappa=0.000 (n=152)
  - A–E: kappa=0.147 (n=154)
  - B–C: kappa=0.350 (n=152)
  - B–D: kappa=1.000 (n=153)
  - B–E: kappa=0.390 (n=152)
  - C–D: kappa=0.587 (n=154)
  - C–E: kappa=0.479 (n=151)
  - D–E: kappa=0.324 (n=152)

## Validity by strategy

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| abbrev | 728 | 725 | 701 | 24 | 3 | 0 | 96.7% [95.1, 97.8] | 0.357 | 0.957 | 95.9% (728) |
| alias | 520 | 520 | 513 | 7 | 0 | 0 | 98.7% [97.2, 99.3] | 0.178 | 0.975 | 97.5% (520) |
| casing | 99 | 98 | 98 | 0 | 1 | 0 | 100.0% [96.2, 100.0] | 1.000 | 1.000 | 100.0% (79) |
| partial | 192 | 191 | 176 | 15 | 1 | 0 | 92.1% [87.4, 95.2] | 0.438 | 0.921 | 92.6% (122) |
| typo | 200 | 200 | 198 | 2 | 0 | 0 | 99.0% [96.4, 99.7] | 0.664 | 0.987 | 98.8% (80) |

## Validity by provenance

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| algorithmic | 448 | 446 | 429 | 17 | 2 | 0 | 96.2% [94.0, 97.6] | 0.482 | 0.956 | 95.8% (238) |
| attested | 393 | 393 | 387 | 6 | 0 | 0 | 98.5% [96.7, 99.3] | 0.390 | 0.977 | 97.7% (393) |
| llm | 898 | 895 | 870 | 25 | 3 | 0 | 97.2% [95.9, 98.1] | 0.291 | 0.961 | 96.2% (898) |

## Validity by dataset

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| cypherbench | 845 | 844 | 824 | 20 | 1 | 0 | 97.6% [96.4, 98.5] | 0.284 | 0.966 | 96.7% (784) |
| mindthequery | 593 | 593 | 588 | 5 | 0 | 0 | 99.2% [98.0, 99.6] | 0.160 | 0.981 | 98.1% (538) |
| zograscope | 301 | 297 | 274 | 23 | 4 | 0 | 92.3% [88.6, 94.8] | 0.475 | 0.911 | 91.8% (207) |

## Validity by strategy × provenance

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| abbrev / attested | 194 | 194 | 190 | 4 | 0 | 0 | 97.9% [94.8, 99.2] | 0.387 | 0.968 | 96.9% (194) |
| abbrev / llm | 534 | 531 | 511 | 20 | 3 | 0 | 96.2% [94.3, 97.5] | 0.349 | 0.953 | 95.5% (534) |
| alias / attested | 199 | 199 | 197 | 2 | 0 | 0 | 99.0% [96.4, 99.7] | 0.394 | 0.985 | 98.5% (199) |
| alias / llm | 321 | 321 | 316 | 5 | 0 | 0 | 98.4% [96.4, 99.3] | 0.080 | 0.968 | 96.9% (321) |
| casing / algorithmic | 99 | 98 | 98 | 0 | 1 | 0 | 100.0% [96.2, 100.0] | 1.000 | 1.000 | 100.0% (79) |
| partial / algorithmic | 149 | 148 | 133 | 15 | 1 | 0 | 89.9% [84.0, 93.8] | 0.418 | 0.874 | 88.6% (79) |
| partial / llm | 43 | 43 | 43 | 0 | 0 | 0 | 100.0% [91.8, 100.0] | 1.000 | 1.000 | 100.0% (43) |
| typo / algorithmic | 200 | 200 | 198 | 2 | 0 | 0 | 99.0% [96.4, 99.7] | 0.664 | 0.987 | 98.8% (80) |

## Overall

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| ALL | 1739 | 1734 | 1686 | 48 | 5 | 0 | 97.2% [96.3, 97.9] | 0.354 | 0.964 | 96.5% (1529) |
