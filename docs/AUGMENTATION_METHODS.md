# Appendix: Entity-Perturbation Augmentation Methodology

This appendix specifies exactly how each perturbation category is produced and
validated. It is written to be self-contained for review. Notation: for a
question *q* with gold Cypher *C*, an **entity** is a string literal *v* in *C*
(the canonical database value) that also occurs in *q*; an augmentation rewrites
exactly one occurrence-set of one entity in *q* into a perturbed surface *v′*,
leaving *C* (and therefore the gold answer) unchanged.

## A.1 Entity identification and typing

1. **Extraction.** We parse single/double-quoted string literals from *C* and
   keep those that occur (case-insensitively) in *q*. The literal is anchored to
   its character span(s) in *q*.
2. **(label, property) resolution.** For each literal we recover the graph
   `(label, property)` it is compared against in *C* (e.g. `x.surname = "Hanson"`
   → `(Person, surname)`; `{name: 'Natara'}` → label from the nearest pattern
   binding). This scopes the validity checks (§A.5).
3. **Type filter.** A literal is augmentable only if `classify_entity` labels it
   `name`. Dates, times, emails, and structured identifiers/postcodes (e.g.
   `6/08/2017`, `00:52`, `a@b.com`, `770-22-6561`, `WN5`) are excluded: they are
   exact-lookup keys with no world-knowledge variant, and they are collision-dense
   (a one-character change frequently lands on *another* valid code, silently
   corrupting the gold answer). The same filter applies to the optional LLM
   entity-extraction fallback used when literal extraction yields nothing.

## A.2 The perturbation mixture and its control

We target a **balanced mixture** over five categories: `casing` 10%, and
`typo`/`partial`/`abbrev`/`alias` 22.5% each. `casing` is held low as a
difficulty floor / control; the four informative categories are equal to give
uniform per-category statistical power and to avoid weighting the benchmark
toward any category a grounding system is best at.

Per question, the category is chosen by a **deficit-greedy quota sampler**: among
the categories *eligible* for some entity in the question, it tries them in order
of `target_share − realized_share` (largest deficit first, with a tiny random
tie-break) and commits the first that yields a *valid* edit (§A.5). Two rules:

- **Casing cap.** `casing` is removed from contention once its realized share
  reaches its 10% target, so when an informative category is supply-starved on a
  domain (e.g. `abbrev` where entities have no abbreviations) the surplus flows
  to the other informative categories, never to the trivial control.
- **Drop, never substitute.** If no eligible category yields a valid edit for a
  question, the question is dropped and the reason recorded — it is never
  silently replaced by a trivial casing edit (the failure mode that let
  casing/paraphrase dominate the pre-redesign data).

Consequently the realized per-graph mixture is balanced where the informative
categories have supply, and honestly skews toward `typo`/`partial` on domains
whose entities lack abbreviations/aliases; we report the per-graph mixture rather
than forcing variants that do not exist.

## A.3 The five categories

Each category below is specified as: **definition → grounding challenge →
generation procedure → category-specific validity → examples → provenance**.

### A.3.1 `casing` — surface re-casing (control / floor)

- **Definition.** Re-case the entity to all-lower or all-UPPER.
- **Challenge.** Trivial: a case-insensitive exact match still recovers it. It
  calibrates the difficulty scale (its grounding gap should be ≈0 on a
  case-insensitive backend).
- **Procedure.** Try `lower()` and `upper()` in random order; emit the first that
  changes the string. (`title()` is deliberately not used — it mangles
  apostrophes, e.g. `Night's → Night'S`, an artifact no user produces.)
- **Validity.** Collision check only (§A.5).
- **Examples.** `Sacramento Kings → SACRAMENTO KINGS`; `Jean Grey → jean grey`.
- **Provenance.** Algorithmic; never flagged for verification.

### A.3.2 `typo` — single keyboard-slip

- **Definition.** Inject exactly one realistic typing error.
- **Challenge.** Breaks exact match; recoverable by edit-distance / fuzzy search.
- **Procedure.** In-house generator (no external library, for reproducibility).
  On a randomly chosen word with an alterable (non-initial alphabetic) position,
  apply one of: **keyboard substitution** (replace a letter with a QWERTY-adjacent
  letter), **adjacent transposition** (swap two neighbouring letters),
  **deletion**, or **doubling**. Word-initial characters are never altered
  (entity recognition anchors on them, so a leading-character change is a
  different entity, not a typo). Requires ≥3 stripped characters; up to 6
  attempts to land a non-empty change.
