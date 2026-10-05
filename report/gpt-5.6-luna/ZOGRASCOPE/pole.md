# Report — pole (entity-perturbed ZOGRASCOPE)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** ZOGRASCOPE `pole`, 1290 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-04T10:03:04-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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

| method      | retrieval |    EA |  PSJS |    n | err | gold err |
| ----------- | --------- | ----: | ----: | ---: | --: | -------: |
| No Val Link | —         | 0.043 | 0.027 | 1290 |   3 |        0 |
| FCAV        | vector    | 0.115 | 0.103 | 1290 |   9 |        0 |
| ReAct       | fuzzy     | 0.281 | 0.216 | 1283 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.301 | 0.240 | 1283 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.472 | 0.367 | 1283 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.112 | 0.038 |   0.025 |  0.027 |
| FCAV        |  0.224 | 0.136 |   0.025 |  0.018 |
| ReAct       |  0.350 | 0.259 |   0.338 |  0.230 |
| GraphRAG    |  0.301 | 0.250 |   0.483 |  0.283 |
| CyANCHOR    |  0.476 | 0.410 |   0.692 |  0.451 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.062 |  0.044 | 0.032 |
| FCAV        | 0.185 |  0.107 | 0.120 |
| ReAct       | 0.506 |  0.266 | 0.262 |
| GraphRAG    | 0.580 |  0.274 | 0.315 |
| CyANCHOR    | 0.605 |  0.444 | 0.536 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.109 | 0.021 |   0.005 |  0.015 |
| FCAV        |  0.198 | 0.126 |   0.011 |  0.015 |
| ReAct       |  0.281 | 0.202 |   0.265 |  0.137 |
| GraphRAG    |  0.269 | 0.200 |   0.375 |  0.203 |
| CyANCHOR    |  0.381 | 0.330 |   0.522 |  0.285 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.056 |  0.026 | 0.025 |
| FCAV        | 0.136 |  0.093 | 0.128 |
| ReAct       | 0.358 |  0.197 | 0.245 |
| GraphRAG    | 0.405 |  0.199 | 0.346 |
| CyANCHOR    | 0.425 |  0.328 | 0.496 |
