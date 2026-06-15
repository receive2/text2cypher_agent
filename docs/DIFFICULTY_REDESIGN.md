# Query-Difficulty Classification — Redesign Plan

**Status:** implemented. The current `eval/difficulty.py` replaced the
degenerate presence-cascade with a graded rubric per this document; tests
in `tests/test_difficulty.py`, validator at `eval/difficulty_validate.py`.

**Locked decisions:**
1. **Static formula + GLOBAL thresholds** (Spider paradigm), computed uniformly
   from gold Cypher. Per-dataset threshold calibration rejected — see §2.
2. **Three tiers (easy / medium / hard)**, NOT four. text2cypher literature
   uses 2-3 tiers (BIRD / DuSQL / SpCQL / Neo4j Text2Cypher); only Spider /
   CSpider use the 4-tier "extra" scheme. Curated graph-QA benchmarks have a
   naturally thin extra tail (< 5%); chasing 4 tiers would have required a
   contrived 4th dimension purely to populate "extra". See §2.
3. **`classify(gold_cypher)` signature kept** — one parser, all datasets;
   zero caller changes.

## 1. The problem (evidence)

`eval/difficulty.py` classifies the gold Cypher by **presence-triggers**: *any*
`WITH` → hard, *any* aggregation → hard. But these are Cypher idioms, not
complexity signals. Measured on the generated data:

| dataset | easy | medium | hard | extra |
|---|--:|--:|--:|--:|
| cypherbench | 7% | **0%** | **90%** | 3% |
| mindthequery | 24% | 23% | 48% | 5% |
| zograscope | 37% | 38% | 24% | 0% |

CypherBench gold queries: **93% contain `WITH`**, 93% `DISTINCT`, 37%
aggregation — all from the `MATCH … WITH DISTINCT n WHERE … RETURN` template.
The `WITH → hard` rule alone auto-buckets 1003/2136 as hard; **medium collapses
to 0**. **Root cause:** "uses feature X" is treated as "is hard," and
aggregation/`COUNT` ("how many…") is the *most common* query type, not the
hardest. The scheme neither **grades** complexity nor **calibrates** thresholds.

## 2. How the classics do it (and why we lock global thresholds + 3 tiers)

### 2.1 Paradigms — none calibrates thresholds per dataset

| paradigm | representative | label / threshold source | distribution |
|---|---|---|---|
| **static formula + global thresholds** | **Spider** | hardcoded component-count rules | natural **bell** 24/40/21/15 |
| human annotation | BIRD | DB experts via docs/textbooks | skewed 60/30/10 |
| model-performance quantiles | CypherBench, Neo4j Text2Cypher | bin by base-model EX score | ~uniform (quantile-forced) |
| category taxonomy (non-ordinal) | Mind-the-Query | query *type* (retrieval/aggregation/…) | not a difficulty ordering |

- Spider's `eval_hardness` is **hardcoded global** — same thresholds over all
  200 DBs, never per-db. ⇒ **Per-dataset calibration has no precedent**; it
  forfeits cross-dataset comparability. **Global thresholds is the only
  literature-consistent path.**
- **Correction — CypherBench's difficulty is NOT its template taxonomy.** Its
  *difficulty* is a **post-hoc model-EX quantile**; `match_category` ×
  `return_pattern_id` are the **generation template taxonomy for diversity**,
  not difficulty. We adopt the template STRUCTURE only as a validation
  cross-check (§3.2), and **explicitly not** the model-quantile difficulty —
  which drifts as models improve and conflates "hard" with "current models fail."

### 2.2 Tier count — 3 (easy / medium / hard), not 4

| benchmark | domain | tiers | uses "extra"? |
|---|---|---|---|
| **Spider** | text2SQL | 4 (easy/medium/hard/extra) | ✓ |
| **CSpider** (Chinese Spider translation) | text2SQL | 4 (inherited) | ✓ |
| **DuSQL** (Chinese) | text2SQL | 3 (easy/medium/hard) | ✗ |
| **BIRD** | text2SQL | 3 (simple/moderate/challenging) | ✗ |
| **CypherBench** | **text2cypher** | model-EX quantile, no fixed tier | ✗ |
| **Mind-the-Query** | **text2cypher** | category (retrieval/aggregation/…) | ✗ |
| **Neo4j Text2Cypher** (Ozsoy) | **text2cypher** | 2 (easy/challenging) | ✗ |
| **SpCQL** (Chinese) | **text2cypher** | 3 (basic/medium/hard) | ✗ |
| **SynthCypher**, **PIPE-Cypher** | **text2cypher** | no explicit tier system | ✗ |