- **Validity.** Damerau-Levenshtein margin (§A.5): the canonical value must remain
  the **unique** database value within Damerau distance 1 of *v′*; if any *other*
  value is within distance 1, the edit is rejected (this is what blocks the
  `WN5 → NW5` class where a transposition lands on a different real value).
  Distance is **Damerau** (adjacent transposition costs 1), not plain Levenshtein
  — the pre-redesign bug used Levenshtein, which scored transpositions as 2 and
  rejected essentially all typos.
- **Examples.** `Barletta → Balretta` (transposition); `Sacramento → Sxcramento`
  (keyboard); `Buddy Hield → Buddy Hiel` (deletion).
- **Provenance.** Algorithmic; never flagged.

### A.3.3 `partial` — token reduction

- **Definition.** Drop word(s), keeping a contiguous fragment that still denotes
  the entity (the natural way users shorten multi-word names).
- **Challenge.** Breaks exact match; recoverable by substring / partial matching.
- **Procedure (hybrid).** Generate conservative candidates and keep the first that
  resolves uniquely (below): **suffix reductions** (drop leading modifiers,
  shortest first — a single-token reduction is allowed only if it keeps the *last*
  token, the usual English head) and **prefix reductions** of length ≥2 (keep a
  leading head phrase). Candidates that start/end on a stopword are rejected. If
  no algorithmic candidate resolves uniquely, fall back to an **LLM proposer**
  (gpt-4.1) constrained to output only words already present in the name (a
  subset, not a rephrase); this is flagged for verification.
- **Validity.** Uniqueness (§A.5): the reduced surface, by case-insensitive
  containment over the `(label, property)` value set, must match the canonical
  value and **no other**. (This rejects `Los Angeles → Los Angeles Lakers` when
  `Los Angeles Clippers` also exists.)
- **Examples.** `Los Angeles Lakers → Lakers`; `North American P-51 Mustang →
  Mustang`; `Bob Lanier → Lanier`. The single-token-must-be-the-head rule blocks
  the over-reductions `shooting guard → shooting` and `ACB ... Award → ACB`.
- **Provenance.** Algorithmic where possible (`algorithmic`); LLM fallback
  flagged.

### A.3.4 `abbrev` — acronym / short form

- **Definition.** Replace the entity with its acronym/initialism/short form (or,
  bidirectionally, expand a short form).
- **Challenge.** Often little/no surface overlap → requires world knowledge.
- **Procedure (two tiers).**
  1. **Attested (model-free, not flagged).** (a) a curated bidirectional table of
     well-known acronyms (countries, international organisations, agencies, sports
     leagues, plus policing ranks for the synthetic policing graph); (b) the
     entity's Wikidata aliases (shipped with the CypherBench graphs) filtered to
     acronym-like forms (all-caps short token, or letters equal to the name's
     initials).
  2. **LLM proposer (only if no attested form; flagged).** A **two-stage** prompt:
     stage 1 *judges* whether a widely-recognised abbreviation exists (YES/NO);
     only on YES does stage 2 *produce* it. The output must be strictly shorter,
     differ from the surface, and contain at most one space. Splitting judge from
     produce suppresses the model's tendency to invent a plausible-but-unknown
     acronym.
- **Validity.** Collision check (§A.5): the abbreviation must not equal a
  *different* value of the same `(label, property)`.
- **Examples.** `United States of America → USA` (curated); `Custom Coasters
  International → CCI` (Wikidata); `Golden State Warriors → GSW`, `shooting guard
  → SG` (LLM, then verified).
- **Provenance.** Attested forms `kb:curated` / `kb:simplekg` (trusted); LLM forms
  `llm` (flagged). Reliability is discussed in §A.6.

### A.3.5 `alias` — replacement nickname / brand–generic

- **Definition.** Replace the entity with a *different* name for the same referent
  (nickname, colloquial, or brand↔generic), with little or no surface overlap.
- **Challenge.** The hardest tier — essentially zero surface overlap, so only
  world knowledge / semantic (vector) grounding recovers it.
- **Eligibility guards.**
  - **Synthetic domains off.** On fabricated graphs (`pole`, `bloom`, `er`) the
    category is disabled: an LLM asked to alias a fabricated surname hallucinates a
    real-world entity (the pre-redesign `Wagner → the Wagner Group` corruption).
  - **Closed-set guard.** For the LLM fallback only, if the entity's
    `(label, property)` has ≤30 distinct values (a small enumerable category such
    as divisions, conferences, positions, awards), the LLM is not asked — forced
    to alias an enumerable category it swaps siblings (`Central Division → Midwest
    Division`) or hallucinates. Attested/curated aliases for such sets are still
    used.
