# Report — ZOGRASCOPE (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** ZOGRASCOPE `all graphs pooled`, 1283 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-08. LLMs: NER `deepseek-v4.1-flash` · Cypher `deepseek-v4.1-flash` · QA `deepseek-v4.1-flash`.

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
| No Val Link | —         | 0.062 | 0.040 | 1283 |   2 |        0 |
| FCAV        | vector    | 0.154 | 0.129 | 1283 |   0 |        0 |
| ReAct       | fuzzy     | 0.268 | 0.217 | 1283 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.383 | 0.294 | 1283 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.537 | 0.410 | 1283 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.112 | 0.058 |   0.073 |  0.000 |
| FCAV        |  0.308 | 0.175 |   0.064 |  0.000 |
| ReAct       |  0.301 | 0.245 |   0.419 |  0.080 |
| GraphRAG    |  0.427 | 0.317 |   0.568 |  0.416 |
| CyANCHOR    |  0.573 | 0.479 |   0.735 |  0.487 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.148 |  0.062 | 0.032 |
| FCAV        | 0.296 |  0.142 | 0.157 |
| ReAct       | 0.333 |  0.260 | 0.278 |
| GraphRAG    | 0.605 |  0.353 | 0.427 |
| CyANCHOR    | 0.568 |  0.512 | 0.625 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.110 | 0.034 |   0.036 |  0.004 |
| FCAV        |  0.287 | 0.145 |   0.039 |  0.003 |
| ReAct       |  0.255 | 0.206 |   0.324 |  0.030 |
| GraphRAG    |  0.345 | 0.240 |   0.450 |  0.281 |
| CyANCHOR    |  0.459 | 0.367 |   0.591 |  0.276 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.109 |  0.036 | 0.033 |
| FCAV        | 0.223 |  0.116 | 0.151 |
| ReAct       | 0.270 |  0.197 | 0.278 |
| GraphRAG    | 0.431 |  0.248 | 0.423 |
| CyANCHOR    | 0.438 |  0.371 | 0.552 |
