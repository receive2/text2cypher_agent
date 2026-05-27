# Data Augmentation Strategies

This file documents every entity-perturbation strategy implemented in
this module. It is the authoritative reference — if you add a new
strategy, update this file in the same commit.

The pipeline (`data_augmentation/pipeline.py::augment_nl`) extracts
entity spans from a question, samples a strategy per entity by weighted
random choice (`_strategy_order`, sampling without replacement so a
declined pick falls through), applies the perturbation, and records
each successful edit in `_aug_meta.edits[].strategy`. The strings in
the *Name* column below are exactly what gets written to that field.

## Strategy summary table

| Name         | Category              | Approach                                | Cost          | Deterministic |
| ------------ | --------------------- | --------------------------------------- | ------------- | ------------- |
| `casing`     | Surface / formatting  | Built-in `.lower()/.upper()/.title()`   | free          | stochastic (rng-shuffled variant order) |
| `partial`    | Token truncation      | Whitespace tokenise + drop leading/trailing N tokens (weighted) | free | stochastic |
| `abbrev`     | Abbreviation / alias  | Curated bidirectional dict + LLM fallback | free → LLM-API-cost | deterministic when dict hits; stochastic otherwise |
| `synonym`    | Nickname / colloquial | Curated dict (per-entry multi-candidate) + LLM fallback | free → LLM-API-cost | stochastic (random pick among candidates) |
| `paraphrase` | Descriptive scaffold  | LLM-only (no static fallback)           | LLM-API-cost  | stochastic |
| `typo`       | Typing noise          | `nlpaug` (Keyboard / RandomChar) → built-in 1-char swap fallback | free (cheap CPU) | stochastic |

---

## Per-strategy detail

### `casing`

- **What it does:** Re-cases the entity surface form to one of
  lower / UPPER / Title — whichever variant is the first (after random
  shuffle) to actually change the input.
- **Examples** (from `augmenters/casing.py` module docstring):
  - `"Sacramento Kings"` → `"sacramento kings"` (lower)
  - `"Sacramento Kings"` → `"SACRAMENTO KINGS"` (upper)
  - `"sacramento kings"` → `"Sacramento Kings"` (title)
- **Implementation:** `data_augmentation/augmenters/casing.py::CasingAugmenter.apply`,
  pure Python string methods.
- **Dependencies:** none.
- **Notes:** Declines on empty / whitespace-only input. The variant
  order is shuffled per call via `ctx.rng.shuffle` so multiple entities
  in the same row don't all flip to identical casing.

### `partial`