- **Procedure.** Prefer **attested** aliases (Wikidata non-acronym aliases;
  curated nickname table incl. position slang; optional RxNorm brand↔generic for
  drugs), keeping only candidates that do **not** contain the original verbatim
  (enforcing replacement, the inverse of the pre-redesign "substring-survives"
  rule that had degenerated `alias` into paraphrase). Otherwise an **LLM
  proposer** (flagged) under the same "must not contain the original" and a
  runaway-length cap.
- **Validity.** Collision check (§A.5).
- **Examples.** `United Kingdom → Britain`; `Tocilizumab → Actemra` (brand);
  `Chicago Bulls → the Bulls`; `shooting guard → the two guard` (curated slang).
- **Provenance.** Attested `kb:*` (trusted); LLM `llm` (flagged).

## A.4 Validity gates (shared, database-grounded, model-free)

Every candidate edit is checked against the live graph — never by an LLM and
never by the system under test. Let *V* be the set of distinct values of the
entity's `(label, property)`.

- **Collision (all categories).** Reject if *v′* equals (case-insensitively) a
  value in *V* other than the canonical *v*. Prevents an edit from silently
  denoting a *different* existing entity.
- **Uniqueness (`partial`).** Reject unless exactly one value of *V* contains *v′*
  (case-insensitive), and it is *v*.
- **Margin (`typo`).** Reject if any value other than *v* lies within Damerau
  distance 1 of *v′*.
- **Splice grammar guard (all).** When *v′* is spliced into *q*, repair the seam:
  drop a duplicated article (`... the <the X> → ... the X`), fix `a/an` agreement,
  and remove word-doubling at either boundary; if a new duplication cannot be
  cleaned, the edit is declined. All occurrences of the entity in *q* are replaced
  consistently.

## A.5 Provenance and human verification

Each edit records its `source`: `algorithmic`, `kb:curated`, `kb:simplekg`,
`kb:rxnorm`, or `llm`. **Only `llm`-sourced edits are flagged
`needs_verification`.** Algorithmic and attested-source edits are trusted by
construction; LLM proposals are 100% human-verified (not sampled) against two
questions: (i) does the perturbed mention still uniquely denote the original
entity / preserve the gold answer? (ii) is it a plausible real-user surface form?
Verdicts (keep / fix / drop) are applied before release. (In the v2.1 freeze,
916 of the 4,641 edits are LLM-proposed; all 916 are queued for the
double-annotated census.) In the verified v2.2 release, 25 of the 898
measured LLM edits were rejected (19 reverted to certified prior algorithmic
forms, 6 removed), 3 were removed as source errors and 9 as unnatural;
see `docs/VERIFICATION_PROTOCOL.md` §6.

## A.6 On the reliability of LLM-proposed forms

LLMs only *propose*; correctness is decided by the validity gates and human
verification. Empirically, proposal precision differs sharply by category, which
the design reflects: abbreviations are largely deterministic (initials or
standardised short forms with a single correct answer) and the two-stage judge +
collision check make them high-precision; aliases require specific world
knowledge and are the noisiest (sibling-swaps, invented nicknames for obscure
entities), which is exactly why the closed-set and synthetic-domain guards and
the human-verification backstop concentrate there.

## A.7 Reproducibility

Per-question randomness is seeded from `(seed, dataset, row_id)` (so adding or
removing a source row does not reshuffle others); generation only **reads** the
graph database; the proposer model is pinned (gpt-4.1; the exact snapshot should
be recorded at release). One edit per question (`MAX_EDITS_PER_ROW = 1`).

## A.8 Difficulty annotation

Independently of any model and without the database, each edit is classified by
the surface↔canonical relationship: `exact_ci` (case-insensitively equal —
trivial), `edit_distance` (Damerau ≤2), `substring` (perturbed is a substring of
the canonical), else `semantic` (no surface overlap — requires world
knowledge/vector grounding). This yields an objective difficulty spectrum and the
"grounding gap" (fraction on which case-insensitive exact match fails).

## A.9 Limitations (for transparency)

- The **curated abbreviation/alias tables are hand-written and small** (≈19
  acronym pairs + a short nickname/slang table); they are a supplement to the
  primary attested source (Wikidata aliases shipped with the CypherBench graphs),
  not a systematically-sourced authority. A stronger, fully-citable variant would
  derive them from Wikidata's *short name* property (P1813) and standard
  domain glossaries.
- On domains whose entities lack abbreviations/aliases (e.g. fictional characters,
  contact-tracing places, synthetic graphs), the realized mixture is
  `typo`/`partial`-heavy by supply rather than balanced.
- `fulltext`/`vector` difficulty ranks are not computed (the benchmark graphs
  ship without those indexes); the §A.8 class spectrum is index-free.
- The closed-set guard uses a fixed threshold (≤30 distinct values) as a heuristic
  for "enumerable category".
