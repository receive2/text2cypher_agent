# Component ablation of CyANCHOR — paper tables (gpt-5.6-terra)

Execution accuracy (EA, %) of the full system, and the change in EA points when one component is removed. Each cell is a single run at temperature 0, paired per question with the full-system run on the same questions; † / ‡ = two-sided paired sign test p < 0.05 / p < 0.01. Pooled = all questions of the 4 graphs, paired the same way. `− Levenshtein Retrieval` and `− Token Level Fuzzy Match` leave the other arm as the only retrieval arm. The full row is the released configuration: routing on node-property tools, select-or-abstain judge on, Token Level Fuzzy Match, Levenshtein Retrieval, Adaptive Search Control, Result Aware Query Repair and Value Existence Guard on.

## Main-text table

Rows of the full table whose pooled effect is significant (p < 0.05).

| | flight_accident (n=168) | healthcare (n=418) | pole (n=1283) | nba (n=251) | pooled (n=2,120) |
|---|---:|---:|---:|---:|---:|
| **CyANCHOR (full)** | 88.7 | 70.8 | 56.8 | 77.7 | 64.6 |
| *Grounding loop* | | | | | |
| − Adaptive Search Control | −8.9‡ | +0.7 | −2.2† | −4.8 | −2.5‡ |
| *Retrieval arms* | | | | | |
| − Levenshtein Retrieval | −6.0 | −3.3 | −3.6‡ | −8.8‡ | −4.3‡ |
| *Post-generation correction* | | | | | |
| − Result Aware Query Repair | −5.4 | −3.1† | −3.5‡ | −3.2 | −3.5‡ |
| − Value Existence Guard | −5.4 | −10.3‡ | −21.6‡ | −5.2† | −16.1‡ |

## Full table (appendix)

| | flight_accident (n=168) | healthcare (n=418) | pole (n=1283) | nba (n=251) | pooled (n=2,120) |
|---|---:|---:|---:|---:|---:|
| **CyANCHOR (full)** | 88.7 | 70.8 | 56.8 | 77.7 | 64.6 |
| *Grounding loop* | | | | | |
| − Adaptive Search Control | −8.9‡ | +0.7 | −2.2† | −4.8 | −2.5‡ |
| − select-or-abstain judge | — | — | −0.6 | — | — |
| *Retrieval arms* | | | | | |
| − Levenshtein Retrieval | −6.0 | −3.3 | −3.6‡ | −8.8‡ | −4.3‡ |
| − Token Level Fuzzy Match | −8.3‡ | +1.4 | −0.6 | −2.4 | −1.0 |
| *Post-generation correction* | | | | | |
| − Result Aware Query Repair | −5.4 | −3.1† | −3.5‡ | −3.2 | −3.5‡ |
| − Value Existence Guard | −5.4 | −10.3‡ | −21.6‡ | −5.2† | −16.1‡ |

## Paired flips behind each cell (questions gained / lost relative to the full run, sign-test p)

| | flight_accident (n=168) | healthcare (n=418) | pole (n=1283) | nba (n=251) | pooled (n=2,120) |
|---|---|---|---|---|---|
| − Adaptive Search Control | 6/21, p=0.0059 | 17/14, p=0.72 | 72/100, p=0.039 | 10/22, p=0.05 | 105/157, p=0.0016 |
| − select-or-abstain judge | — | — | 77/85, p=0.58 | — | — |
| − Levenshtein Retrieval | 10/20, p=0.099 | 23/37, p=0.092 | 77/123, p=0.0014 | 8/30, p=0.00047 | 118/210, p=4.3e-07 |
| − Token Level Fuzzy Match | 5/19, p=0.0066 | 19/13, p=0.38 | 73/81, p=0.57 | 10/16, p=0.33 | 107/129, p=0.17 |
| − Result Aware Query Repair | 7/16, p=0.093 | 12/25, p=0.047 | 59/104, p=0.00053 | 8/16, p=0.15 | 86/161, p=2.1e-06 |
| − Value Existence Guard | 6/15, p=0.078 | 18/61, p=1.3e-06 | 46/323, p=2.3e-52 | 5/18, p=0.011 | 75/417, p=1.6e-58 |

Macro-mean Δ over the 4 graphs (unweighted): − Adaptive Search Control -3.8; − Levenshtein Retrieval -5.4; − Token Level Fuzzy Match -2.5; − Result Aware Query Repair -3.8; − Value Existence Guard -10.6.
Detection floor of the paired sign test (80% power at the observed 4–8% discordance): ≈5–6 points at n≈170, ≈3.5 at n≈400, ≈2 at n≈1,300, ≈2.4 pooled over 1,237.

## What each component is

Pipeline order: PLAN (one LLM call extracts every entity mention verbatim) → EXECUTE per mention (route the mention to schema fields, retrieve candidate values, verify) → GENERATE (evidence block injected into the shared Cypher prompt) → execution-guided correction. The rows below are the toggleable components; mention extraction, tool routing, evidence injection and the error-message retry are not ablated (removing the evidence block recovers the No Val Link baseline exactly).