- **What it does:** Drops the leading or trailing N tokens
  (1 ≤ N < #tokens) from a multi-token entity surface form. Bias
  toward dropping a single token (weight = 1/(i+1)) so the perturbation
  stays close to natural usage.
- **Examples** (from `augmenters/partial_name.py` module docstring):
  - `"Los Angeles Lakers"` → `"Lakers"` (drop leading)
  - `"House Committee on Education and the Workforce"` → `"House Committee"` (drop trailing)
  - `"United States of America"` → `"United States"`
- **Implementation:** `data_augmentation/augmenters/partial_name.py::PartialNameAugmenter.apply`,
  whitespace tokeniser + weighted random `k` + coin flip for
  leading/trailing side.
- **Dependencies:** none (stdlib `re`).
- **Notes:** Declines on single-token entities (`len(toks) < 2`).
  Tokenisation is whitespace-only and preserves casing/punctuation.

### `abbrev`

- **What it does:** Compresses or expands an entity to its canonical
  acronym / short form via a curated bidirectional pair table; falls
  back to a single LLM call asking for the canonical short form when
  the dict misses and `ctx.llm.enabled` is True.
- **Examples** (from `augmenters/abbreviation.py` module docstring and `_PAIRS`):
  - `"United States of America"` → `"USA"`
  - `"Republican Party"` → `"GOP"`
  - `"NYC"` → `"New York City"` (reverse direction)
- **Implementation:** `data_augmentation/augmenters/abbreviation.py::AbbreviationAugmenter.apply`.
  Curated `_PAIRS` list (countries, supranational orgs, US politics, US
  federal agencies, tech companies, sports leagues, cities, adjectivals
  — ~50 pairs) is loaded once into a case-insensitive bidirectional
  dict by `_build_lookup`. Long-form keys always overwrite to their
  paired short form; short-form keys take the FIRST long form they were
  paired with (so `"US"` → `"United States"`, not `"American"`). LLM
  fallback is gated on `ctx.llm.enabled`, and the reply is rejected
  unless it is strictly shorter than the input and case-insensitively
  different.
- **Dependencies:** curated `_PAIRS` table in-file; optional
  `LLMClient` (via `ctx.llm`).
- **Notes:** Distinct from `synonym` — `abbrev` is specifically for
  acronyms/initialisms/short forms with the same referent, not
  colloquial nicknames or descriptive phrases.

### `synonym`

- **What it does:** Swaps the entity to a colloquial nickname or short
  descriptive phrase that points to the same referent without being a
  pure abbreviation. Curated dict path picks one of multiple candidate
  substitutions at random; LLM fallback asks for a colloquial form with
  strict validation against runaway paraphrases.
- **Examples** (from `augmenters/synonym.py` `_KNOWN_SYNONYMS`):
  - `"Sacramento Kings"` → `"the Kings"` or `"the Kings of Sacramento"`
  - `"Tom Hanks"` → `"the actor Tom Hanks"`
  - `"Los Angeles Lakers"` → `"the Lakers"` or `"LA Lakers"`
- **Implementation:** `data_augmentation/augmenters/synonym.py::SynonymAugmenter.apply`.
  Curated `_KNOWN_SYNONYMS` dict (NBA — all 30 teams; popular NFL/MLB/NHL
  teams; famous people with descriptive nominal phrasings; country /
  region colloquials; cities; tech orgs; US politics) maps lower-cased
  surface forms to a tuple of candidate substitutions; the augmenter
  picks one via `ctx.rng.choice`. LLM fallback gated on
  `ctx.llm.enabled`; reply is rejected if it equals the surface
  (case-insensitive), is `"NONE"`, or exceeds `max(4, 4 * len(surface.split()))`
  words (runaway-paraphrase guard).
- **Dependencies:** curated `_KNOWN_SYNONYMS` dict in-file; optional
  `LLMClient` (via `ctx.llm`).
- **Notes:** Explicitly distinct from `abbrev` (acronyms) and from
  `paraphrase` (which keeps the original entity string visible).
  Curated entries list `"Barack Obama" → ("former president Obama", "President Obama")`
  so this strategy can also produce honorific-prefixed forms.

### `paraphrase`

- **What it does:** Wraps a short descriptive paraphrase around the
  entity (typically keeping the original entity string visible inside
  the paraphrase). LLM-only — there is **no** static fallback;
  declines when `ctx.llm.enabled` is False.
- **Examples** (from `augmenters/paraphrase.py` module docstring):
  - `"Tom Hanks"` → `"the actor Tom Hanks"`
  - `"Sacramento Kings"` → `"the Kings of Sacramento"`
  - `"USA"` → `"the country known as the USA"`
- **Implementation:** `data_augmentation/augmenters/paraphrase.py::ParaphraseAugmenter.apply`,
  single LLM completion through `ctx.llm.complete` with `first_nonempty_line`
  parsing. Output is rejected if `"NONE"`, equal to surface
  (case-insensitive), or longer than `max(len(surface.split()) + 6, 4 * len(surface.split()))`
  words (runaway-paraphrase guard).
- **Dependencies:** `LLMClient` via `ctx.llm`. Hard LLM dependency.
- **Notes:** Distinguishes itself from `synonym` by **adding**
  descriptive scaffolding around the original entity string rather
  than replacing it with a different surface form.

### `typo`

- **What it does:** Injects a small amount of typing-noise into the
  entity surface — at most one or two character changes per entity —
  to simulate real-user keyboard slips.
- **Examples:** ⚠ The module docstring contains only a paraphrased
  example (`"Balretta"` instead of `"Barletta"`); no concrete dict or
  fixture is shipped. Constructed examples consistent with the
  `nlpaug.KeyboardAug` / `RandomCharAug` configuration in
  `augmenters/typo.py::_ensure_nlpaug`:
  - `"Barletta"` → `"Balretta"` *(constructed, per module docstring)*
  - `"Sacramento"` → `"Sxcramento"` *(constructed; KeyboardAug — adjacent-key slip)*
  - `"Lakers"` → `"Laekrs"` *(constructed; RandomCharAug `action="swap"` — finger-order slip)*
- **Implementation:** `data_augmentation/augmenters/typo.py::TypoAugmenter.apply`.
  Tries `_nlpaug_typo` first — picks `KeyboardAug` or `RandomCharAug`
  with equal probability (`ctx.rng.choice`), each configured with
  `aug_char_min=1, aug_char_max=1, aug_word_min=1, aug_word_max=1`,
  no special chars / numerics / uppercase. Falls back to `_builtin_typo`
  (a single adjacent-letter swap inside one random alphabetic word) when
  nlpaug is unavailable or the nlpaug call returned nothing usable.
- **Dependencies:** optional `nlpaug` package
  (`nlpaug.augmenter.char.KeyboardAug` + `RandomCharAug`); built-in
  fallback uses only stdlib. `loguru` for warnings.
- **Notes:** Declines on inputs shorter than 2 stripped characters.

---

## Strategies registered but not implemented

None — all 6 strategy names in `augmenters/__init__.py::STRATEGY_REGISTRY`
(`casing`, `partial`, `abbrev`, `synonym`, `paraphrase`, `typo`) have
matching `Augmenter` subclass implementations in
`data_augmentation/augmenters/`, and all 6 are referenced with positive
weights in both `config.py::DEFAULT_PROPORTIONS` and the runner's
`run_data_augmentation.py::AUG_PROPORTIONS`.

## Strategies implemented but not registered

None — every `Augmenter` subclass in `data_augmentation/augmenters/`
is wired into `STRATEGY_REGISTRY`.

## Strategy name strings observed in existing augmented datasets

Collected by walking each `~/datasets/*_augmented/` tree, parsing
every `.json` / `.jsonl` / `.csv` row's `_aug_meta.edits[].strategy`
field, and de-duplicating:

- `cypherbench_augmented`: `["abbrev", "casing", "paraphrase", "partial", "synonym", "typo"]`
- `mindthequery_augmented`: `["abbrev", "casing", "paraphrase", "partial", "synonym", "typo"]`
- `zograscope_augmented`: `[]`  ⚠ No `_aug_meta` data found.
  The CSV files under `~/datasets/zograscope_augmented/data/` have the
  source schema (`id, nl, mr, nl_gold_linked, nl_bracketed, entities,
  num_nodes, template_id, type, return_count`) and **no `_aug_meta`
  column**, even though `datasets/augment_zograscope.py` is wired to
  append one. Either the pipeline has not been run against zograscope
  since the augmented tree was populated, or the augmented tree was
  initialised from a verbatim copy. Re-run `run_data_augmentation.py`
  with `"zograscope"` in `DATASETS_TO_AUGMENT` (and `"train"` in
  `SPLITS_TO_AUGMENT` if you want the train CSV augmented too) to
  populate it.

## Cross-reference

| Strategy     | In `STRATEGY_REGISTRY` | In `config.DEFAULT_PROPORTIONS` | In runner `AUG_PROPORTIONS` | Seen in cypherbench_augmented | Seen in mindthequery_augmented | Seen in zograscope_augmented |
| ------------ | :-: | :-: | :-: | :-: | :-: | :-: |
| `casing`     | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ (file has no `_aug_meta`) |
| `partial`    | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ (file has no `_aug_meta`) |
| `abbrev`     | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ (file has no `_aug_meta`) |
| `synonym`    | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ (file has no `_aug_meta`) |
| `paraphrase` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ (file has no `_aug_meta`) |
| `typo`       | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ (file has no `_aug_meta`) |

No registry / config drift. The only flag is that
`zograscope_augmented` does not appear to contain pipeline output —
see note above.
