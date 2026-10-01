# Component ablation of CyANCHOR — paper tables (gpt-5.6-terra)

Execution accuracy (EA, %) of the full system, and the change in EA points when one component is removed. Each cell is a single run at temperature 0, paired per question with the full-system run on the same questions; † / ‡ = two-sided paired sign test p < 0.05 / p < 0.01. Pooled = all questions of the 4 graphs, paired the same way. `− Levenshtein Retrieval` and `− Token Level Fuzzy Match` leave the other arm as the only retrieval arm. The full-system run has every component on (select-or-abstain judge on, node + relation tools); the released default routes on node-property tools only, which is the `− relation tools` row.

## Main-text table

Rows of the full table whose pooled effect is significant (p < 0.05).

| | flight_accident (n=168) | healthcare (n=418) | pole (n=400) | nba (n=251) | pooled (n=1,237) |
|---|---:|---:|---:|---:|---:|
| **CyANCHOR (full)** | 86.3 | 70.1 | 35.8 | 78.5 | 62.9 |
| *Grounding loop* | | | | | |
| − Adaptive Search Control | −9.5‡ | +0.2 | −2.2 | −8.8‡ | −3.7‡ |
| *Retrieval arms* | | | | | |
| − Levenshtein Retrieval | −4.8 | −6.2‡ | −4.5‡ | −11.2‡ | −6.5‡ |
| *Post-generation correction* | | | | | |
| − Result Aware Query Repair | −3.6 | −2.6 | −4.5‡ | −4.4 | −3.7‡ |
| − Value Existence Guard | −2.4 | −10.8‡ | −18.0‡ | −6.0‡ | −11.0‡ |

## Full table (appendix)

| | flight_accident (n=168) | healthcare (n=418) | pole (n=400) | nba (n=251) | pooled (n=1,237) |
|---|---:|---:|---:|---:|---:|
| **CyANCHOR (full)** | 86.3 | 70.1 | 35.8 | 78.5 | 62.9 |
| *Grounding loop* | | | | | |
| − Adaptive Search Control | −9.5‡ | +0.2 | −2.2 | −8.8‡ | −3.7‡ |
| − select-or-abstain judge | +0.6 | +0.7 | −2.0 | −0.4 | −0.4 |
| − relation tools | +2.4 | +0.7 | −0.3 | −0.8 | +0.3 |
| *Retrieval arms* | | | | | |
| − Levenshtein Retrieval | −4.8 | −6.2‡ | −4.5‡ | −11.2‡ | −6.5‡ |
| − Token Level Fuzzy Match | −0.6 | +0.0 | −1.7 | +0.0 | −0.6 |
| *Post-generation correction* | | | | | |
| − Result Aware Query Repair | −3.6 | −2.6 | −4.5‡ | −4.4 | −3.7‡ |
| − Value Existence Guard | −2.4 | −10.8‡ | −18.0‡ | −6.0‡ | −11.0‡ |

## Paired flips behind each cell (questions gained / lost relative to the full run, sign-test p)

| | flight_accident (n=168) | healthcare (n=418) | pole (n=400) | nba (n=251) | pooled (n=1,237) |
|---|---|---|---|---|---|
| − Adaptive Search Control | 2/18, p=0.0004 | 11/10, p=1 | 8/17, p=0.11 | 5/27, p=0.00011 | 26/72, p=3.7e-06 |
| − select-or-abstain judge | 6/5, p=1 | 20/17, p=0.74 | 13/21, p=0.23 | 13/14, p=1 | 52/57, p=0.7 |
| − relation tools | 12/8, p=0.5 | 12/9, p=0.66 | 15/16, p=1 | 11/13, p=0.84 | 50/46, p=0.76 |
| − Levenshtein Retrieval | 8/16, p=0.15 | 19/45, p=0.0016 | 6/24, p=0.0014 | 5/33, p=4.3e-06 | 38/118, p=9.7e-11 |
| − Token Level Fuzzy Match | 9/10, p=1 | 12/12, p=1 | 12/19, p=0.28 | 13/13, p=1 | 46/54, p=0.48 |
| − Result Aware Query Repair | 4/10, p=0.18 | 13/24, p=0.099 | 7/25, p=0.0021 | 10/21, p=0.071 | 34/80, p=2e-05 |
| − Value Existence Guard | 5/9, p=0.42 | 16/61, p=2.4e-07 | 4/76, p=2.8e-18 | 7/22, p=0.0081 | 32/168, p=1.8e-23 |

Macro-mean Δ over the 4 graphs (unweighted): − Adaptive Search Control -5.1; − select-or-abstain judge -0.3; − relation tools +0.5; − Levenshtein Retrieval -6.7; − Token Level Fuzzy Match -0.6; − Result Aware Query Repair -3.8; − Value Existence Guard -9.3.
Detection floor of the paired sign test (80% power at the observed 4–8% discordance): ≈5–6 points at n≈170, ≈3.5 at n≈400, ≈2 at n≈1,300, ≈2.4 pooled over 1,237.

## What each component is

Pipeline order: PLAN (one LLM call extracts every entity mention verbatim) → EXECUTE per mention (route the mention to schema fields, retrieve candidate values, verify) → GENERATE (evidence block injected into the shared Cypher prompt) → execution-guided correction. The rows below are the toggleable components; mention extraction, tool routing, evidence injection and the error-message retry are not ablated (removing the evidence block recovers the No Val Link baseline exactly).

