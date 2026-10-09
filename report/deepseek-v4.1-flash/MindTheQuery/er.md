# Report — er (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `er`, 184 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-07T08:42:25-05:00. LLMs: NER `deepseek-v4.1-flash-deepinfra` · Cypher `deepseek-v4.1-flash-deepinfra` · QA `deepseek-v4.1-flash-deepinfra`.
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
| No Val Link | —         | 0.293 | 0.250 | 184 |   1 |        3 |
| FCAV        | vector    | 0.435 | 0.423 | 184 |   1 |        3 |
| ReAct       | fuzzy     | 0.511 | 0.510 | 184 |   0 |        3 |
| GraphRAG    | norm-Lev  | 0.712 | 0.869 | 184 |   0 |        3 |
| CyANCHOR    | fuzzy+lev | 0.734 | 0.870 | 184 |   0 |        3 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 3 of the 184 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.471 | 0.300 |   0.680 |  0.134 |
| FCAV        |  0.529 | 0.650 |   0.800 |  0.146 |
| ReAct       |  0.529 | 0.850 |   0.920 |  0.134 |
| GraphRAG    |  0.588 | 0.883 |   0.920 |  0.549 |
| CyANCHOR    |  0.647 | 0.817 |   0.880 |  0.646 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.500 |  0.311 | 0.194 |
| FCAV        | 0.500 |  0.457 | 0.323 |
| ReAct       | 0.500 |  0.543 | 0.355 |
| GraphRAG    | 1.000 |  0.748 | 0.516 |
| CyANCHOR    | 1.000 |  0.748 | 0.645 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.353 | 0.267 |   0.560 |  0.122 |
| FCAV        |  0.529 | 0.650 |   0.715 |  0.146 |
| ReAct       |  0.412 | 0.933 |   0.837 |  0.122 |
| GraphRAG    |  0.706 | 0.967 |   0.832 |  0.843 |
| CyANCHOR    |  0.706 | 0.917 |   0.792 |  0.894 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.291 | 0.065 |
| FCAV        | 0.000 |  0.463 | 0.258 |
| ReAct       | 0.000 |  0.562 | 0.290 |
| GraphRAG    | 0.500 |  0.893 | 0.775 |
| CyANCHOR    | 0.500 |  0.886 | 0.818 |
