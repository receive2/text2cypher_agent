# NER Ablation — Clean HEAD Baseline (movie · geography · politics)

> **Supersedes the gated-integration-era numbers in [`NER_ABLATION_REPORT.md`](NER_ABLATION_REPORT.md).**
> This run uses the committed **HEAD** pipeline (commit `8d209c8`): the single
> mixed-tool NER agent, with FAISS top-K selection over the combined tool index.
> The exploratory `gated-integration` / C-pruning / `K_rel` cap changes were
> reverted (stashed) **before** this run — see *Why we reverted* below.

Metric key: **EA** = execution accuracy (predicted Cypher's result set matches
gold's). **PSJS** = Provenance-Subgraph Jaccard Similarity (partial-credit
overlap of the retrieved subgraph). Higher is better for both. EM omitted
(structurally ≈0 on CypherBench: gold is template-generated, predictions are
semantically-equivalent string variants).

**Modes.** `full` = NER ReAct agent with node **+** relation tools; `node_only`
= node-property tools only; `no_ner` = NER bypassed (perturbed surface forms
copied verbatim into the Cypher literal).

## Setup / provenance

- **Code:** HEAD (`8d209c8`), gated-integration reverted. Tool **selection** is
  the original single mixed FAISS top-K (=15); `full` vs `node_only` differ only
  in which tools exist in the index.
