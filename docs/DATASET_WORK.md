# Augmented-Dataset Work — Master Reference

Self-contained record of the entity-perturbed text2cypher benchmark work, so it
survives loss of chat history. Last updated 2026-06-14.

**Sibling docs:** [`AUGMENTATION_REDESIGN.md`](AUGMENTATION_REDESIGN.md) = the
plan & decisions; [`DATASHEET.md`](DATASHEET.md) = the release-facing dataset
description; [`REVIEW_GUIDE.md`](REVIEW_GUIDE.md) = human-verification
instructions; [`GRAPHS.md`](GRAPHS.md) / [`DEPLOY_LOG.md`](DEPLOY_LOG.md) = the
graph DB deployment.

---

## 1. What this is and why

The paper (NAACL) argues existing text2cypher benchmarks are unrealistically
clean — the entity a user mentions matches a graph value verbatim — so exact
matching succeeds and accuracy is overstated. We perturb the **entity mention**
in each test question (leaving the gold Cypher / answer unchanged) to create a
**grounding gap** that a value-grounding NER step must close. The perturbed
datasets are a paper contribution.

**Proven headline:** across 4,875 perturbed examples, baseline case-insensitive
exact-match no longer recovers the canonical entity on **89.9%** of them.

## 2. Why the old augmented data was thrown out (audit, 2026-06-11)

All three shipped `*_augmented` sets were unusable; archived to
`~/datasets/_archive_augmented_pre_redesign_20260613/`. Findings:

- Distribution collapsed (casing+paraphrase ~90% on cypherbench; typo 0%) — the
  old "first-success fallback" let always-succeeding strategies absorb the
  share of declining ones.
- `_validate_edit` contradicted the strategies it gated (plain Levenshtein
  rejected typo transpositions; "substring survives" killed replacement aliases).
- Referent corruption: `Wagner`→"the Wagner Group", `Hanson`→"the band Hanson"
  (synthetic surnames → real entities); UK dates re-read US-style; `WN5`→`NW5`
  (typo collided with another real value).
- Splice artifacts ("the the X"), dates/IDs perturbed, three pipeline eras mixed
  (not comparable), three inconsistent proportion tables.

## 3. Design principles

1. **LLMs propose, never judge.** Validity is decided by construction, the DB,
   attested aliases, and human verification — never an LLM, never the system
   under test. (Kills the circularity objection even though the eval uses many
   LLMs.)
2. **The DB is the oracle.** Each entity comes from a gold-Cypher literal, so
   the canonical value is known; every edit is checked against the graph
   (collision / uniqueness / margin).
3. **Each category is a measured difficulty rung** (casing floor → semantic
   crown); a DB-free probe records the difficulty per edit.
4. **Honest accounting.** One proportion source; realized distribution + drop
   reasons reported per graph; deviations explained by supply, not hidden.
5. **Reproducible.** Per-row seeding from stable IDs; generation only *reads*
   the DB; pinned proposer model.

## 4. Architecture (module map)

```
data_augmentation/
  config.py            knobs: PROPORTIONS, CAPPED_STRATEGIES, SYNTHETIC_GRAPHS,
                       ALIAS_CLOSED_SET_MAX, AUGMENTABLE_ENTITY_TYPES, gpt-4.1
  entity_extractor.py  extract entity from gold-Cypher literal + (label,prop);
                       classify_entity() filters dates/times/emails/IDs
  validity.py          Damerau metric; ValueProvider (InMemory + Neo4j);
                       check_validity (collision/uniqueness/margin); splice guard
  kb_aliases.py        AliasProvider: CypherBench Wikidata aliases + curated
                       acronym/nickname tables (+ RxNorm hook); abbrev vs alias
  providers.py         build_providers(dataset, graph[, conn_graph]) →
                       (Neo4jValueProvider, AliasProvider); driver cache
  pipeline.py          augment_nl(); QuotaSampler (deficit-greedy + casing cap);
                       replace-all-occurrences; row_rng() per-row seeding
  augmenters/
    base.py            Augmenter ABC; EditProposal (surface, source, needs_verif)
    casing.py          lower/UPPER only (no .title() apostrophe artifact)
    typo.py            in-house keyboard/transpose/delete/double; never word-init
    partial_name.py    head-preserving reductions (algorithmic) + LLM fallback
    abbreviation.py    attested abbrevs → LLM proposer (flagged)
    alias.py           attested aliases → LLM proposer (flagged); closed-set +
                       synthetic-domain guards
  datasets/            legacy production adapters (cypherbench/mtq/zograscope)
scripts/
  stage_augment.py     dry-run one graph: prints distribution + samples (no write)
  generate_augmented.py  writes <ds>_augmented_v2/ {test.json, report.json,
                         needs_verification.jsonl}; handles all 3 formats
  grounding_probe.py   DB-free difficulty annotation → test.probed.json + spectrum
  make_review_file.py  needs_verification.jsonl → review CSV for the partner
```

## 5. Pipeline mechanics (per row)

1. **Extract** augmentable (name-type) entity spans from the gold-Cypher
   literals; resolve `(label, prop)`; drop dates/times/emails/IDs.
