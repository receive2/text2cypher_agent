# Report — wwc (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `wwc`, 265 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-02T10:07:32-05:00. LLMs: NER `gpt-5.6-terra` · Cypher `gpt-5.6-terra` · QA `gpt-5.6-terra`.
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
| No Val Link | —         | 0.125 | 0.133 | 265 |   5 |       11 |
| FCAV        | vector    | 0.151 | 0.656 | 265 |   4 |       11 |
| ReAct       | fuzzy     | 0.460 | 0.582 | 265 |   0 |       12 |
| GraphRAG    | norm-Lev  | 0.528 | 0.673 | 265 |   0 |       12 |
| CyANCHOR    | fuzzy+lev | 0.551 | 0.718 | 265 |   0 |       12 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 12 of the 265 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.071 | 0.082 |   0.037 |  0.138 | 0.395 |
| FCAV        |  0.036 | 0.115 |   0.087 |  0.172 | 0.395 |
| ReAct       |  0.429 | 0.672 |   0.525 |  0.207 | 0.395 |
| GraphRAG    |  0.536 | 0.574 |   0.525 |  0.552 | 0.421 |
| CyANCHOR    |  0.500 | 0.607 |   0.562 |  0.569 | 0.447 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.153 |  0.148 | 0.046 |
| FCAV        | 0.208 |  0.180 | 0.031 |
| ReAct       | 0.597 |  0.531 | 0.169 |
| GraphRAG    | 0.722 |  0.594 | 0.185 |
| CyANCHOR    | 0.722 |  0.617 | 0.231 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.143 | 0.082 |   0.039 |  0.138 | 0.395 |
| FCAV        |  0.699 | 0.809 |   0.674 |  0.584 | 0.455 |
| ReAct       |  0.596 | 0.833 |   0.720 |  0.239 | 0.400 |
| GraphRAG    |  0.599 | 0.777 |   0.693 |  0.711 | 0.457 |
| CyANCHOR    |  0.666 | 0.819 |   0.766 |  0.722 | 0.484 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.181 |  0.148 | 0.048 |
| FCAV        | 0.791 |  0.726 | 0.370 |
| ReAct       | 0.694 |  0.639 | 0.345 |
| GraphRAG    | 0.853 |  0.705 | 0.409 |
| CyANCHOR    | 0.852 |  0.788 | 0.431 |
