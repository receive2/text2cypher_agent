# Report — politics (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `politics`, 360 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-09-15T04:32:14-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node_rel` · escalate `on` (≤3) · semantic_repair `on` (≤4) · empty_is_wrong `off` · value_snap `on`.

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
| No Val Link | —         | 0.108 | 0.132 | 360 |   9 |        0 |
| FCAV        | vector    | 0.342 | 0.383 | 360 |   9 |        0 |
| ReAct       | fuzzy     | 0.203 | 0.264 | 360 |   0 |        0 |
| GraphRAG    | norm-Lev  | 0.425 | 0.480 | 360 |   0 |        0 |
| CyANCHOR    | fuzzy+lev | 0.650 | 0.706 | 360 |   0 |        0 |

## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.333 | 0.190 |   0.102 |  0.098 | 0.071 |
| FCAV        |  0.389 | 0.667 |   0.306 |  0.289 | 0.374 |
| ReAct       |  0.444 | 0.476 |   0.265 |  0.116 | 0.222 |
| GraphRAG    |  0.667 | 0.857 |   0.449 |  0.387 | 0.343 |
| CyANCHOR    |  0.833 | 0.952 |   0.755 |  0.607 | 0.576 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.088 |  0.052 | 0.214 |
| FCAV        | 0.509 |  0.267 | 0.384 |
| ReAct       | 0.175 |  0.168 | 0.277 |
| GraphRAG    | 0.456 |  0.419 | 0.420 |
| CyANCHOR    | 0.684 |  0.649 | 0.634 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev | alias |
| ----------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link |  0.312 | 0.133 |   0.095 |  0.144 | 0.095 |
| FCAV        |  0.383 | 0.554 |   0.328 |  0.362 | 0.411 |
| ReAct       |  0.452 | 0.526 |   0.307 |  0.196 | 0.274 |
| GraphRAG    |  0.606 | 0.799 |   0.445 |  0.465 | 0.434 |
| CyANCHOR    |  0.767 | 0.986 |   0.771 |  0.666 | 0.672 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.088 |  0.080 | 0.242 |
| FCAV        | 0.476 |  0.324 | 0.436 |
| ReAct       | 0.196 |  0.221 | 0.373 |
| GraphRAG    | 0.515 |  0.474 | 0.474 |
| CyANCHOR    | 0.748 |  0.699 | 0.694 |
