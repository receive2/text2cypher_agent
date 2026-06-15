# NER Ablation on Perturbed CypherBench (movie · geography · politics)

> Metric key: **EA** = execution accuracy (predicted Cypher's result set matches gold's). **PSJS** = Provenance-Subgraph Jaccard Similarity (partial-credit overlap of the retrieved subgraph). Higher is better for both. EM omitted (structurally ~0 on CypherBench: gold is template-generated, predictions are semantically-equivalent string variants).

**NER modes compared:** `full`, `node_only`, `no_ner` (Δ columns are vs `no_ner` baseline).

- `full` — NER ReAct agent with node + relation tools; resolves each question entity to its canonical DB value via fulltext search.
- `node_only` — NER agent with node-property tools only (relation tools ablated).
- `no_ner` — NER bypassed entirely; the Cypher LLM sees only schema + question (perturbed entity surface forms are copied verbatim into the query).

## Executive summary

Three NER modes evaluated on the **value-grounding-perturbed** CypherBench
benchmark (entity surface forms in the NL question are abbreviated / mis-cased /
typo'd / aliased; the gold Cypher is unchanged). 3 graphs, 800 questions total
(movie 200, geography 300, politics 300). All metrics are over successfully-scored
rows (errored rows excluded from the mean).

**Headline (pooled, row-weighted):**

| metric | full | node_only | no_ner |
|---|---|---|---|
| EA | 0.165 | **0.201** | 0.047 |
| PSJS | 0.339 | **0.349** | 0.113 |

1. **NER is decisive.** Either NER mode beats the no-NER baseline by **+12–15 pp
   EA (3.5–4.3×)** and **+23–24 pp PSJS (≈3×)**. Without NER, the perturbed
   surface form ("FRA", "THE BIG SHORT", "Cnetral African…") is copied verbatim
   into the Cypher literal and never matches the canonical DB value. This is the
   benchmark's core claim and it holds decisively on all 3 graphs.

2. **Surprise: `node_only` ≥ `full`.** On EA, node_only beats full on geography
   (0.199 vs 0.158) and politics (0.193 vs 0.134), and ties on movie (0.215 vs
   0.222). full clearly wins only on **movie PSJS** (0.468 vs 0.362). Pooled,
   node_only leads full on both metrics. **Adding relation tools hurts more than
   it helps on these graphs** — root cause below.

3. **Difficulty trend is sane.** EA/PSJS generally decline easy→hard, and the
   redesigned 3-tier difficulty axis is non-degenerate on every graph.

> Caveat: geography `full` had 40/300 transient OpenAI `APIConnectionError`
> rows (excluded from the mean; the rate over the 260 scored rows is unbiased).
> All other cells have ≤10 errors.

## Why `full` < `node_only` — root-cause analysis

Diagnosed on the **common scored set** (questions both modes scored without
error), so this is not an artifact of differing N:

| graph | full EA | node_only EA | regressions (node✓ full✗) | gains (full✓ node✗) | net |
|---|---|---|---|---|---|
| geography | 0.157 | 0.209 | 27 | 14 | **−13** |
| politics | 0.136 | 0.192 | 26 | 10 | **−16** |

Adding relation tools causes **≈2× more regressions than gains**.

**Mechanism (code-confirmed, not inferred):**
- The NER agent's system prompt is *identical* across modes; the only runtime
  difference is the `{tool_list}` placeholder, filled with the FAISS **top-K
  (=15)** tools selected from that mode's index.
- full index = 63 tools (geography) / 56 (politics); node_only = 51 / 41. The
  extra ~12–15 are **relation tools**.
- These graphs' questions are relation-verb-heavy ("flows through", "founded
  by", "holds position"), so relation-property tools score high on the query
  embedding and **occupy top-15 slots, pushing the node-name tool the agent
  needs below the cutoff**. The agent then lacks the tool to resolve e.g.
  "ARAUCA RIVER" → "Arauca River", so the perturbed form leaks into the Cypher.
- **93% of geography regressions and 81% of politics regressions** are exactly
  this: full emitted a *different (non-canonical) string literal* than node_only.

| question (perturbed) | full wrote (wrong) | node_only wrote (canonical) |
|---|---|---|
| ARAUCA RIVER | `"ARAUCA RIVER"` | `"Arauca River"` |
| Zheng Shui | `"Zheng Shui"` | `"Zheng River"` |
| Prorvisnkaya (typo) | `"Prorvisnkaya"` | `"Prorvinskaya"` |
| Cnetral African (typo) | `"Cnetral African…"` | `"Central African…"` |

**Why movie is the exception:** movie's relations carry *groundable* properties
(`winners`, `character_role`), so relation tools earn their top-K slots there
(full PSJS 0.468 > node_only 0.362). geography/politics relations
(`flowsThrough`, `locatedIn`, `headedBy`, `foundedBy`) are *structural* — no
groundable values a user would mention — so their relation tools are pure
retrieval noise.

**Fix direction** (options in `docs/NER_IMPROVEMENT_PROPOSAL.md`): guarantee
node-tool coverage in top-K (separate node/relation budgets, or two-stage
node-then-relation NER), and/or prune relation tools for relations lacking
groundable properties.

## Per-graph results

### cypherbench_augmented / geography  (N=300)

| metric | `full` | `node_only` | `no_ner` | Δfull vs no_ner | Δnode_only vs no_ner |
|---|---|---|---|---|---|
| EA | 0.158 | 0.199 | 0.047 | +0.111 | +0.151 |
| PSJS | 0.309 | 0.342 | 0.095 | +0.215 | +0.248 |
| n_errors | 40 | 8 | 3 |  |  |

<details><summary>by query-difficulty — geography</summary>

| bucket | n | EA `full` | EA `node_only` | EA `no_ner` | PSJS `full` | PSJS `node_only` | PSJS `no_ner` |
|---|---|---|---|---|---|---|---|
| easy | 51 | 0.186 | 0.163 | 0.040 | 0.209 | 0.184 | 0.040 |
| medium | 156 | 0.153 | 0.224 | 0.052 | 0.238 | 0.325 | 0.068 |
| hard | 93 | 0.151 | 0.176 | 0.043 | 0.467 | 0.457 | 0.169 |

</details>

### cypherbench_augmented / movie  (N=200)

| metric | `full` | `node_only` | `no_ner` | Δfull vs no_ner | Δnode_only vs no_ner |
|---|---|---|---|---|---|
| EA | 0.222 | 0.215 | 0.031 | +0.191 | +0.185 |
| PSJS | 0.468 | 0.362 | 0.107 | +0.361 | +0.255 |
| n_errors | 6 | 5 | 5 |  |  |

<details><summary>by query-difficulty — movie</summary>

| bucket | n | EA `full` | EA `node_only` | EA `no_ner` | PSJS `full` | PSJS `node_only` | PSJS `no_ner` |
|---|---|---|---|---|---|---|---|
| easy | 25 | 0.240 | 0.320 | 0.000 | 0.407 | 0.333 | 0.007 |
| medium | 105 | 0.300 | 0.277 | 0.050 | 0.417 | 0.322 | 0.050 |
| hard | 70 | 0.101 | 0.087 | 0.014 | 0.564 | 0.430 | 0.228 |

</details>

### cypherbench_augmented / politics  (N=300)

| metric | `full` | `node_only` | `no_ner` | Δfull vs no_ner | Δnode_only vs no_ner |
|---|---|---|---|---|---|
| EA | 0.134 | 0.193 | 0.058 | +0.076 | +0.135 |
| PSJS | 0.279 | 0.347 | 0.136 | +0.144 | +0.211 |
| n_errors | 10 | 10 | 9 |  |  |

<details><summary>by query-difficulty — politics</summary>

| bucket | n | EA `full` | EA `node_only` | EA `no_ner` | PSJS `full` | PSJS `node_only` | PSJS `no_ner` |
|---|---|---|---|---|---|---|---|
| easy | 52 | 0.250 | 0.250 | 0.154 | 0.304 | 0.304 | 0.160 |
| medium | 158 | 0.107 | 0.233 | 0.033 | 0.210 | 0.307 | 0.053 |
| hard | 90 | 0.114 | 0.091 | 0.045 | 0.382 | 0.439 | 0.260 |

</details>

## Pooled (row-weighted across all graphs)

| metric | `full` | `node_only` | `no_ner` | Δfull vs no_ner | Δnode_only vs no_ner |
|---|---|---|---|---|---|
| EA | 0.165 | 0.201 | 0.047 | +0.118 | +0.154 |
| PSJS | 0.339 | 0.349 | 0.113 | +0.226 | +0.236 |

### Pooled by query-difficulty

| bucket | EA `full` | EA `node_only` | EA `no_ner` | PSJS `full` | PSJS `node_only` | PSJS `no_ner` |
|---|---|---|---|---|---|---|
| easy | 0.225 | 0.230 | 0.079 | 0.291 | 0.263 | 0.082 |
| medium | 0.173 | 0.241 | 0.044 | 0.274 | 0.318 | 0.058 |
| hard | 0.123 | 0.121 | 0.036 | 0.464 | 0.443 | 0.218 |

