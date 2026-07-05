# Report — healthcare (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `healthcare`, 439 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-06-24T07:09:19+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node_rel` · escalate `on`.

**Methods.**
- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).
- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve
  candidate values from a self-built value index, an LLM generates the entity JSON.
- **ReAct (Node + Rel)** — ReAct NER agent (fuzzy/BM25 retrieval) over node + relation tools.
- **GraphRAG** — Multi-Agent GraphRAG baseline: generate→execute→evaluate→repair; on
  error/empty it extracts the query's labels/values/rels, validates them, and proposes
  normalized-Levenshtein replacements, iterating the generator.
- **CyANCHOR (Node + Rel)** — our plan-and-execute grounder: decompose the question into
  entity mentions, route each to a database field, retrieve candidates with an LLM-judge
  corrective loop, then the Cypher LLM value-links. Retrieval is the union of independently
  toggleable arms — **fuzzy** (BM25) · **lev** (APOC normalized Levenshtein) · **vector**
  (in-graph embeddings).

---

## Overall

| method               | retrieval |    EA |  PSJS |   n | err |
| -------------------- | --------- | ----: | ----: | --: | --: |
| No Val Link          | —         | 0.467 | 0.460 | 439 |  13 |
| FCAV                 | vector    | 0.469 | 0.462 | 439 |  10 |
| ReAct (Node + Rel)   | fuzzy     | 0.667 | 0.698 | 439 |   5 |
| GraphRAG             | norm-Lev  | 0.690 | 0.713 | 439 |   5 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.702 | 0.741 | 439 |   5 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.455 | 0.390 |   0.397 |  0.614 | 0.564 |
| FCAV                 |  0.477 | 0.398 |   0.397 |  0.614 | 0.556 |
| ReAct (Node + Rel)   |  0.727 | 0.669 |   0.759 |  0.659 | 0.556 |
| GraphRAG             |  0.773 | 0.754 |   0.750 |  0.614 | 0.564 |
| CyANCHOR (fuzzy+lev) |  0.795 | 0.754 |   0.724 |  0.659 | 0.607 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.472 | 0.461 |
| FCAV                 | 0.000 |  0.478 | 0.451 |
| ReAct (Node + Rel)   | 0.500 |  0.687 | 0.608 |
| GraphRAG             | 0.500 |  0.696 | 0.676 |
| CyANCHOR (fuzzy+lev) | 0.500 |  0.699 | 0.716 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.455 | 0.373 |   0.381 |  0.614 | 0.570 |
| FCAV                 |  0.477 | 0.381 |   0.372 |  0.614 | 0.570 |
| ReAct (Node + Rel)   |  0.763 | 0.725 |   0.787 |  0.659 | 0.573 |
| GraphRAG             |  0.803 | 0.811 |   0.748 |  0.634 | 0.573 |
| CyANCHOR (fuzzy+lev) |  0.803 | 0.810 |   0.784 |  0.691 | 0.623 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.000 |  0.466 | 0.450 |
| FCAV                 | 0.000 |  0.475 | 0.431 |
| ReAct (Node + Rel)   | 0.251 |  0.719 | 0.637 |
| GraphRAG             | 0.609 |  0.725 | 0.673 |
| CyANCHOR (fuzzy+lev) | 0.592 |  0.741 | 0.742 |
