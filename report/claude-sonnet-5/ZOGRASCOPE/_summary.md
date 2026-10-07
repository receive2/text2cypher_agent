# Report — ZOGRASCOPE (all graphs pooled)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** ZOGRASCOPE `all graphs pooled`, 1283 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-10-06. LLMs: NER `claude-sonnet-5` · Cypher `claude-sonnet-5` · QA `claude-sonnet-5`.

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
| No Val Link | —         | 0.112 | 0.082 | 1283 |   8 |        0 |
| FCAV        | vector    | 0.239 | 0.199 | 1283 |   7 |        0 |
| ReAct       | fuzzy     | 0.392 | 0.304 | 1283 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.460 | 0.384 | 1283 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.557 | 0.447 | 1283 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.245 | 0.069 |   0.218 |  0.027 |
| FCAV        |  0.392 | 0.253 |   0.197 |  0.035 |
| ReAct       |  0.441 | 0.354 |   0.504 |  0.363 |
| GraphRAG    |  0.476 | 0.401 |   0.641 |  0.478 |
| CyANCHOR    |  0.580 | 0.494 |   0.697 |  0.681 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.296 |  0.091 | 0.133 |
| FCAV        | 0.556 |  0.205 | 0.266 |
| ReAct       | 0.642 |  0.375 | 0.375 |
| GraphRAG    | 0.741 |  0.425 | 0.504 |
| CyANCHOR    | 0.630 |  0.532 | 0.629 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.210 | 0.037 |   0.191 |  0.015 |
| FCAV        |  0.359 | 0.203 |   0.173 |  0.018 |
| ReAct       |  0.398 | 0.280 |   0.397 |  0.161 |
| GraphRAG    |  0.443 | 0.327 |   0.562 |  0.340 |
| CyANCHOR    |  0.498 | 0.411 |   0.562 |  0.401 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.225 |  0.057 | 0.134 |
| FCAV        | 0.371 |  0.163 | 0.281 |
| ReAct       | 0.429 |  0.281 | 0.353 |
| GraphRAG    | 0.509 |  0.337 | 0.522 |
| CyANCHOR    | 0.476 |  0.403 | 0.608 |
