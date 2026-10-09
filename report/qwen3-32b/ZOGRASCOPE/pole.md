# Report — pole (entity-perturbed ZOGRASCOPE)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** ZOGRASCOPE `pole`, 1283 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-08T14:39:23-05:00. LLMs: NER `qwen3-32b-deepinfra` · Cypher `qwen3-32b-deepinfra` · QA `qwen3-32b-deepinfra`.
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
| No Val Link | —         | 0.025 | 0.020 | 1283 |  94 |        0 |
| FCAV        | vector    | 0.072 | 0.075 | 1283 | 117 |        0 |
| ReAct       | fuzzy     | 0.143 | 0.129 | 1283 |   5 |        0 |
| GraphRAG    | norm-Lev  | 0.236 | 0.206 | 1283 |   3 |        0 |
| CyANCHOR    | fuzzy+lev | 0.320 | 0.268 | 1283 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.035 | 0.025 |   0.026 |  0.009 |
| FCAV        |  0.133 | 0.084 |   0.026 |  0.009 |
| ReAct       |  0.189 | 0.139 |   0.188 |  0.027 |
| GraphRAG    |  0.238 | 0.207 |   0.346 |  0.212 |
| CyANCHOR    |  0.329 | 0.267 |   0.534 |  0.230 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.012 |  0.025 | 0.028 |
| FCAV        | 0.148 |  0.064 | 0.081 |
| ReAct       | 0.346 |  0.128 | 0.137 |
| GraphRAG    | 0.444 |  0.217 | 0.242 |
| CyANCHOR    | 0.444 |  0.310 | 0.315 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.051 | 0.020 |   0.001 |  0.020 |
| FCAV        |  0.168 | 0.089 |   0.002 |  0.009 |
| ReAct       |  0.188 | 0.127 |   0.152 |  0.018 |
| GraphRAG    |  0.248 | 0.185 |   0.277 |  0.147 |
| CyANCHOR    |  0.312 | 0.225 |   0.453 |  0.128 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.015 |  0.021 | 0.017 |
| FCAV        | 0.193 |  0.065 | 0.074 |
| ReAct       | 0.361 |  0.109 | 0.132 |
| GraphRAG    | 0.430 |  0.178 | 0.240 |
| CyANCHOR    | 0.425 |  0.251 | 0.280 |
