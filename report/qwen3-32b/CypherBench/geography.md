# Report — geography (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `geography`, 331 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-08T07:29:17-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.069 | 0.088 | 331 |  31 |        0 |
| FCAV        | vector    | 0.196 | 0.244 | 331 |  35 |        0 |
| ReAct       | fuzzy     | 0.224 | 0.280 | 331 |   1 |        0 |
| GraphRAG    | norm-Lev  | 0.396 | 0.459 | 331 |   5 |        1 |
| CyANCHOR    | fuzzy+lev | 0.532 | 0.616 | 331 |   0 |        0 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 1 of the 331 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.111 | 0.042 |   0.127 |  0.038 | 0.062 |
| FCAV        |  0.361 | 0.146 |   0.218 |  0.127 | 0.204 |
| ReAct       |  0.611 | 0.208 |   0.291 |  0.051 | 0.195 |
| GraphRAG    |  0.611 | 0.562 |   0.400 |  0.329 | 0.301 |
| CyANCHOR    |  0.750 | 0.646 |   0.509 |  0.430 | 0.496 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.036 |  0.024 | 0.159 |
| FCAV        | 0.236 |  0.178 | 0.206 |
| ReAct       | 0.255 |  0.213 | 0.224 |
| GraphRAG    | 0.527 |  0.325 | 0.439 |
| CyANCHOR    | 0.618 |  0.473 | 0.579 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.131 | 0.042 |   0.144 |  0.094 | 0.061 |
| FCAV        |  0.503 | 0.160 |   0.197 |  0.186 | 0.262 |
| ReAct       |  0.708 | 0.295 |   0.318 |  0.129 | 0.224 |
| GraphRAG    |  0.706 | 0.622 |   0.359 |  0.464 | 0.356 |
| CyANCHOR    |  0.827 | 0.738 |   0.566 |  0.553 | 0.567 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.036 |  0.039 | 0.190 |
| FCAV        | 0.255 |  0.236 | 0.252 |
| ReAct       | 0.273 |  0.262 | 0.312 |
| GraphRAG    | 0.564 |  0.408 | 0.485 |
| CyANCHOR    | 0.654 |  0.564 | 0.681 |
