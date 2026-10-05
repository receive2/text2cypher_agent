# Report — er (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold; a gold query that returns a whole node is matched by a prediction that selects exactly those nodes).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `er`, 185 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev).

**Run config.** Generated 2026-09-15T23:53:08-07:00. LLMs: NER `gpt-5.6-luna` · Cypher `gpt-5.6-luna` · QA `gpt-5.6-luna`.
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
| No Val Link | —         | 0.319 | 0.287 | 185 |   3 |        3 |
| FCAV        | vector    | 0.416 | 0.426 | 185 |   2 |        3 |
| ReAct       | fuzzy     | 0.535 | 0.569 | 185 |   0 |        3 |
| GraphRAG    | norm-Lev  | 0.692 | 0.817 | 185 |   0 |        3 |
| CyANCHOR    | fuzzy+lev | 0.686 | 0.808 | 185 |   0 |        3 |

> `err` = examples the **method** failed on (unrunnable generated Cypher, timeouts). `gold err` = examples whose **gold query itself** does not execute — a dataset defect that scores 0 for every method, not a property of the method. Both are scored 0 and kept in the denominator. At least 3 of the 185 examples have a broken gold; a method that fails earlier masks some of them behind its own error, so the per-method count is a lower bound.


## By perturbation strategy — EA

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.529 | 0.300 |   0.692 |  0.171 |
| FCAV        |  0.412 | 0.633 |   0.692 |  0.171 |
| ReAct       |  0.529 | 0.817 |   0.923 |  0.207 |
| GraphRAG    |  0.588 | 0.850 |   0.962 |  0.512 |
| CyANCHOR    |  0.588 | 0.833 |   0.962 |  0.512 |

## By query-difficulty — EA

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.500 |  0.336 | 0.226 |
| FCAV        | 0.000 |  0.441 | 0.323 |
| ReAct       | 0.500 |  0.579 | 0.323 |
| GraphRAG    | 1.000 |  0.704 | 0.613 |
| CyANCHOR    | 1.000 |  0.711 | 0.548 |

## By perturbation strategy — PSJS

| method      | casing |  typo | partial | abbrev |
| ----------- | -----: | ----: | ------: | -----: |
| No Val Link |  0.412 | 0.282 |   0.577 |  0.172 |
| FCAV        |  0.620 | 0.646 |   0.594 |  0.171 |
| ReAct       |  0.647 | 0.904 |   0.761 |  0.246 |
| GraphRAG    |  0.679 | 0.921 |   0.838 |  0.762 |
| CyANCHOR    |  0.679 | 0.900 |   0.877 |  0.745 |

## By query-difficulty — PSJS

| method      |  easy | medium |  hard |
| ----------- | ----: | -----: | ----: |
| No Val Link | 0.000 |  0.326 | 0.112 |
| FCAV        | 0.000 |  0.462 | 0.276 |
| ReAct       | 0.000 |  0.617 | 0.370 |
| GraphRAG    | 0.500 |  0.840 | 0.725 |
| CyANCHOR    | 0.500 |  0.835 | 0.691 |
