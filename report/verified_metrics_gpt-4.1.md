# Metrics on the human-verified subset

- Verdicts from the release decisions file; pending items **keep** (0 pending)
- Rows dropped by verification: **50** (invalid / source-error)
- Rows outside the verification queue are kept (never sampled for review)

| run | n before | n after | dropped | EA before | EA after | EM before | EM after | PSJS before | PSJS after |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| cypherbench__flight_accident__cyanchor_fl | 189 | 187 | 2 | 0.9524 | 0.9519 | 0.0000 | 0.0000 | 0.9904 | 0.9903 |
| cypherbench__flight_accident__fcav | 189 | 187 | 2 | 0.8148 | 0.8128 | 0.0000 | 0.0000 | 0.9057 | 0.9047 |
| cypherbench__flight_accident__graphrag | 189 | 187 | 2 | 0.9471 | 0.9465 | 0.0000 | 0.0000 | 0.9770 | 0.9768 |
| cypherbench__flight_accident__no_val_link | 189 | 187 | 2 | 0.7989 | 0.7968 | 0.0000 | 0.0000 | 0.9340 | 0.9333 |
| cypherbench__flight_accident__react | 189 | 187 | 2 | 0.8360 | 0.8342 | 0.0000 | 0.0000 | 0.8652 | 0.8638 |
| cypherbench_augmented__company__cyanchor_fl | 308 | 307 | 1 | 0.7013 | 0.7003 | 0.0000 | 0.0000 | 0.7142 | 0.7133 |
| cypherbench_augmented__company__fcav | 308 | 307 | 1 | 0.0812 | 0.0814 | 0.0000 | 0.0000 | 0.1206 | 0.1210 |
| cypherbench_augmented__company__graphrag | 308 | 307 | 1 | 0.5032 | 0.5016 | 0.0000 | 0.0000 | 0.5295 | 0.5280 |
| cypherbench_augmented__company__no_val_link | 308 | 307 | 1 | 0.0747 | 0.0749 | 0.0000 | 0.0000 | 0.1113 | 0.1117 |
| cypherbench_augmented__company__react | 308 | 307 | 1 | 0.4643 | 0.4625 | 0.0000 | 0.0000 | 0.4858 | 0.4842 |
| cypherbench_augmented__fictional_character__cyanchor_fl | 326 | 323 | 3 | 0.5920 | 0.5975 | 0.0000 | 0.0000 | 0.6541 | 0.6583 |
| cypherbench_augmented__fictional_character__fcav | 326 | 323 | 3 | 0.0706 | 0.0712 | 0.0000 | 0.0000 | 0.0958 | 0.0948 |
| cypherbench_augmented__fictional_character__graphrag | 326 | 323 | 3 | 0.4172 | 0.4211 | 0.0000 | 0.0000 | 0.4549 | 0.4572 |
| cypherbench_augmented__fictional_character__no_val_link | 326 | 323 | 3 | 0.0706 | 0.0712 | 0.0000 | 0.0000 | 0.0966 | 0.0956 |
| cypherbench_augmented__fictional_character__react | 326 | 323 | 3 | 0.3344 | 0.3375 | 0.0000 | 0.0000 | 0.3781 | 0.3797 |
| cypherbench_augmented__flight_accident__chess_adapted__20260707-122224 | 170 | 168 | 2 | 0.6294 | 0.6310 | 0.0000 | 0.0000 | 0.6694 | 0.6714 |
| cypherbench_augmented__flight_accident__chess_adapted__20260707-165632 | 170 | 168 | 2 | 0.6647 | 0.6667 | 0.0000 | 0.0000 | 0.7060 | 0.7084 |
| cypherbench_augmented__flight_accident__chess_adapted_repair__20260708-000532 | 170 | 168 | 2 | 0.8000 | 0.7976 | 0.0000 | 0.0000 | 0.8543 | 0.8526 |
| cypherbench_augmented__flight_accident__cyanchor_fl | 170 | 168 | 2 | 0.8000 | 0.7976 | 0.0000 | 0.0000 | 0.8446 | 0.8428 |
| cypherbench_augmented__flight_accident__cyanchor_fvl | 170 | 168 | 2 | 0.7882 | 0.7857 | 0.0000 | 0.0000 | 0.8485 | 0.8466 |
| cypherbench_augmented__flight_accident__cyanchor_skeleton__20260707-122703 | 170 | 168 | 2 | 0.7118 | 0.7143 | 0.0000 | 0.0000 | 0.7389 | 0.7417 |
| cypherbench_augmented__flight_accident__fcav | 170 | 168 | 2 | 0.4706 | 0.4643 | 0.0000 | 0.0000 | 0.5115 | 0.5056 |
| cypherbench_augmented__flight_accident__graphrag | 170 | 168 | 2 | 0.6118 | 0.6131 | 0.0000 | 0.0000 | 0.6206 | 0.6220 |
| cypherbench_augmented__flight_accident__no_val_link | 170 | 168 | 2 | 0.1059 | 0.1071 | 0.0000 | 0.0000 | 0.1159 | 0.1173 |
| cypherbench_augmented__flight_accident__react | 170 | 168 | 2 | 0.4059 | 0.4107 | 0.0000 | 0.0000 | 0.4101 | 0.4150 |
| cypherbench_augmented__geography__cyanchor_fl | 339 | 334 | 5 | 0.7227 | 0.7275 | 0.0000 | 0.0000 | 0.7734 | 0.7790 |
| cypherbench_augmented__geography__fcav | 339 | 334 | 5 | 0.1829 | 0.1856 | 0.0000 | 0.0000 | 0.2774 | 0.2756 |
| cypherbench_augmented__geography__graphrag | 339 | 334 | 5 | 0.4956 | 0.5000 | 0.0000 | 0.0000 | 0.5442 | 0.5479 |
| cypherbench_augmented__geography__no_val_link | 339 | 334 | 5 | 0.0737 | 0.0749 | 0.0000 | 0.0000 | 0.1054 | 0.1070 |
| cypherbench_augmented__geography__react | 339 | 334 | 5 | 0.3923 | 0.3982 | 0.0000 | 0.0000 | 0.4325 | 0.4390 |
| cypherbench_augmented__movie__cyanchor_fl | 370 | 363 | 7 | 0.6297 | 0.6364 | 0.0000 | 0.0000 | 0.6675 | 0.6720 |
| cypherbench_augmented__movie__fcav | 370 | 363 | 7 | 0.2514 | 0.2534 | 0.0000 | 0.0000 | 0.3664 | 0.3671 |
| cypherbench_augmented__movie__graphrag | 370 | 363 | 7 | 0.4973 | 0.4986 | 0.0000 | 0.0000 | 0.5694 | 0.5714 |
| cypherbench_augmented__movie__no_val_link | 370 | 363 | 7 | 0.0432 | 0.0413 | 0.0000 | 0.0000 | 0.1069 | 0.1046 |
| cypherbench_augmented__movie__react | 370 | 363 | 7 | 0.3757 | 0.3802 | 0.0000 | 0.0000 | 0.4446 | 0.4478 |
| cypherbench_augmented__nba__cyanchor_fl | 258 | 258 | 0 | 0.8062 | 0.8062 | 0.0000 | 0.0000 | 0.8761 | 0.8761 |
| cypherbench_augmented__nba__fcav | 258 | 258 | 0 | 0.0775 | 0.0775 | 0.0000 | 0.0000 | 0.1251 | 0.1251 |
| cypherbench_augmented__nba__graphrag | 258 | 258 | 0 | 0.6822 | 0.6822 | 0.0000 | 0.0000 | 0.7589 | 0.7589 |
| cypherbench_augmented__nba__no_val_link | 258 | 258 | 0 | 0.0736 | 0.0736 | 0.0000 | 0.0000 | 0.1093 | 0.1093 |
| cypherbench_augmented__nba__react | 258 | 258 | 0 | 0.3372 | 0.3372 | 0.0000 | 0.0000 | 0.3677 | 0.3677 |
| cypherbench_augmented__politics__cyanchor_fl | 365 | 364 | 1 | 0.7068 | 0.7060 | 0.0000 | 0.0000 | 0.7498 | 0.7491 |
| cypherbench_augmented__politics__fcav | 365 | 364 | 1 | 0.1452 | 0.1429 | 0.0000 | 0.0000 | 0.2049 | 0.2027 |
| cypherbench_augmented__politics__graphrag | 365 | 364 | 1 | 0.5479 | 0.5467 | 0.0000 | 0.0000 | 0.6156 | 0.6146 |
| cypherbench_augmented__politics__no_val_link | 365 | 364 | 1 | 0.1014 | 0.0989 | 0.0000 | 0.0000 | 0.1227 | 0.1203 |
| cypherbench_augmented__politics__react | 365 | 364 | 1 | 0.3699 | 0.3681 | 0.0000 | 0.0000 | 0.4233 | 0.4217 |
| mindthequery__bloom50__cyanchor_fl | 58 | 58 | 0 | 0.7414 | 0.7414 | 0.0172 | 0.0172 | 0.7933 | 0.7933 |
| mindthequery__bloom50__fcav | 58 | 58 | 0 | 0.4138 | 0.4138 | 0.0172 | 0.0172 | 0.7406 | 0.7406 |
| mindthequery__bloom50__graphrag | 58 | 58 | 0 | 0.7414 | 0.7414 | 0.0172 | 0.0172 | 0.7855 | 0.7855 |
| mindthequery__bloom50__no_val_link | 58 | 58 | 0 | 0.4483 | 0.4483 | 0.0172 | 0.0172 | 0.7759 | 0.7759 |
| mindthequery__bloom50__react | 58 | 58 | 0 | 0.7069 | 0.7069 | 0.0172 | 0.0172 | 0.7241 | 0.7241 |
| mindthequery_augmented__bloom__cyanchor_fl | 40 | 40 | 0 | 0.5500 | 0.5500 | 0.0000 | 0.0000 | 0.6202 | 0.6202 |
| mindthequery_augmented__bloom__fcav | 40 | 40 | 0 | 0.3000 | 0.3000 | 0.0000 | 0.0000 | 0.3990 | 0.3990 |
| mindthequery_augmented__bloom__graphrag | 40 | 40 | 0 | 0.5250 | 0.5250 | 0.0000 | 0.0000 | 0.6490 | 0.6490 |
| mindthequery_augmented__bloom__no_val_link | 40 | 40 | 0 | 0.2750 | 0.2750 | 0.0000 | 0.0000 | 0.3740 | 0.3740 |
| mindthequery_augmented__bloom__react | 40 | 40 | 0 | 0.5250 | 0.5250 | 0.0000 | 0.0000 | 0.5000 | 0.5000 |
| mindthequery_augmented__covid__cyanchor_fl | 342 | 342 | 0 | 0.3772 | 0.3772 | 0.0000 | 0.0000 | 0.1979 | 0.1979 |
| mindthequery_augmented__covid__cyanchor_fvl | 342 | 342 | 0 | 0.3187 | 0.3187 | 0.0000 | 0.0000 | 0.1826 | 0.1826 |
| mindthequery_augmented__covid__fcav | 342 | 342 | 0 | 0.0205 | 0.0205 | 0.0000 | 0.0000 | 0.0759 | 0.0759 |
| mindthequery_augmented__covid__graphrag | 342 | 342 | 0 | 0.3772 | 0.3772 | 0.0000 | 0.0000 | 0.4598 | 0.4598 |
| mindthequery_augmented__covid__no_val_link | 342 | 342 | 0 | 0.0234 | 0.0234 | 0.0000 | 0.0000 | 0.0599 | 0.0599 |
| mindthequery_augmented__covid__react | 342 | 342 | 0 | 0.1637 | 0.1637 | 0.0000 | 0.0000 | 0.2819 | 0.2819 |
| mindthequery_augmented__er__cyanchor_fl | 202 | 201 | 1 | 0.6931 | 0.6965 | 0.0000 | 0.0000 | 0.7792 | 0.7781 |
| mindthequery_augmented__er__fcav | 202 | 201 | 1 | 0.3119 | 0.3134 | 0.0000 | 0.0000 | 0.2525 | 0.2537 |
| mindthequery_augmented__er__graphrag | 202 | 201 | 1 | 0.6881 | 0.6915 | 0.0000 | 0.0000 | 0.7794 | 0.7783 |
| mindthequery_augmented__er__no_val_link | 202 | 201 | 1 | 0.3069 | 0.3085 | 0.0000 | 0.0000 | 0.2525 | 0.2537 |
| mindthequery_augmented__er__react | 202 | 201 | 1 | 0.5297 | 0.5323 | 0.0000 | 0.0000 | 0.5395 | 0.5372 |
| mindthequery_augmented__healthcare__chess_adapted__20260707-125245 | 439 | 438 | 1 | 0.5490 | 0.5502 | 0.0000 | 0.0000 | 0.5829 | 0.5843 |
| mindthequery_augmented__healthcare__chess_adapted__20260707-174208 | 439 | 438 | 1 | 0.5125 | 0.5137 | 0.0000 | 0.0000 | 0.5984 | 0.5997 |
| mindthequery_augmented__healthcare__cyanchor_fl | 439 | 438 | 1 | 0.7016 | 0.7032 | 0.0000 | 0.0000 | 0.7409 | 0.7426 |
| mindthequery_augmented__healthcare__fcav | 439 | 438 | 1 | 0.4692 | 0.4703 | 0.0000 | 0.0000 | 0.4622 | 0.4632 |
| mindthequery_augmented__healthcare__graphrag | 439 | 438 | 1 | 0.6902 | 0.6918 | 0.0000 | 0.0000 | 0.7126 | 0.7143 |
| mindthequery_augmented__healthcare__no_val_link | 439 | 438 | 1 | 0.4670 | 0.4680 | 0.0000 | 0.0000 | 0.4599 | 0.4609 |
| mindthequery_augmented__healthcare__react | 439 | 438 | 1 | 0.6674 | 0.6689 | 0.0000 | 0.0000 | 0.6980 | 0.6996 |
| mindthequery_augmented__wwc__cyanchor_fl | 275 | 272 | 3 | 0.5091 | 0.5110 | 0.0000 | 0.0000 | 0.7255 | 0.7286 |
| mindthequery_augmented__wwc__fcav | 275 | 272 | 3 | 0.1418 | 0.1397 | 0.0000 | 0.0000 | 0.3374 | 0.3374 |
| mindthequery_augmented__wwc__graphrag | 275 | 272 | 3 | 0.5091 | 0.5147 | 0.0000 | 0.0000 | 0.6993 | 0.7057 |
| mindthequery_augmented__wwc__no_val_link | 275 | 272 | 3 | 0.1382 | 0.1397 | 0.0000 | 0.0000 | 0.3410 | 0.3448 |
| mindthequery_augmented__wwc__react | 275 | 272 | 3 | 0.4473 | 0.4485 | 0.0000 | 0.0000 | 0.6375 | 0.6409 |
| zograscope_augmented__pole__chess_adapted__20260707-130806 | 1441 | 1415 | 26 | 0.0666 | 0.0678 | 0.0000 | 0.0000 | 0.0876 | 0.0889 |
| zograscope_augmented__pole__chess_adapted__20260707-175346 | 1441 | 1415 | 26 | 0.1686 | 0.1696 | 0.0000 | 0.0000 | 0.2263 | 0.2296 |
| zograscope_augmented__pole__cyanchor_fl | 1441 | 1415 | 26 | 0.2915 | 0.2940 | 0.0000 | 0.0000 | 0.3615 | 0.3646 |
| zograscope_augmented__pole__fcav | 1441 | 1415 | 26 | 0.0854 | 0.0848 | 0.0000 | 0.0000 | 0.1241 | 0.1250 |
| zograscope_augmented__pole__graphrag | 1441 | 1415 | 26 | 0.1638 | 0.1654 | 0.0000 | 0.0000 | 0.2604 | 0.2637 |
| zograscope_augmented__pole__no_val_link | 1441 | 1415 | 26 | 0.0493 | 0.0495 | 0.0000 | 0.0000 | 0.0436 | 0.0444 |
| zograscope_augmented__pole__react | 1441 | 1415 | 26 | 0.1763 | 0.1788 | 0.0000 | 0.0000 | 0.2313 | 0.2333 |

> **Warning:** 1902 record(s) had no manifest entry for their (graph, qid) and were kept unconditionally. This means the evaluation ran on a different dataset build than the manifest — check before using these numbers.
