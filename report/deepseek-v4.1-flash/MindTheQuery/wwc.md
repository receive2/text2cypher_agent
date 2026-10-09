# Report — wwc (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `wwc`, 265 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T12:22:25-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.125 | 0.128 | 265 |   8 |       12 |
| FCAV        | vector    | 0.309 | 0.587 | 265 |   8 |       12 |
| ReAct       | fuzzy     | 0.336 | 0.580 | 265 |   0 |       12 |
| GraphRAG    | norm-Lev  | 0.389 | 0.641 | 265 |   0 |       12 |
| CyANCHOR    | fuzzy+lev | 0.400 | 0.700 | 265 |   0 |       12 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 12 of the 265 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.107 | 0.082 |   0.037 |  0.138 | 0.368 |
| FCAV        |  0.250 | 0.393 |   0.225 |  0.293 | 0.421 |
| ReAct       |  0.286 | 0.525 |   0.225 |  0.276 | 0.395 |
| GraphRAG    |  0.357 | 0.459 |   0.350 |  0.397 | 0.368 |
| CyANCHOR    |  0.357 | 0.361 |   0.338 |  0.466 | 0.526 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.153 |  0.141 | 0.062 |
| FCAV        | 0.306 |  0.383 | 0.169 |
| ReAct       | 0.319 |  0.438 | 0.154 |
| GraphRAG    | 0.472 |  0.453 | 0.169 |
| CyANCHOR    | 0.403 |  0.500 | 0.200 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.136 | 0.082 |   0.037 |  0.138 | 0.368 |
| FCAV        |  0.611 | 0.702 |   0.602 |  0.502 | 0.482 |
| ReAct       |  0.689 | 0.854 |   0.480 |  0.496 | 0.395 |
| GraphRAG    |  0.666 | 0.802 |   0.624 |  0.630 | 0.415 |
| CyANCHOR    |  0.701 | 0.800 |   0.662 |  0.720 | 0.586 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.153 |  0.148 | 0.059 |
| FCAV        | 0.726 |  0.644 | 0.321 |
| ReAct       | 0.706 |  0.661 | 0.279 |
| GraphRAG    | 0.802 |  0.703 | 0.340 |
| CyANCHOR    | 0.837 |  0.772 | 0.406 |
