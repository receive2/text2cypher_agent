# Report — er (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `er`, 184 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-07T05:58:31-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.261 | 0.232 | 184 |  23 |        0 |
| FCAV        | vector    | 0.359 | 0.352 | 184 |  23 |        1 |
| ReAct       | fuzzy     | 0.446 | 0.410 | 184 |   0 |        3 |
| GraphRAG    | norm-Lev  | 0.685 | 0.835 | 184 |   0 |        3 |
| CyANCHOR    | fuzzy+lev | 0.592 | 0.652 | 184 |   0 |        3 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 3 of the 184 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.412 | 0.300 |   0.680 |  0.073 |
| FCAV        |  0.353 | 0.533 |   0.800 |  0.098 |
| ReAct       |  0.412 | 0.700 |   0.880 |  0.134 |
| GraphRAG    |  0.588 | 0.850 |   0.920 |  0.512 |
| CyANCHOR    |  0.529 | 0.833 |   0.920 |  0.329 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.285 | 0.161 |
| FCAV        | 0.000 |  0.404 | 0.161 |
| ReAct       | 0.000 |  0.497 | 0.226 |
| GraphRAG    | 0.000 |  0.722 | 0.548 |
| CyANCHOR    | 0.500 |  0.636 | 0.387 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.353 | 0.267 |   0.560 |  0.082 |
| FCAV        |  0.529 | 0.526 |   0.661 |  0.094 |
| ReAct       |  0.412 | 0.683 |   0.781 |  0.098 |
| GraphRAG    |  0.679 | 0.936 |   0.832 |  0.794 |
| CyANCHOR    |  0.706 | 0.852 |   0.828 |  0.440 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.269 | 0.065 |
| FCAV        | 0.000 |  0.403 | 0.129 |
| ReAct       | 0.000 |  0.480 | 0.097 |
| GraphRAG    | 0.500 |  0.851 | 0.777 |
| CyANCHOR    | 0.000 |  0.709 | 0.415 |
