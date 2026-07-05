# Report — wwc (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `wwc`, 275 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-06-24T08:23:51+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
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
| No Val Link          | —         | 0.138 | 0.341 | 275 |  30 |
| FCAV                 | vector    | 0.142 | 0.337 | 275 |  26 |
| ReAct (Node + Rel)   | fuzzy     | 0.447 | 0.638 | 275 |  12 |
| GraphRAG             | norm-Lev  | 0.509 | 0.699 | 275 |  12 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.509 | 0.725 | 275 |  12 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.071 | 0.043 |   0.088 |  0.571 | 0.351 |
| FCAV                 |  0.071 | 0.043 |   0.088 |  0.571 | 0.368 |
| ReAct (Node + Rel)   |  0.321 | 0.446 |   0.473 |  0.571 | 0.456 |
| GraphRAG             |  0.429 | 0.467 |   0.527 |  1.000 | 0.526 |
| CyANCHOR (fuzzy+lev) |  0.429 | 0.489 |   0.516 |  1.000 | 0.509 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.173 |  0.159 | 0.059 |
| FCAV                 | 0.173 |  0.167 | 0.059 |
| ReAct (Node + Rel)   | 0.520 |  0.508 | 0.250 |
| GraphRAG             | 0.613 |  0.561 | 0.294 |
| CyANCHOR (fuzzy+lev) | 0.627 |  0.583 | 0.235 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.108 | 0.046 |   0.676 |  0.571 | 0.369 |
| FCAV                 |  0.108 | 0.033 |   0.666 |  0.571 | 0.389 |
| ReAct (Node + Rel)   |  0.632 | 0.686 |   0.681 |  0.574 | 0.500 |
| GraphRAG             |  0.754 | 0.693 |   0.728 |  1.000 | 0.601 |
| CyANCHOR (fuzzy+lev) |  0.690 | 0.758 |   0.767 |  0.992 | 0.591 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.370 |  0.397 | 0.200 |
| FCAV                 | 0.373 |  0.392 | 0.191 |
| ReAct (Node + Rel)   | 0.743 |  0.687 | 0.426 |
| GraphRAG             | 0.839 |  0.756 | 0.435 |
| CyANCHOR (fuzzy+lev) | 0.847 |  0.780 | 0.485 |