2. **Choose one (entity, strategy)** via the deficit-greedy `QuotaSampler`:
   the strategy furthest below its target that yields a DB-valid edit on some
   entity. `casing` is **capped** at its 10% target (`CAPPED_STRATEGIES`) so
   surplus from supply-starved strategies flows to the informative ones, not the
   control. If nothing valid → drop the row with a reason (never substitute).
3. **Generate** the surface: casing/typo/partial algorithmic; abbrev/alias from
   attested sources, else gpt-4.1 proposer (flagged `needs_verification`).
4. **Validate** (DB, model-free): no collision with a *different* value of the
   `(label,prop)`; partial must resolve uniquely by containment; typo must leave
   the canonical unique within Damerau-1. Splice guard repairs the seam.
5. **Guards:** synthetic graphs (`pole/bloom/er`) → `alias` off; closed-set
   `(label,prop)` ≤ `ALIAS_CLOSED_SET_MAX` (30) → LLM alias off (prevents
   sibling-swaps); replace ALL occurrences of the entity consistently.

The five strategies: `casing` (10%, control floor) / `typo` / `partial` /
`abbrev` / `alias` (22.5% each target). `paraphrase` was removed (left the
entity verbatim → no grounding challenge).

## 6. How to actually run it (operational)

**Critical infra facts:**
- The benchmark graphs are on a colleague's GCP VM (`eval_config.GRAPH_CONNS`).
  The IP is **ephemeral** — overridable: `export EVAL_NEO4J_HOST=<current-ip>`.
- **The corporate VPN must be OFF.** On-VPN, GCP VM IPs route through Private
  Google Access and time out on every port. (See env-vpn-proxy memory.)
- With `--llm`, OpenAI must bypass the corporate proxy (it's set in the shell).

**Generate (VPN OFF):**
```bash
export OPENAI_API_KEY=$(grep '^OPENAI_API_KEY=' .env | cut -d= -f2- | tr -d '"')
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
  python -m scripts.generate_augmented cypherbench nba flight_accident fictional_character \
    company geography movie politics --llm
# mindthequery graphs: bloom covid er healthcare wwc   |   zograscope: pole
```

**Dry-run one graph (distribution + samples, no write):**
```bash
python -m scripts.stage_augment cypherbench nba --limit 200 --llm
```

**Difficulty spectrum (DB-free, VPN state irrelevant):**
```bash
python -m scripts.grounding_probe          # all 3 datasets' _augmented_v2
```

**Build the review CSV:**
```bash
python -m scripts.make_review_file ~/datasets/*_augmented_v2/needs_verification.jsonl \
  -o ~/datasets/review_queue_ALL.csv
```

**Tests:** `python -m pytest tests/test_augmentation_redesign.py` (34, offline).

## 7. Current state (2026-06-14)

Generated to `~/datasets/<dataset>_augmented_v2/` (live `*_augmented` untouched):

| dataset | rows | verify queue |
|---|--:|--:|
| cypherbench (7 graphs) | 2,136 | 431 |
| mindthequery (5 graphs) | 1,298 | 292 |
| zograscope (pole) | 1,441 | 91 |
| **total** | **4,875** | **814** |

**Difficulty spectrum (all 4,875):** exact_ci 10.1% / edit_distance 38.3% /
substring 30.2% / semantic 21.4%; grounding gap **89.9%**. Class×strategy is
clean (casing→exact_ci, typo→edit_distance, partial→substring,
abbrev/alias→semantic). Per-graph realized distributions are in `DATASHEET.md`
§6. Validated: synthetic domains alias=0; casing pinned ~10% everywhere;
abbrev-rich domains hit 10/22.5×4; abbrev-poor domains typo-heavy by honest
supply.

## 8. Remaining steps

1. Partner human-verifies `~/datasets/review_queue_ALL.csv` (814 edits) per
   `REVIEW_GUIDE.md`.
2. Apply verdicts (keep/fix/drop) → final data; update DATASHEET counts.
3. **Layout conversion:** v2 is a consolidated `test.json` (each row keeps
   `_source_row`); convert to each source's eval layout (Mind-the-Query
   per-graph files; ZOGRASCOPE CSV) — or wire `providers` into the production
   `data_augmentation/datasets/` adapters — before the eval harness can run.
4. (Optional) build fulltext/vector indexes on the graphs for true Lucene/vector
   difficulty ranks — but that's really part of eval setup.
5. Swap v2 into the live `*_augmented` location (archive current → move in).

## 9. Key decisions (dated)

- **2026-06-12** — Balanced targets 10 / 22.5×4 (preempts "weighted toward the
  agent's best category"). Proposer LLM = **gpt-4.1** (not mini/open-weight;
  every proposal human-verified).
- **2026-06-13** — Cut `paraphrase`. Exclude dates/times/emails/IDs/postcodes
  from the entity pool. Scaffold class cut.
- **2026-06-14** — `casing` hard cap (pins control at 10% on abbrev-poor
  domains). Closed-set guard (`ALIAS_CLOSED_SET_MAX=30`) on LLM aliasing +
  curated position-slang aliases. Grounding probe made DB-free.
- **Standing** — synthetic graphs (`pole/bloom/er`) → `alias` disabled;
  generation is read-only on the VM; VPN must be OFF to reach it.
