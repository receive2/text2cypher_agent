# Unchecked-edit backfill — results (2026-08-09)

Tool: `scripts/backfill_unchecked_validity.py` (read-only; graphs on the eval VM).
Input: the 356 v2 edits that shipped `validity="unchecked"` (generation-time
(label,prop) resolution failed, so collision/uniqueness/margin never ran).
Resolution fallback: locate the canonical value across ALL node/rel scalar AND
array string properties, then re-run `data_augmentation.validity.check_validity`
in every matching context (conservative: must pass all).

## Outcome

| result | n | disposition |
|---|--:|---|
| auto_ok_casing | 37 | keep (identity-preserving) |
| **ok_backfilled** | 110 | keep; flip `validity` to `ok(backfilled)` |
| **unresolved** | 209 | **recommend drop** (see classes below) |

No edit that resolved FAILED its checks (fail=0) — everything resolvable passed.
The unresolved are not check-failures; they are **entity-pool leaks**: the
"entity" never was a stored DB value, which is also *why* (label,prop)
resolution failed at generation time.

## The 209 unresolved, by leak class

| class | n | examples | why it leaked |
|---|--:|---|---|
| dates/datetimes (excluded by design) | 10 | 'August 25, 2017'→'2017' | type-filter never ran (label/prop unresolved) |
| structured IDs / descriptor phrases (excluded by design) | 136 | 'NHS number 554-93-4466'→'554-93-4466' | type-filter never ran (label/prop unresolved) |
| schema words (labels/rel-types) & common nouns — not entities | 32 | 'AccountHolders'→typo; 'IS_PRIMARY_SUSPECT'→'Prime Suspect' | type-filter never ran (label/prop unresolved) |
| CONTAINS-fragment literals (domains) | 8 | 'gmail.com'→'gmmail.com' | type-filter never ran (label/prop unresolved) |
| unmatched — likely unicode/format drift; hand-check | 23 | 'NBA'→'National Basketball Association'; 'Gaudí Award…' | type-filter never ran (label/prop unresolved) |

Source split of the 209: {'llm': 24, 'algorithmic': 181, 'kb:curated': 4} — 28 would reach human census anyway
(llm/kb), 181 are algorithmic with **no human backstop** (the
census/sample design assumed DB checks covered them).

## Recommended actions

1. **Drop all 209** from the v2 dataset (or drop A–D = 186 and hand-check the 23 E-class). They are out-of-scope
   per the redesign's own entity-pool rules (dates/IDs excluded; non-entities
   excluded) — this is documented curation, not data loss: log in DATASHEET.
2. **Flip the 110 ok_backfilled + 37 casing to `validity=ok`** in `_aug_meta`.
3. **Root cause** for the paper/notes: the generation-time extractor missed
   (a) relationship-property & array-property values, (b) type-filtering for
   spans it could not resolve — fixed here post-hoc; a v2.1 regen should apply
   the same fallback at generation time.
4. Re-run `verification_sample.py` after the drop so the annotation queue
   excludes dropped rows.
