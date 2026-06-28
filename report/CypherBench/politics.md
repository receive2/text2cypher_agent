# Report — politics (entity-perturbed CypherBench)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** CypherBench `politics`, 365 entity-perturbed test questions
(strategies: casing · typo · partial · abbrev · alias).

**Run config.** Generated 2026-06-24T05:26:00+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
CyANCHOR knobs: retrieval `fuzzy+lev` · tool `node_rel` · escalate `on`.

**Methods.**
- **No Val Link** — grounding bypassed (the perturbed surface form is used as-is).
- **FCAV (RAG)** — retrieve-then-generate baseline: embed the question, retrieve
  candidate values from a self-built value index, an LLM generates the entity JSON.
- **ReAct (Node + Rel)** — ReAct NER agent (fuzzy/BM25 retrieval) over node + relation tools.
- **GraphRAG** — Multi-Agent GraphRAG baseline: generate→execute→evaluate→repair; on
  error/empty it extracts the query's labels/values/rels, validates them, and proposes
  normalized-Levenshtein replacements, iterating the generator.
- **CyANCHOR (Node + Rel)** — our plan-and-execute grounder: decompose the question into
  entity mentions, route each to a database field, retrieve candidates with an LLM-judge
  corrective loop, then the Cypher LLM value-links. Retrieval is the union of independently
  toggleable arms — **fuzzy** (BM25) · **lev** (APOC normalized Levenshtein) · **vector**
  (in-graph embeddings).

---

## Overall

| method               | retrieval |    EA |  PSJS |   n | err |
| -------------------- | --------- | ----: | ----: | --: | --: |
| No Val Link          | —         | 0.101 | 0.123 | 365 |  13 |
| FCAV                 | vector    | 0.145 | 0.205 | 365 |  12 |
| ReAct (Node + Rel)   | fuzzy     | 0.370 | 0.423 | 365 |   0 |
| GraphRAG             | norm-Lev  | 0.548 | 0.616 | 365 |   0 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.707 | 0.750 | 365 |   0 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.135 | 0.134 |   0.085 |  0.037 | 0.134 |
| FCAV                 |  0.243 | 0.159 |   0.134 |  0.098 | 0.146 |
| ReAct (Node + Rel)   |  0.486 | 0.537 |   0.402 |  0.195 | 0.293 |
| GraphRAG             |  0.730 | 0.793 |   0.537 |  0.317 | 0.463 |
| CyANCHOR (fuzzy+lev) |  0.946 | 0.878 |   0.744 |  0.500 | 0.598 |

## By query-difficulty — EA

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.085 |  0.047 | 0.202 |
| FCAV                 | 0.153 |  0.094 | 0.228 |
| ReAct (Node + Rel)   | 0.373 |  0.344 | 0.412 |
| GraphRAG             | 0.593 |  0.557 | 0.509 |
| CyANCHOR (fuzzy+lev) | 0.797 |  0.656 | 0.746 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | abbrev | alias |
| -------------------- | -----: | ----: | ------: | -----: | ----: |
| No Val Link          |  0.197 | 0.135 |   0.110 |  0.064 | 0.149 |
| FCAV                 |  0.352 | 0.215 |   0.167 |  0.206 | 0.165 |
| ReAct (Node + Rel)   |  0.497 | 0.589 |   0.477 |  0.277 | 0.317 |
| GraphRAG             |  0.761 | 0.836 |   0.570 |  0.486 | 0.505 |
| CyANCHOR (fuzzy+lev) |  0.886 | 0.852 |   0.815 |  0.593 | 0.677 |

## By query-difficulty — PSJS

| method               |  easy | medium |  hard |
| -------------------- | ----: | -----: | ----: |
| No Val Link          | 0.073 |  0.062 | 0.251 |
| FCAV                 | 0.160 |  0.150 | 0.320 |
| ReAct (Node + Rel)   | 0.436 |  0.395 | 0.465 |
| GraphRAG             | 0.645 |  0.621 | 0.591 |
| CyANCHOR (fuzzy+lev) | 0.795 |  0.712 | 0.791 |