**No text2cypher benchmark uses the 4-tier "extra" scheme.** Spider's
extra=15% comes from 200 cross-domain DBs with long-tail SQL outliers;
curated graph-QA benchmarks are structurally bounded and have a naturally
thin extra tail. Forcing 4 tiers would require a contrived 4th dimension
purely to populate "extra" — a Spider-shaped tail where the data has none.

We adopt Spider's *paradigm* (static formula + global thresholds, graded
accumulation) but **3 tiers like the rest of the text2cypher field**.
Override conditions that would have been "extra" markers (nested subqueries,
UNION + multi-hop) **collapse into "hard"** with a `hard-override:` reason
prefix preserved so callers can still filter for them.

## 3. Redesign

### 3.1 Canonical complexity score (uniform, global thresholds)

Three dimensions, each 0/1/2, computed uniformly from the gold Cypher. Full
**detector → dimension → score** map (nothing left implicit):

| detector | dimension | score |
|---|---|--:|
| longest path ≤1 hop | Reach | 0 |
| longest path 2–3 fixed hops | Reach | 1 |
| longest path ≥4 fixed hops, **or** variable-length `[*..]` | Reach | 2 |
| plain return (node / property); no agg / sort / subquery | Operation | 0 |
| single aggregation `count/sum/avg/min/max/collect` (not grouped) | Operation | 1 |
| sort alone: `ORDER BY` / `LIMIT` / `SKIP` (without the `LIMIT 1` argmax pattern below) | Operation | 1 |
| `OPTIONAL MATCH` (hops also feed Reach, same rules as `MATCH`) | Operation | 1 |
| `UNWIND` | Operation | 1 |
| `shortestPath` / `allShortestPaths` | Operation | 1 |
| grouping: aggregation **+** a non-aggregated key in RETURN/WITH | Operation | 2 |
| extremal/argmax: `ORDER BY <expr> [DESC] LIMIT 1` returning the entity (NOT a bare `max()/min()` — that is already counted as single agg above) | Operation | 2 |
| comparison: `CASE WHEN` comparing two terms | Operation | 2 |
| set operation `UNION` | Operation | 2 |
| a single subquery `CALL{}` / `EXISTS{}` / `COUNT{}` / `COLLECT{}` | Operation | 2 |
| WHERE predicates + property-map `{k:v}` filters in MATCH | Filtering | see ↓ |

- **Operation is the MAX** over the rows above (group + sort still = 2, not 3).
- **Filtering**: predicates = `(1 + #AND + #OR)` if any WHERE present, plus the
  count of property-map `{k:v}` filters in MATCH patterns. → 0–1 preds: 0 ·
  exactly 2: 1 · ≥3 **or** mixed AND+OR: 2.

**`WITH` rule (the idiom fix).** A `WITH` clause feeds Operation **iff its
projection list contains an aggregation call**; otherwise it is ignored
entirely. Boundary cases:

| WITH clause | effect |
|---|---|
| `WITH n.x AS x, count(*) AS c` | has agg → feeds grouping (Operation) |
| `WITH DISTINCT n` | projection only → **ignored** |
| `WITH n, m WHERE n.x > 5` | projection + filter → WITH ignored (filter already counted in Filtering) |
| `WITH n ORDER BY n.x LIMIT 10` | the ORDER BY/LIMIT feed Operation (sort); the WITH itself ignored |

`score = Reach + Operation + Filtering` (0–6):

| score | bucket |
|---|---|
| 0 | easy |
| 1–2 | medium |
| ≥3 | hard |

**Hard-override** (→ hard regardless of score; reason carries the
`hard-override:` prefix): a **nested** subquery (a subquery block *inside
another* — `_has_nested_subquery`, depth ≥2), **or** `UNION` combined with a
multi-hop path (Reach ≥1). A single *flat* subquery (`EXISTS { (n)-[:R]->(m) }`)
is **not** an override — it only scores Operation=2.

Thresholds are LOCKED globally — never re-tuned per dataset. The override
preserves the principle that **nesting depth and union-over-multi-hop are
genuine structural complexity markers**, even when their accumulated
score happens to undershoot 3 (e.g. a 1-hop UNION of two flat patterns
that would otherwise score 2 → medium).