| component | what it does | removing it (`switch`) | mechanism the ablation isolates |
|---|---|---|---|
| Adaptive Search Control | For a mention that no candidate cleanly matches, an LLM judge inspects the evidence for up to 3 rounds and returns one action: *done*, *deepen* (fetch more values from the searched fields, budget 5/3/1) or *switch to* a not-yet-searched name-like field. Mentions that already pass the clean-grounding check skip the loop. | initial retrieval only, no corrective rounds (`PLAN_EXEC_ESCALATE=0`) | recovery of routing misses and shallow retrieval; pays off where the alias/abbreviation still shares tokens with the canonical value (flight_accident, nba), not where it does not (healthcare medical synonyms). |
| select-or-abstain judge | One closed-list LLM call on mentions that fail the clean-grounding check: *select* the one candidate the mention denotes (evidence narrowed to it), *abstain* (evidence for that mention suppressed, generator writes the predicate unaided) or *keep* on a transient failure. It can only narrow or remove evidence, never add a value. | judge skipped, evidence passes through unchanged (`PLAN_EXEC_SELECT_JUDGE=0`) | filtering of long candidate lists in the abbreviation/alias region. |
| relation tools | Relationship-type tools in the routing index. In CyANCHOR a relation mention retrieves no values; it only contributes its traversal pattern `(:A)-[:rel]->(:B)` as a hint to the generator. | routing over node-property tools only, no pattern hint (`CYANCHOR_TOOL_SCOPE=node`) | value of the relation-pattern hint; the perturbed entities never live on relationship properties, and the hint repeats what the schema block already states. |
| Levenshtein Retrieval | Server-side normalized edit-distance scan over the field's full value set (top 10), array-valued alias lists unwound and matched element-wise. | Token Level Fuzzy Match is the only retrieval arm (`RETRIEVAL_LEVENSHTEIN=0`) | character-level recall for dense typos and abbreviation-like codes that BM25 tokenization misses. |
| Token Level Fuzzy Match | The mention is split into word tokens and each token is matched, with a one-edit Lucene fuzzy operator, against the full-text index of the routed (label, property) field; a value matching any token is a hit, ranked by BM25 and re-ranked to the top 10. Index-backed, so its cost does not grow with the field. | Levenshtein Retrieval is the only retrieval arm (`RETRIEVAL_FUZZY=0`) | token-level recall for casing, mild typos and partial names; largely subsumed by Levenshtein Retrieval at these top-k. |
| Result Aware Query Repair | After a query executes, an LLM evaluator classifies its result against the question; any non-accept verdict triggers regeneration that keeps the full evidence block and adds the evaluator's feedback (≤4 rounds, anti-oscillation: first accepted attempt, else first executable one). | error-message retry only (`CYPHER_SEMANTIC_REPAIR=0`) | correction of executable-but-wrong queries with the grounding evidence still in the prompt. |
| Value Existence Guard | Final guard on the generated query: (label, property, value) literals in `=` and property-map predicates that do not exist in the database are mapped, by one closed-list LLM call over a fresh retrieval on that field, to an existing value; the substitution is adopted only if the query still runs. Existing values are never touched. | generated literals left as written (`PLAN_EXEC_VALUE_SNAP=0`) | the residual failure where the generator retrieved the right value but copied the question's corrupted surface form into the predicate. |

## Provenance

Backbone gpt-5.6-terra for every LLM stage; benchmark release v2.3 (questions restricted to those verbatim in `benchmarks/`); pole uses its first 400 questions in release order (the prefix has the category mix of the whole graph), the other graphs run in full; SHARDS=1; errored questions score 0. The full-system run has every component on (select-or-abstain judge on, node + relation tools); the released default routes on node-property tools only, which is the `− relation tools` row. Runs: `logs/ablation_gpt-5.6-terra/flight_accident__reference`, `logs/ablation_gpt-5.6-terra/healthcare__reference`, `logs/ablation_gpt-5.6-terra/pole__reference`, `logs/ablation_gpt-5.6-terra/nba__reference` and the variant cells under `logs/ablation_gpt-5.6-terra/`. Regenerate with `python scripts/tuning/score_ablation.py --model gpt-5.6-terra --paper`; per-category breakdowns are in `report/ablation_table_gpt-5.6-terra.md`.

## Format conventions applied (ACL-style ablation table)

- One backbone, one metric (EA), the full system as the first row and one `− component` row per switch, grouped by pipeline stage in the order the method section introduces them.
- Δ in points relative to the full row; the full row carries the absolute score so readers can recover every variant's absolute EA.
- n per column in the header; a pooled column paired over all questions (micro); the macro-mean is stated in the text.
- Paired significance per cell (two-sided sign test on per-question flips), marked † / ‡, with the test and the detection floor stated in the caption or text.
- The main text carries the components with a significant pooled effect; the full table, including components without a measurable effect, goes to the appendix and is referenced from the main text.
- booktabs rules only (no vertical rules), `table*` width, `\small`; component definitions live in the method section, the table's first column only names them.
- The caption states data version, question counts, decoding (temperature 0, single run), the pairing, and which configuration the full row is.