| component | what it does | removing it (`switch`) | mechanism the ablation isolates |
|---|---|---|---|
| Adaptive Search Control | For a mention that no candidate cleanly matches, an LLM judge inspects the evidence for up to 3 rounds and returns one action: *done*, *deepen* (fetch more values from the searched fields, budget 5/3/1) or *switch to* a not-yet-searched name-like field. Mentions that already pass the clean-grounding check skip the loop. | initial retrieval only, no corrective rounds (`PLAN_EXEC_ESCALATE=0`) | recovery of routing misses and shallow retrieval; pays off where the alias/abbreviation still shares tokens with the canonical value (flight_accident, nba), not where it does not (healthcare medical synonyms). |
| select-or-abstain judge | One closed-list LLM call on mentions that fail the clean-grounding check: *select* the one candidate the mention denotes (evidence narrowed to it), *abstain* (evidence for that mention suppressed, generator writes the predicate unaided) or *keep* on a transient failure. It can only narrow or remove evidence, never add a value. | judge skipped, evidence passes through unchanged (`PLAN_EXEC_SELECT_JUDGE=0`) | filtering of long candidate lists in the abbreviation/alias region. |
| Levenshtein Retrieval | Server-side normalized edit-distance scan over the field's full value set (top 10), array-valued alias lists unwound and matched element-wise. | Token Level Fuzzy Match is the only retrieval arm (`RETRIEVAL_LEVENSHTEIN=0`) | character-level recall for dense typos and abbreviation-like codes that BM25 tokenization misses. |
| Token Level Fuzzy Match | The mention is split into word tokens and each token is matched, with a one-edit Lucene fuzzy operator, against the full-text index of the routed (label, property) field; a value matching any token is a hit, ranked by BM25 and re-ranked to the top 10. Index-backed, so its cost does not grow with the field. | Levenshtein Retrieval is the only retrieval arm (`RETRIEVAL_FUZZY=0`) | token-level recall for casing, mild typos and partial names; largely subsumed by Levenshtein Retrieval at these top-k. |
| Result Aware Query Repair | After a query executes, an LLM evaluator classifies its result against the question; any non-accept verdict triggers regeneration that keeps the full evidence block and adds the evaluator's feedback (≤4 rounds, anti-oscillation: first accepted attempt, else first executable one). | error-message retry only (`CYPHER_SEMANTIC_REPAIR=0`) | correction of executable-but-wrong queries with the grounding evidence still in the prompt. |
| Value Existence Guard | Final guard on the generated query: (label, property, value) literals in `=` and property-map predicates that do not exist in the database are mapped, by one closed-list LLM call over a fresh retrieval on that field, to an existing value; the substitution is adopted only if the query still runs. Existing values are never touched. | generated literals left as written (`PLAN_EXEC_VALUE_SNAP=0`) | the residual failure where the generator retrieved the right value but copied the question's corrupted surface form into the predicate. |

## Provenance

Backbone gpt-5.6-terra for every LLM stage; benchmark release v2.3 (questions restricted to those verbatim in `benchmarks/`); every graph runs in full; SHARDS=1; errored questions score 0. The full row is the released configuration: routing on node-property tools, select-or-abstain judge on, Token Level Fuzzy Match, Levenshtein Retrieval, Adaptive Search Control, Result Aware Query Repair and Value Existence Guard on. Runs: `logs/ablation_gpt-5.6-terra__judge-on-node/flight_accident__reference`, `logs/ablation_gpt-5.6-terra__judge-on-node/healthcare__reference`, `logs/ablation_gpt-5.6-terra__judge-on-node/pole_full__reference`, `logs/ablation_gpt-5.6-terra__judge-on-node/nba__reference` and the variant cells under `logs/ablation_gpt-5.6-terra__judge-on-node/`. Regenerate with `python scripts/tuning/score_ablation.py --model gpt-5.6-terra --ref judge-on --scope node --pole-full --paper`; per-category breakdowns are in `report/ablation_table_gpt-5.6-terra__judge-on-node-polefull.md`.

## Format conventions applied (ACL-style ablation table)

- One backbone, one metric (EA), the full system as the first row and one `− component` row per switch, grouped by pipeline stage in the order the method section introduces them.
- Δ in points relative to the full row; the full row carries the absolute score so readers can recover every variant's absolute EA.
- n per column in the header; a pooled column paired over all questions (micro); the macro-mean is stated in the text.
- Paired significance per cell (two-sided sign test on per-question flips), marked † / ‡, with the test and the detection floor stated in the caption or text.
- The main text carries the components with a significant pooled effect; the full table, including components without a measurable effect, goes to the appendix and is referenced from the main text.
- booktabs rules only (no vertical rules), `table*` width, `\small`; component definitions live in the method section, the table's first column only names them.
- The caption states data version, question counts, decoding (temperature 0, single run), the pairing, and which configuration the full row is.
