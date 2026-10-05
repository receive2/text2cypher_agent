# Report — covid (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `covid`, 327 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-10-03T20:49:35-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.031 | 0.100 | 327 | 113 |       31 |
| FCAV        | vector    | 0.034 | 0.089 | 327 | 109 |       33 |
| ReAct       | fuzzy     | 0.131 | 0.232 | 327 |   0 |       52 |
| GraphRAG    | norm-Lev  | 0.303 | 0.489 | 327 |   0 |       52 |
| CyANCHOR    | fuzzy+lev | 0.322 | 0.492 | 326 |   0 |       52 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 52 of the 327 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.057 | 0.011 |   0.056 |  0.103 | 0.020 |
| FCAV        |  0.000 | 0.028 |   0.083 |  0.069 | 0.020 |
| ReAct       |  0.143 | 0.152 |   0.139 |  0.103 | 0.061 |
| GraphRAG    |  0.371 | 0.292 |   0.444 |  0.207 | 0.245 |
| CyANCHOR    |  0.286 | 0.305 |   0.528 |  0.207 | 0.327 |

## By query-difficulty — EA

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.060 | 0.010 |
| FCAV        |  0.067 | 0.010 |
| ReAct       |  0.104 | 0.150 |
| GraphRAG    |  0.284 | 0.316 |
| CyANCHOR    |  0.254 | 0.370 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.179 | 0.069 |   0.083 |  0.155 | 0.133 |
| FCAV        |  0.094 | 0.062 |   0.093 |  0.080 | 0.185 |
| ReAct       |  0.339 | 0.224 |   0.165 |  0.246 | 0.223 |
| GraphRAG    |  0.528 | 0.450 |   0.696 |  0.493 | 0.448 |
| CyANCHOR    |  0.543 | 0.410 |   0.769 |  0.492 | 0.548 |

## By query-difficulty — PSJS

| method      | medium |  hard |
| ----------- | -----: | ----: |
| No Val Link |  0.087 | 0.109 |
| FCAV        |  0.094 | 0.086 |
| ReAct       |  0.212 | 0.246 |
| GraphRAG    |  0.540 | 0.454 |
| CyANCHOR    |  0.503 | 0.484 |
