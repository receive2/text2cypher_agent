# Report — wwc (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `wwc`, 265 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-06T01:03:01-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.128 | 0.128 | 265 |   8 |       12 |
| FCAV        | vector    | 0.423 | 0.653 | 265 |   8 |       12 |
| ReAct       | fuzzy     | 0.445 | 0.691 | 265 |   0 |       12 |
| GraphRAG    | norm-Lev  | 0.426 | 0.639 | 265 |   0 |       12 |
| CyANCHOR    | fuzzy+lev | 0.472 | 0.711 | 265 |   0 |       12 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 12 of the 265 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.107 | 0.082 |   0.037 |  0.138 | 0.395 |
| FCAV        |  0.357 | 0.492 |   0.350 |  0.448 | 0.474 |
| ReAct       |  0.393 | 0.525 |   0.338 |  0.466 | 0.553 |
| GraphRAG    |  0.393 | 0.541 |   0.400 |  0.397 | 0.368 |
| CyANCHOR    |  0.357 | 0.508 |   0.450 |  0.500 | 0.500 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.167 |  0.148 | 0.046 |
| FCAV        | 0.500 |  0.492 | 0.200 |
| ReAct       | 0.500 |  0.531 | 0.215 |
| GraphRAG    | 0.514 |  0.484 | 0.215 |
| CyANCHOR    | 0.528 |  0.562 | 0.231 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.107 | 0.082 |   0.037 |  0.138 | 0.395 |
| FCAV        |  0.703 | 0.751 |   0.622 |  0.646 | 0.534 |
| ReAct       |  0.734 | 0.792 |   0.623 |  0.709 | 0.612 |
| GraphRAG    |  0.637 | 0.798 |   0.625 |  0.623 | 0.440 |
| CyANCHOR    |  0.689 | 0.795 |   0.716 |  0.741 | 0.533 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.167 |  0.148 | 0.046 |
| FCAV        | 0.795 |  0.713 | 0.377 |
| ReAct       | 0.788 |  0.779 | 0.410 |
| GraphRAG    | 0.811 |  0.667 | 0.394 |
| CyANCHOR    | 0.801 |  0.805 | 0.425 |
