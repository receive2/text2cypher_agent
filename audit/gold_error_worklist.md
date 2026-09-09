> **STATUS: DESCOPED (advisor decision, 2026-08).** Gold fixing is NOT being done —
> scope is annotation-only. This file is kept as a record. The 79 golds remain in
> the benchmark and score 0 for every method (assumption-free eval). Recommended
> follow-up is a single datasheet sentence noting them, nothing more.

# Gold-error worklist (79 broken golds → 7 root-cause clusters)

Actionable companion to `audit/gold_errors.jsonl`. Produced by clustering the 79
broken Mind-the-Query golds by **root cause** so they can be fixed in a few
batch passes instead of 79 one-offs. Row-level detail (qid, error, gold) is in
`audit/gold_error_worklist.csv`.

**Principle unchanged** (see `docs/GOLD_ERROR_AUDIT.md`): all edits happen in the
**dataset source** (`MINDTHEQUERY_AUGMENTED_PATH` in `eval_config.py`), never in
eval code. Every fix/removal is logged in `docs/DATASHEET.md`.

All 79 are in Mind-the-Query: **covid 59, wwc 12, healthcare 5, er 3**
(CypherBench and ZOGRASCOPE/pole have 0).

## Clusters

| id | n | kind | root cause | proposed action |
|---|--:|---|---|---|
| **C** | 20 | mechanical | `distance(...)` removed in Neo4j 5 | find/replace `distance(` → `point.distance(` |
| **D** | 4 | mechanical | `datetime("…T..:.. UTC")` won't parse | drop ` UTC` / convert to ISO-8601 offset (`…T00:00:00Z`) |
| **B** | 19 | review | `v.duration.seconds` reported unknown/undefined | confirm `Visit.duration` is a Duration type; in 5.x the component access `v.duration.seconds` is valid — if the property name differs, fix per schema |
| **A** | 4 | review | `duration.seconds(a,b)` is not a real function | rewrite to `duration.between(a,b).seconds` / `duration.inSeconds(...)`; verify semantics |
| **E** | 3 | review | `duration(p,pl)` wrong arg count | intent is a difference of two datetimes → `duration.between(t1,t2)`; rewrite per question |
| **F** | 8 | review | undefined variable (WITH scope dropped) | variable not carried through `WITH`; add it or restructure |
| **Z** | 21 | review | mixed / other syntax | inspect case by case: genuine bug vs 4→5 dialect |

**24 mechanical** (C + D) can be transpiled and re-tested in one batch.
**55 review** (A, B, E, F, Z) need a human to read the query and decide
transpile-vs-rewrite-vs-remove.

## Workflow (per `docs/GOLD_ERROR_AUDIT.md`)

1. **Batch the mechanical fixes (C, D).** Apply the transpile to the MtQ source
   golds, run each against the live covid/wwc/healthcare/er graph
   (cypher-shell / Browser), confirm it returns rows.
2. **Review clusters A, B, E first** — they cluster around covid's
   `duration`/time handling and may share one fix. Decide the canonical
   rewrite, apply to all members, re-test.
3. **F (undefined variable) and Z (other)** — case by case. Some are genuine
   authoring bugs → hand-write a correct gold if the question is sound, else
   **remove the example** (a question with no valid gold tests nothing).
4. **Rule out our environment first** for anything that smells like schema
   (missing label/property) or `timeout` — confirm the right graph is loaded
   (`verify_setup.py`) and the timeout cap is adequate before blaming the gold.
5. **Re-audit**: `python audit_gold_errors.py --graph covid` (etc.); the count
   should fall toward 0.
6. **Log every fixed/removed qid + reason in `docs/DATASHEET.md`.**

## Note for the plan

This is **not on the human-verification critical path** — it is an independent
dataset-quality track (gold *executability*), orthogonal to entity-perturbation
*validity*. It can proceed in parallel with, or after, the annotation effort.
It does affect the **clean/perturbed EA numbers** (broken golds score 0 for every
method), so it should be closed before the final results tables are frozen.
