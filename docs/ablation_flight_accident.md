# Ablation — flight_accident (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better; both over successfully-scored rows. Generated 2026-06-18.

**Setup.** CypherBench `flight_accident`, 170 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias). LLMs: gpt-4.1 for
grounding and Cypher generation. Each mode is scored over its own
successfully-executed rows (per-mode `n`).

**Modes.**
- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).
- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve
  candidate values from a self-built value index, an LLM generates the entity JSON.
- **ReAct Fuzzy (Node)** / **ReAct Fuzzy (Node + Rel)** — ReAct NER agent (fuzzy/BM25
  retrieval) over node tools only / node + relation tools.
- **Plan&Exec Fuzzy / Hybrid (Node + Rel)** — plan-and-execute grounder: decompose the
  question into entity mentions, route each to a database field, retrieve candidates
  with an LLM-judge corrective loop (it adds the right field / more values when a
  mention is not yet grounded), then the Cypher LLM value-links. Fuzzy = BM25 only
  (zero embeddings); Hybrid = BM25 ∪ in-graph vector.

---

## Overall

| mode                          | retrieval |    EA |  PSJS |   n | err |
| ----------------------------- | --------- | ----: | ----: | --: | --: |
| No Val Link                   | —         | 0.095 | 0.126 | 169 |   1 |
| FCAV (RAG)                    | vector    | 0.509 | 0.559 | 167 |   3 |
| ReAct Fuzzy (Node)            | fuzzy     | 0.314 | 0.346 | 169 |   1 |
| ReAct Fuzzy (Node + Rel)      | fuzzy     | 0.373 | 0.410 | 169 |   1 |
| Plan&Exec Fuzzy (Node + Rel)  | fuzzy     | 0.774 | 0.845 | 168 |   2 |
| Plan&Exec Hybrid (Node + Rel) | hybrid    | 0.792 | 0.883 | 168 |   2 |

## By perturbation strategy — EA

| mode                          | casing |  typo | partial | abbrev | alias |
| ----------------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link                   |  0.118 | 0.000 |   0.105 |  0.184 | 0.077 |
| FCAV (RAG)                    |  0.647 | 0.595 |   0.447 |  0.514 | 0.421 |
| ReAct Fuzzy (Node)            |  0.353 | 0.324 |   0.289 |  0.342 | 0.282 |
| ReAct Fuzzy (Node + Rel)      |  0.471 | 0.486 |   0.368 |  0.263 | 0.333 |
| Plan&Exec Fuzzy (Node + Rel)  |  0.882 | 0.865 |   0.763 |  0.684 | 0.737 |
| Plan&Exec Hybrid (Node + Rel) |  0.882 | 0.865 |   0.838 |  0.737 | 0.692 |

## By query-difficulty — EA

| mode                          |  easy | medium |  hard |
| ----------------------------- | ----: | -----: | ----: |
| No Val Link                   | 0.115 |  0.056 | 0.133 |
| FCAV (RAG)                    | 0.462 |  0.479 | 0.614 |
| ReAct Fuzzy (Node)            | 0.346 |  0.264 | 0.356 |
| ReAct Fuzzy (Node + Rel)      | 0.481 |  0.319 | 0.333 |
| Plan&Exec Fuzzy (Node + Rel)  | 0.750 |  0.764 | 0.818 |
| Plan&Exec Hybrid (Node + Rel) | 0.824 |  0.764 | 0.800 |

## By perturbation strategy — PSJS

| mode                          | casing |  typo | partial | abbrev | alias |
| ----------------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link                   |  0.254 | 0.027 |   0.077 |  0.269 | 0.071 |
| FCAV (RAG)                    |  0.725 | 0.658 |   0.487 |  0.595 | 0.425 |
| ReAct Fuzzy (Node)            |  0.471 | 0.383 |   0.263 |  0.399 | 0.285 |
| ReAct Fuzzy (Node + Rel)      |  0.588 | 0.528 |   0.355 |  0.337 | 0.347 |
| Plan&Exec Fuzzy (Node + Rel)  |  1.000 | 0.946 |   0.835 |  0.781 | 0.753 |
| Plan&Exec Hybrid (Node + Rel) |  1.000 | 0.991 |   0.940 |  0.847 | 0.708 |

---

## Findings

1. **Grounding is the dominant lever.** No Val Link (0.095) → any grounded mode lifts
   EA several-fold; the perturbed surface form is rarely the canonical DB value.
2. **Plan&Exec beats both the ReAct agent and the retrieve-then-generate RAG (FCAV).**
   Both Plan&Exec methods clear 0.77 EA vs 0.51 (FCAV) and 0.37 (ReAct Fuzzy Node + Rel).
3. **The gains concentrate on the hardest perturbations** (partial / abbrev / alias),
   where decomposing per mention and routing to the right field matters most.
4. **Two methods:** Plan&Exec Fuzzy (zero embeddings) and Plan&Exec Hybrid (in-graph
   vector); Hybrid edges Fuzzy by a few points.
