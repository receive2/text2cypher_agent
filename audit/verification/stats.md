# Human Verification — Results

- Items annotated: **1739** (5 annotators: A, B, C, D, E)
- Calibration items excluded from all measurements (pre-registered): 48 ids on the exclusion list (27 present in the queue; 54 judgments dropped)
- Double-annotated: 1524; disagreements: 53 (3.5% of double-annotated) → adjudication
- Still **pending** adjudication: 55
- Source-error rows (dropped): 5
- **Final retained N (valid): 1657**

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
| abbrev | 728 | 695 | 686 | 9 | 3 | 30 | 98.7% [97.6, 99.3] | 0.357 | 0.957 | 95.9% (728) |
| alias | 520 | 507 | 506 | 1 | 0 | 13 | 99.8% [98.9, 100.0] | 0.178 | 0.975 | 97.5% (520) |
| casing | 99 | 98 | 98 | 0 | 1 | 0 | 100.0% [96.2, 100.0] | 1.000 | 1.000 | 100.0% (79) |
| partial | 192 | 181 | 171 | 10 | 1 | 10 | 94.5% [90.1, 97.0] | 0.438 | 0.921 | 92.6% (122) |
| typo | 200 | 198 | 196 | 2 | 0 | 2 | 99.0% [96.4, 99.7] | 0.664 | 0.987 | 98.8% (80) |

## Validity by provenance

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| algorithmic | 448 | 434 | 422 | 12 | 2 | 12 | 97.2% [95.2, 98.4] | 0.482 | 0.956 | 95.8% (238) |
| attested | 393 | 384 | 381 | 3 | 0 | 9 | 99.2% [97.7, 99.7] | 0.390 | 0.977 | 97.7% (393) |
| llm | 898 | 861 | 854 | 7 | 3 | 34 | 99.2% [98.3, 99.6] | 0.291 | 0.961 | 96.2% (898) |

## Validity by dataset

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| cypherbench | 845 | 818 | 809 | 9 | 1 | 26 | 98.9% [97.9, 99.4] | 0.284 | 0.966 | 96.7% (784) |
| mindthequery | 593 | 582 | 580 | 2 | 0 | 11 | 99.7% [98.8, 99.9] | 0.160 | 0.981 | 98.1% (538) |
| zograscope | 301 | 279 | 268 | 11 | 4 | 18 | 96.1% [93.1, 97.8] | 0.475 | 0.911 | 91.8% (207) |

## Validity by strategy × provenance

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| abbrev / attested | 194 | 188 | 186 | 2 | 0 | 6 | 98.9% [96.2, 99.7] | 0.387 | 0.968 | 96.9% (194) |
| abbrev / llm | 534 | 507 | 500 | 7 | 3 | 24 | 98.6% [97.2, 99.3] | 0.349 | 0.953 | 95.5% (534) |
| alias / attested | 199 | 196 | 195 | 1 | 0 | 3 | 99.5% [97.2, 99.9] | 0.394 | 0.985 | 98.5% (199) |
| alias / llm | 321 | 311 | 311 | 0 | 0 | 10 | 100.0% [98.8, 100.0] | 0.080 | 0.968 | 96.9% (321) |
| casing / algorithmic | 99 | 98 | 98 | 0 | 1 | 0 | 100.0% [96.2, 100.0] | 1.000 | 1.000 | 100.0% (79) |
| partial / algorithmic | 149 | 138 | 128 | 10 | 1 | 10 | 92.8% [87.2, 96.0] | 0.418 | 0.874 | 88.6% (79) |
| partial / llm | 43 | 43 | 43 | 0 | 0 | 0 | 100.0% [91.8, 100.0] | 1.000 | 1.000 | 100.0% (43) |
| typo / algorithmic | 200 | 198 | 196 | 2 | 0 | 2 | 99.0% [96.4, 99.7] | 0.664 | 0.987 | 98.8% (80) |

## Overall

| stratum | n | resolved | valid | invalid | src_err | pending | validity% [95% CI] | alpha | AC1 | raw agr (n_2) |
|---|--:|--:|--:|--:|--:|--:|---|--:|--:|---|
| ALL | 1739 | 1679 | 1657 | 22 | 5 | 55 | 98.7% [98.0, 99.1] | 0.354 | 0.964 | 96.5% (1529) |
