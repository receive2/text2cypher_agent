# Report — er (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `er`, 184 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-05T14:38:39-07:00. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.
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
| No Val Link | —         | 0.299 | 0.245 | 184 |   3 |        3 |
| FCAV        | vector    | 0.478 | 0.475 | 184 |   1 |        3 |
| ReAct       | fuzzy     | 0.582 | 0.616 | 184 |   0 |        3 |
| GraphRAG    | norm-Lev  | 0.690 | 0.843 | 184 |   0 |        3 |
| CyANCHOR    | fuzzy+lev | 0.745 | 0.905 | 184 |   0 |        3 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 3 of the 184 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.529 | 0.300 |   0.680 |  0.134 |
| FCAV        |  0.588 | 0.717 |   0.880 |  0.159 |
| ReAct       |  0.588 | 0.850 |   0.960 |  0.268 |
| GraphRAG    |  0.588 | 0.833 |   0.920 |  0.537 |
| CyANCHOR    |  0.588 | 0.867 |   0.960 |  0.622 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.500 |  0.311 | 0.226 |
| FCAV        | 0.500 |  0.510 | 0.323 |
| ReAct       | 0.500 |  0.623 | 0.387 |
| GraphRAG    | 1.000 |  0.715 | 0.548 |
| CyANCHOR    | 1.000 |  0.755 | 0.677 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.353 | 0.267 |   0.560 |  0.110 |
| FCAV        |  0.647 | 0.733 |   0.792 |  0.155 |
| ReAct       |  0.706 | 0.950 |   0.853 |  0.280 |
| GraphRAG    |  0.706 | 0.926 |   0.832 |  0.814 |
| CyANCHOR    |  0.679 | 0.977 |   0.872 |  0.908 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.278 | 0.097 |
| FCAV        | 0.000 |  0.526 | 0.258 |
| ReAct       | 0.000 |  0.658 | 0.452 |
| GraphRAG    | 0.500 |  0.867 | 0.748 |
| CyANCHOR    | 0.500 |  0.916 | 0.875 |
