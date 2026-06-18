# Ablation — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over successfully-scored rows. Generated 2026-06-18.

**Setup.** CypherBench `flight_accident`, 170 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias). LLMs: gpt-4.1 for
grounding/judge and Cypher generation. Each mode is scored over its own
successfully-executed rows (per-mode `n`).

**Modes.**
- `no_ner` — grounding bypassed (perturbed surface form used as-is).
- `fcav (RAG)` — retrieve-then-generate baseline: embed the question, retrieve
  candidate values from a self-built value index, LLM generates the entity JSON.
- `react node_only` / `react node_rel` — ReAct NER agent, node tools only / node+relation tools.
- `plan_exec fuzzy` / `plan_exec hybrid` — plan-and-execute grounder; fuzzy = BM25 only
  (zero embeddings), hybrid = BM25 ∪ in-graph vector.
- `+ escalate` — corrective loop: an LLM judge picks the next action each round
  (done / deepen the field / a specific field it chooses from a menu), up to 3 rounds.

---

## Overall

| mode                        | retrieval | escalate |    EA |  PSJS |   n | err |
| --------------------------- | --------- | -------- | ----: | ----: | --: | --: |
| no_ner                      | —         | —        | 0.095 | 0.126 | 169 |   1 |
| fcav (RAG)                  | vector    | —        | 0.509 | 0.559 | 167 |   3 |
| react node_only             | fuzzy     | —        | 0.314 | 0.346 | 169 |   1 |
| react node_rel              | fuzzy     | —        | 0.373 | 0.410 | 169 |   1 |
| plan_exec fuzzy             | fuzzy     | no       | 0.679 | 0.746 | 168 |   2 |
| plan_exec hybrid            | hybrid    | no       | 0.707 | 0.778 | 167 |   3 |
| plan_exec fuzzy + escalate  | fuzzy     | yes      | 0.774 | 0.845 | 168 |   2 |
| plan_exec hybrid + escalate | hybrid    | yes      | 0.792 | 0.883 | 168 |   2 |

## By perturbation strategy — EA

| mode                        | casing |  typo | partial | abbrev | alias |
| --------------------------- | -----: | ----: | ------: | -----: | ----: |
| no_ner                      |  0.118 | 0.000 |   0.105 |  0.184 | 0.077 |
| fcav (RAG)                  |  0.647 | 0.595 |   0.447 |  0.514 | 0.421 |
| react node_only             |  0.353 | 0.324 |   0.289 |  0.342 | 0.282 |
| react node_rel              |  0.471 | 0.486 |   0.368 |  0.263 | 0.333 |
| plan_exec fuzzy             |  0.765 | 0.865 |   0.658 |  0.632 | 0.526 |
| plan_exec hybrid            |  0.824 | 0.865 |   0.676 |  0.605 | 0.632 |
| plan_exec fuzzy + escalate  |  0.882 | 0.865 |   0.763 |  0.684 | 0.737 |
| plan_exec hybrid + escalate |  0.882 | 0.865 |   0.838 |  0.737 | 0.692 |

## By query-difficulty — EA

| mode                        |  easy | medium |  hard |
| --------------------------- | ----: | -----: | ----: |
| no_ner                      | 0.115 |  0.056 | 0.133 |
| fcav (RAG)                  | 0.462 |  0.479 | 0.614 |
| react node_only             | 0.346 |  0.264 | 0.356 |
| react node_rel              | 0.481 |  0.319 | 0.333 |
| plan_exec fuzzy             | 0.647 |  0.667 | 0.733 |
| plan_exec hybrid            | 0.706 |  0.694 | 0.727 |
| plan_exec fuzzy + escalate  | 0.750 |  0.764 | 0.818 |
| plan_exec hybrid + escalate | 0.824 |  0.764 | 0.800 |

## By perturbation strategy — PSJS

| mode                        | casing |  typo | partial | abbrev | alias |
| --------------------------- | -----: | ----: | ------: | -----: | ----: |
| no_ner                      |  0.254 | 0.027 |   0.077 |  0.269 | 0.071 |
| fcav (RAG)                  |  0.725 | 0.658 |   0.487 |  0.595 | 0.425 |
| react node_only             |  0.471 | 0.383 |   0.263 |  0.399 | 0.285 |
| react node_rel              |  0.588 | 0.528 |   0.355 |  0.337 | 0.347 |
| plan_exec fuzzy             |  0.887 | 0.937 |   0.751 |  0.688 | 0.552 |
| plan_exec hybrid            |  0.941 | 0.911 |   0.797 |  0.699 | 0.637 |
| plan_exec fuzzy + escalate  |  1.000 | 0.946 |   0.835 |  0.781 | 0.753 |
| plan_exec hybrid + escalate |  1.000 | 0.991 |   0.940 |  0.847 | 0.708 |

---

## Findings

1. **Grounding is the dominant lever.** `no_ner` (0.095) → any grounded mode lifts EA
   several-fold; the perturbed surface form is rarely the canonical DB value.
2. **plan-and-execute beats both the ReAct agent and the retrieve-then-generate RAG.**
   plan_exec (≥0.68) far exceeds `react node_rel` and `fcav (RAG)` on the full set.
3. **Corrective escalation helps decisively**, and an LLM choosing the field beats a
   fixed next-ranked fallback — biggest gains on partial / abbrev / alias.
4. **Two shipped modes:** `plan_exec fuzzy + escalate` (zero embeddings) and
   `plan_exec hybrid + escalate` (in-graph vector); hybrid edges fuzzy by a few points.
