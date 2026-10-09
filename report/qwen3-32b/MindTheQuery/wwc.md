# Report — wwc (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `wwc`, 265 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T14:08:10-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.121 | 0.121 | 265 |  35 |        9 |
| FCAV        | vector    | 0.253 | 0.419 | 265 |  53 |        8 |
| ReAct       | fuzzy     | 0.279 | 0.469 | 265 |   1 |       12 |
| GraphRAG    | norm-Lev  | 0.340 | 0.601 | 265 |   0 |       12 |
| CyANCHOR    | fuzzy+lev | 0.355 | 0.587 | 265 |   2 |       12 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 12 of the 265 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.071 | 0.082 |   0.025 |  0.138 | 0.395 |
| FCAV        |  0.071 | 0.262 |   0.225 |  0.259 | 0.421 |
| ReAct       |  0.286 | 0.328 |   0.200 |  0.276 | 0.368 |
| GraphRAG    |  0.286 | 0.459 |   0.250 |  0.345 | 0.368 |
| CyANCHOR    |  0.393 | 0.393 |   0.338 |  0.241 | 0.474 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.139 |  0.148 | 0.046 |
| FCAV        | 0.292 |  0.320 | 0.077 |
| ReAct       | 0.306 |  0.359 | 0.092 |
| GraphRAG    | 0.347 |  0.445 | 0.123 |
| CyANCHOR    | 0.417 |  0.461 | 0.077 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.071 | 0.082 |   0.025 |  0.138 | 0.395 |
| FCAV        |  0.347 | 0.490 |   0.370 |  0.425 | 0.453 |
| ReAct       |  0.529 | 0.659 |   0.354 |  0.463 | 0.368 |
| GraphRAG    |  0.618 | 0.767 |   0.534 |  0.645 | 0.393 |
| CyANCHOR    |  0.672 | 0.730 |   0.641 |  0.375 | 0.503 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.139 |  0.148 | 0.046 |
| FCAV        | 0.553 |  0.462 | 0.186 |
| ReAct       | 0.619 |  0.490 | 0.260 |
| GraphRAG    | 0.630 |  0.713 | 0.347 |
| CyANCHOR    | 0.734 |  0.653 | 0.293 |
