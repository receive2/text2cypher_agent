# Report — covid (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `covid`, 326 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-07T02:31:29-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.021 | 0.026 | 326 | 163 |        6 |
| FCAV        | vector    | 0.028 | 0.050 | 326 | 154 |       12 |
| ReAct       | fuzzy     | 0.031 | 0.055 | 326 |   0 |       52 |
| GraphRAG    | norm-Lev  | 0.184 | 0.278 | 326 |   1 |       51 |
| CyANCHOR    | fuzzy+lev | 0.218 | 0.268 | 326 |   0 |       52 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 52 of the 326 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.029 | 0.017 |   0.056 |  0.000 | 0.020 |
| FCAV        |  0.029 | 0.023 |   0.056 |  0.069 | 0.000 |
| ReAct       |  0.029 | 0.011 |   0.083 |  0.069 | 0.041 |
| GraphRAG    |  0.200 | 0.153 |   0.306 |  0.207 | 0.184 |
| CyANCHOR    |  0.314 | 0.203 |   0.444 |  0.069 | 0.122 |

## By query-difficulty — EA

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.045 | 0.005 |
| FCAV        |  0.052 | 0.010 |
| ReAct       |  0.052 | 0.016 |
| GraphRAG    |  0.239 | 0.146 |
| CyANCHOR    |  0.246 | 0.198 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.045 | 0.015 |   0.056 |  0.000 | 0.045 |
| FCAV        |  0.070 | 0.042 |   0.083 |  0.076 | 0.025 |
| ReAct       |  0.086 | 0.022 |   0.143 |  0.069 | 0.079 |
| GraphRAG    |  0.392 | 0.197 |   0.467 |  0.375 | 0.291 |
| CyANCHOR    |  0.419 | 0.212 |   0.516 |  0.246 | 0.195 |

## By query-difficulty — PSJS

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.049 | 0.010 |
| FCAV        |  0.065 | 0.039 |
| ReAct       |  0.088 | 0.032 |
| GraphRAG    |  0.292 | 0.268 |
| CyANCHOR    |  0.305 | 0.242 |