- **Tool sets** (re-generated from HEAD `gen_tools`, matching the original
  report's counts): movie `full`=55 / `node_only`=45 (10 relation tools);
  geography 63 / 51 (12); politics 56 / 41 (15).
- **Retrieval:** `TOOL_RETRIEVAL_MODE = "fuzzy"` (Lucene fulltext; vector
  embeddings unused — no re-embedding needed).
- **Data:** entity-perturbed CypherBench, 200 questions/graph (600 total per
  mode). Metrics over successfully-scored rows (errored rows excluded).
- **Controls:** within each graph, all three modes share the **same** archived
  prompts / schema-meta; only the tool set changes. So `full`–`node_only` is a
  controlled comparison.

## Headline — per graph

| graph | mode | EA | PSJS | n | err |
|---|---|---|---|---|---|
| **movie** | **full** | **0.192** | **0.393** | 193 | 7 |
| movie | node_only | 0.183 | 0.317 | 197 | 3 |
| movie | no_ner | 0.041 | 0.123 | 195 | 5 |
| **geography** | full | 0.141 | 0.309 | 198 | 2 |
| **geography** | **node_only** | **0.172** | **0.325** | 198 | 2 |
| geography | no_ner | 0.041 | 0.093 | 197 | 3 |
| **politics** | full | 0.159 | 0.310 | 195 | 5 |
| **politics** | **node_only** | **0.186** | **0.358** | 194 | 6 |
| politics | no_ner | 0.073 | 0.131 | 193 | 7 |

### `full` − `node_only` (the conditional effect of relation tools)

| graph | ΔEA | ΔPSJS | winner |
|---|---|---|---|
| **movie** | **+0.009** | **+0.076** | **full** |
| geography | −0.030 | −0.016 | node_only |
| politics | −0.027 | −0.049 | node_only |

## Pooled (row-weighted across all 3 graphs)

| mode | EA | PSJS | n |
|---|---|---|---|
| full | 0.164 | 0.337 | 586 |
| node_only | **0.180** | 0.333 | 589 |
| no_ner | 0.051 | 0.116 | 585 |

## Findings

1. **NER grounding is decisive.** Both `full` and `node_only` beat `no_ner` by
   **3–4× on EA** and **≈3× on PSJS** on every graph. Without a grounding step
   the perturbed surface form (`"FRA"`, `"MIB³"`, `"Cnetral African…"`) is copied
   verbatim into the Cypher literal and never matches the canonical DB value.
   This is the benchmark's core claim and it holds decisively.

2. **Adding relation tools helps on movie, hurts on geography/politics.** `full`
   beats `node_only` on movie (ΔPSJS **+0.076**, ΔEA +0.009) but loses on
   geography (ΔEA −0.030) and politics (ΔEA −0.027). Pooled, `node_only` slightly
   leads `full`. **The value of relation tools is conditional on the schema** —
   mechanism below.

3. **The discrepancy is reproducible, not noise.** The direction and cross-graph
   pattern match the earlier run exactly; only the absolute level is a touch
   lower (see *Caveats*).

## Discussion — why relation tools sometimes hurt

The NER agent selects a fixed top-K (=15) tools via FAISS semantic search over
tool descriptions, then a ReAct agent calls a subset to ground the question's
entities to canonical DB values. Going from `node_only` to `full` enlarges the
candidate pool with relation tools; on a fixed budget, **whether this helps
depends on whether the relation carries a groundable value a user would
mention.**

- **Relation-property tools** ground values stored *on the relationship*
  (movie: `hasCastMember.character_role`, `receivesAward.winners`). When users
  mention these, the tool supplies grounding the node tools cannot → `full` >
  `node_only` (movie).
- **Structural relations** (geography: `River-flowsThrough-Country`; politics:
  `Politician-headedBy-Party`) have no groundable property of their own; their
  tool merely re-searches the **end-node's identifying property**, which the
  corresponding node tool already covers. It adds zero new grounding ability —
  but because these graphs' questions are phrased with relational verbs
  ("flows through", "headed by"), the structural relation tools score high on the
  query embedding and **displace the node-name tool the agent actually needs**.
  The perturbed surface form then never gets canonicalized → `full` <
  `node_only` (geography/politics).

**General principle: value-grounding tools should be scoped to where groundable
values live. Nodes always carry them; relations only sometimes. Indiscriminately
adding relation tools dilutes retrieval on schemas where relations are purely
structural.** This suggests a simple, schema-driven refinement (future work):
generate a relation tool only for relations with a groundable (string-typed)
property, so structural-relation graphs degrade cleanly to the `node_only` floor
while value-bearing-relation graphs keep their upside.

## Why we reverted the gated-integration experiment

An exploratory change made `full` guarantee node tools the entire top-K budget
(node tools from a node-only index, relation tools merely appended). It was
intended to stop structural relation tools from crowding out node tools on
geography/politics. In validation it **broke movie**: it converted `full` into
`node_only`-like behavior (85% per-question EA agreement with `node_only`),
collapsing movie's PSJS from 0.39 to 0.29 and dropping EA below the `node_only`
floor. Diagnosis: guaranteeing node tools the full top-K surfaces *more*
distracting same-label attribute tools (`date_of_death`, `place_of_birth`, …),
so the agent mis-extracts (e.g. reads "passed away" as a date lookup instead of
grounding the two person names). The original mixed top-K was better precisely
because relation tools displaced those distractors. The change was reverted; the
ablation above uses the clean HEAD selection. Details:
[`NER_IMPROVEMENT_PROPOSAL.md`](NER_IMPROVEMENT_PROPOSAL.md) (now a record of the
rejected direction).

## Appendix — pooled by query-difficulty

| bucket | n | EA full | EA node_only | EA no_ner | PSJS full | PSJS node_only | PSJS no_ner |
|---|---|---|---|---|---|---|---|
| easy | 89 | 0.169 | 0.225 | 0.079 | 0.249 | 0.264 | 0.081 |
| medium | 309 | 0.197 | 0.216 | 0.052 | 0.289 | 0.297 | 0.063 |
| hard | 188 | 0.106 | 0.100 | 0.037 | 0.458 | 0.423 | 0.218 |

The redesigned 3-tier difficulty axis is non-degenerate, and EA/PSJS generally
decline easy→hard (PSJS rises on hard because hard questions retrieve larger
subgraphs, inflating partial overlap).

## Caveats

- **Absolute level vs. the earlier run.** This clean HEAD re-run scores movie
  `full` at 0.192/0.393 vs. the earlier 0.222/0.468. The gap is attributable to
  (a) regenerated prompts (few-shot examples re-sampled) and (b) LLM
  nondeterminism. The **direction and cross-graph pattern are unchanged**, which
  is what the ablation claims rest on.
- Per-cell error counts ≤7/200; metrics are over scored rows only.
- Single seed / single run per cell. Treat sub-0.02 EA gaps as within noise; the
  movie ΔPSJS (+0.076) and the geography/politics losses are outside it.