### 3.2 One uniform formula; native metadata = validation only

**Signature: keep `classify(gold_cypher)` — one pure-Cypher parser for all
datasets (RECOMMENDED).** Native metadata is *not* a per-dataset score source:
that would compute difficulty by a different mechanism per dataset and forfeit
the comparability global thresholds exist to provide. The parser already detects
the operations the native fields name — `UNION` (keyword), grouping (agg+key),
subquery (keyword), extremal (`ORDER BY…LIMIT` or `max/min`), comparison
(`CASE WHEN`). We do **not** distinguish argmax from top-K (both Operation=2;
the distinction is irrelevant to difficulty). Residual under-rating: CypherBench
`special_comparison` without `CASE WHEN` (~7% → medium not hard) — bounded, and
recoverable by extending the comparison detector if §4 flags it.

> **Open decision.** Alternative `classify(row)` lets native ground-truth
> (`type`, `return_pattern_id`) drive Operation — more *reliable* on
> argmax/comparison, but **breaks the one-formula paradigm (§2)** and weakens
> comparability. Recommendation: keep `classify(gold_cypher)`. **Confirm before
> implementing** — choosing `classify(row)` requires rewriting this section, the
> Operation detectors, and §5.1's "no caller changes."

**Cross-check is offline.** Native metadata is read only by
`difficulty_validate.py` (§5.2), which compares it to `classify(gold_cypher)`'s
output. **The classifier itself stays a pure Cypher parser — no native metadata,
no circular dependency.**

**Pre-registered validation mapping** (fixed BEFORE running, to prevent
data-snooping). CypherBench `match_category` → expected bucket(s):

| match_category | expected bucket(s) |
|---|---|
| `basic_(n)`, `basic_(n*)`, `basic_(n)=(m0)`, `basic_(n)-(m0)`, `basic_(n)-(m0*)`, `basic_(n)-(m0*),(n)-(m1*)` | easy–medium |
| `basic_(n)-(m0)-(m1*)` | medium |
| `special_optional-match`, `special_comparison`, `special_time-sensitive`, `special_union` | medium–hard |
| `special_three-node-groupby` | hard |

ZOGRASCOPE expected bucket is derived from `num_nodes` (→ Reach: 2→0 · 3→1 ·
4–5→2 wait 4=≤3→1; 5=4→2) and `type` (→ Op: entity_set/attribute_set→0 ·
count/min/max→1 · argmax/argmin→2), scored on the same 0/1/2 dims (Filter
unknown → 0 in this approximation). Mind-the-Query: no fine native signal
(only file category `Complex_Aggregation` / `Complex_Retrieval`) — parser is
the sole source.

The exact mapping table for both is encoded in `eval/difficulty_validate.py`
(see `CYPHERBENCH_MATCH_CATEGORY_MAP` and `_zograscope_expected_bucket`).

### 3.3 Recalibrating the parser

Reuse the existing machinery in `eval/difficulty.py` (comment/string stripping,
clause segmentation, hop counting, brace-aware subquery detection). **Add**
detectors: `UNION`, grouping (agg + non-agg key via the existing
`_split_top_level_commas` on RETURN/WITH segments), `CASE WHEN` comparison,
property-map `{k:v}` filter count in MATCH. **Drop** `WITH` / `DISTINCT` /
lone-`count` as auto-hard triggers. The parser stays a static formula, not a
model.

## 4. Validation (acceptance — Spider paradigm, NOT uniformity)

Natural distribution under a static formula is **bell-shaped**, NOT uniform.
Spider has 24/40/21/15 with 200 cross-domain DBs and a long real-SQL tail; our
single-domain curated text2cypher benchmarks are structurally more
concentrated. Accept iff, on **each** dataset:

- **no tier < 5% and no tier > 75%** (non-degenerate). The 75% cap is
  looser than Spider's natural ~40% medium because curated text2cypher
  benchmarks naturally pile mid-range — ZOG, for instance, is a single
  crime-investigation graph with bounded query shapes.
- **consistency with the §3.2 pre-registered mapping**: parser bucket equals
  the mapped bucket on **≥85% of rows** (3-way exact; for mapping rows that
  span two buckets like `easy–medium`, either counts as a hit), **and**
  Spearman rank correlation **ρ ≥ 0.7** between the parser bucket ordinal
  (easy=1<medium=2<hard=3) and the mapping's ordinal (mid-point for
  dual-bucket rows). The mapping is fixed before running — *not* adjusted
  after seeing the distribution.
