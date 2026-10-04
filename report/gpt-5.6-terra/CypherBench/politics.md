# Report — politics (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `politics`, 356 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02T13:54:20-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node` · escalate `on` (≤3) · semantic_repair `on` (≤4) · empty_is_wrong `off` · value_snap `on`.

**Methods.**
- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).
- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve
  candidate values from a self-built value index, an LLM generates the entity JSON.
- **ReAct** — ReAct NER agent (fuzzy/BM25 retrieval) over node + relation tools.
- **GraphRAG** — Multi-Agent GraphRAG baseline: generate→execute→evaluate→repair; on
  error/empty it extracts the query's labels/values/rels, validates them, and proposes
  normalized-Levenshtein replacements, iterating the generator.
- **CyANCHOR** — our plan-and-execute grounder (node + relation tools): decompose the question into
  entity mentions, route each to a database field, retrieve candidates with an LLM-judge
  corrective loop, then the Cypher LLM value-links. Retrieval is the union of independently
  toggleable arms — **fuzzy** (BM25) · **lev** (APOC normalized Levenshtein) · **vector**
  (in-graph embeddings).

---

## Overall

| method      | retrieval |    EA |  PSJS |   n | err | gold err |
| ----------- | --------- | ----: | ----: | --: | --: | -------: |
| No Val Link | —         | 0.135 | 0.151 | 356 |   4 |        0 |
| FCAV        | vector    | 0.455 | 0.504 | 356 |   5 |        0 |
| ReAct       | fuzzy     | 0.388 | 0.430 | 356 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.461 | 0.536 | 356 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.635 | 0.725 | 356 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.444 | 0.286 |   0.133 |  0.121 | 0.071 |
| FCAV        |  0.667 | 0.857 |   0.467 |  0.364 | 0.485 |
| ReAct       |  0.667 | 0.857 |   0.667 |  0.225 | 0.394 |
| GraphRAG    |  0.611 | 0.905 |   0.578 |  0.399 | 0.394 |
| CyANCHOR    |  0.833 | 0.905 |   0.800 |  0.543 | 0.626 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.143 |  0.063 | 0.252 |
| FCAV        | 0.661 |  0.386 | 0.468 |
| ReAct       | 0.429 |  0.354 | 0.423 |
| GraphRAG    | 0.500 |  0.481 | 0.405 |
| CyANCHOR    | 0.696 |  0.608 | 0.649 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.479 | 0.228 |   0.128 |  0.145 | 0.095 |
| FCAV        |  0.680 | 0.753 |   0.516 |  0.421 | 0.558 |
| ReAct       |  0.722 | 0.857 |   0.707 |  0.265 | 0.450 |
| GraphRAG    |  0.701 | 0.894 |   0.572 |  0.499 | 0.478 |
| CyANCHOR    |  0.834 | 0.953 |   0.811 |  0.660 | 0.730 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.143 |  0.068 | 0.295 |
| FCAV        | 0.676 |  0.437 | 0.529 |
| ReAct       | 0.460 |  0.379 | 0.502 |
| GraphRAG    | 0.540 |  0.567 | 0.480 |
| CyANCHOR    | 0.713 |  0.717 | 0.744 |