- pooled distribution roughly bell-shaped.

**Observed distribution (locked):**

| dataset | n | easy | medium | hard | accept |
|---|--:|--:|--:|--:|---|
| cypherbench | 2136 | 16.3% | 52.9% | 30.8% | ✓ |
| mindthequery | 1298 | 6.2% | 61.9% | 31.9% | ✓ |
| zograscope | 1441 | 6.3% | 74.4% | 19.3% | ✓ (medium near cap; principled for single-domain curated data) |
| POOLED | 4875 | 10.7% | 61.6% | 27.7% | ✓ |

Cross-check: CypherBench 99.1% in-range, ρ=+0.763; ZOGRASCOPE 98.1%
in-range, ρ=+0.748. Top mismatches are documented in the validator output
and are bounded (≤17 rows out of 2136 on CB; ≤14 out of 1441 on ZOG).

Genuine cross-dataset skew is allowed and expected — global thresholds make
the skew *comparable*. Our difficulty is **intrinsic-structural**, not
model-relative; same paradigm as Spider, complementary to CypherBench's
model-quantile difficulty. Paper line: *"we depart from CypherBench's
model-quantile difficulty in favor of a structural rubric, for stability
across model generations."*

## 5. Implementation steps — ORDER MATTERS

Steps 1–4 must **pass §4 and LOCK thresholds before** steps 5–6 — otherwise a
regenerated dataset bakes in difficulty labels inconsistent with the locked
classifier.

1. **Rewrite `eval/difficulty.py` scoring** (§3.1/§3.3): graded score +
   extra-override; reuse the stripping/segmentation/hop/subquery helpers; add the
   new detectors; drop WITH/DISTINCT/lone-count auto-hard. **Keep
   `classify(gold_cypher)`** → zero caller changes (callers:
   `metrics_{CypherBench,MindTheQuery,ZOGRASCOPE}.py`; `aggregate_by_difficulty`
   unchanged, also used in `eval_aggregate.py`).
2. **Add `eval/difficulty_validate.py`**: per-dataset + pooled distribution; the
   §3.2 pre-registered cross-check (% exact + Spearman ρ).
3. **Tune the global thresholds once** on pooled data to pass §4.
4. **LOCK thresholds.** Gate — do not proceed past here until §4 passes; if it
   fails, go to §6 (add a dimension), do NOT re-tune per dataset.
5. **Tag** every augmented row's `_aug_meta` with `query_difficulty` — a NEW
   field (confirmed absent from current `augment_*.py`, no legacy). **Only after
   step 4.** Prefer a small **backfill pass** over existing `*_augmented_v2`
   (read each row → `classify(gold_cypher)` → write `_aug_meta.query_difficulty`)
   — no need to re-run the full augmentation, which is expensive and would also
   regenerate the LLM-perturbed `nl` field. Add the same tagging call to
   `augment_*.py` for future regens.
6. **Paper exhibit:** 2D table **query-difficulty × grounding-difficulty**
   (latter from `grounding_probe`).

## 6. Contingency — fallback if §4 ever fails after a data refresh

Currently §4 passes (see table above) so this is a fallback, not a live
problem. The documented remedy if a future dataset edition fails §4 is to
**add a 4th dimension** to the rubric, NOT to retune thresholds:

- **Return shape (preferred):** scalar/count (0) · one column of nodes/
  properties (1) · multiple columns or computed/`CASE` expressions (2).
  CypherBench variation lives largely in `return_pattern_id`, so this
  separates the dominant basic shape.
- **(alt) Selectivity:** equality predicate (0) · range/`IN` (1) · existence
  `IS NOT NULL` (2). CypherBench uses `WHERE n.x IS NOT NULL` as structural
  filtering.

Add only if §4 fails; then re-tune once for the 4-dimension (0–8) score and
lock. Provisional 4-dim cuts (re-validate against §4): easy=0, medium=1–3,
hard=≥4 (+hard-override).

## 7. Orthogonality

Augmentation does not change the gold Cypher, so query-difficulty is **inherited
unchanged** and **independent** of the grounding-difficulty this benchmark
introduces. The two axes are orthogonal; their cross-product is the headline
analysis.
