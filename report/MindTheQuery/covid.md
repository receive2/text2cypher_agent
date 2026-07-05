# Report — covid (entity-perturbed MindTheQuery)

**Metrics.** EA = execution accuracy (predicted Cypher's result set matches gold).
PSJS = Provenance-Subgraph Jaccard Similarity (partial-credit subgraph overlap).
Higher is better. Denominator = ALL examples; any failure (agent error, empty/wrong result, or a non-executing gold) scores 0.

**Setup.** MindTheQuery `covid`, 342 entity-perturbed test questions
(strategies: casing · typo · partial · alias).

**Run config.** Generated 2026-06-23T10:31:18+02:00. LLMs: NER `gpt-4.1` · Cypher `gpt-4.1` · QA `gpt-4.1`.
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
| No Val Link          | —         | 0.023 | 0.060 | 342 | 192 |
| FCAV                 | vector    | 0.020 | 0.076 | 342 | 199 |
| ReAct (Node + Rel)   | fuzzy     | 0.164 | 0.282 | 342 |  59 |
| GraphRAG             | norm-Lev  | 0.377 | 0.460 | 342 |  59 |
| CyANCHOR (fuzzy+lev) | fuzzy+lev | 0.377 | 0.198 | 342 |  59 |

## By perturbation strategy — EA

| method               | casing |  typo | partial | alias |
| -------------------- | -----: | ----: | ------: | ----: |
| No Val Link          |  0.029 | 0.014 |   0.043 | 0.048 |
| FCAV                 |  0.029 | 0.014 |   0.029 | 0.048 |
| ReAct (Node + Rel)   |  0.229 | 0.175 |   0.116 | 0.095 |
| GraphRAG             |  0.314 | 0.396 |   0.435 | 0.095 |
| CyANCHOR (fuzzy+lev) |  0.457 | 0.392 |   0.333 | 0.238 |

## By query-difficulty — EA

| method               | medium |  hard |
| -------------------- | -----: | ----: |
| No Val Link          |  0.036 | 0.015 |
| FCAV                 |  0.036 | 0.010 |
| ReAct (Node + Rel)   |  0.139 | 0.180 |
| GraphRAG             |  0.401 | 0.361 |
| CyANCHOR (fuzzy+lev) |  0.365 | 0.385 |

## By perturbation strategy — PSJS

| method               | casing |  typo | partial | alias |
| -------------------- | -----: | ----: | ------: | ----: |
| No Val Link          |  0.092 | 0.048 |   0.062 | 0.124 |
| FCAV                 |  0.104 | 0.052 |   0.107 | 0.172 |
| ReAct (Node + Rel)   |  0.487 | 0.265 |   0.261 | 0.176 |
| GraphRAG             |  0.541 | 0.442 |   0.516 | 0.327 |
| CyANCHOR (fuzzy+lev) |  0.237 | 0.196 |   0.194 | 0.168 |

## By query-difficulty — PSJS

| method               | medium |  hard |
| -------------------- | -----: | ----: |
| No Val Link          |  0.070 | 0.053 |
| FCAV                 |  0.092 | 0.065 |
| ReAct (Node + Rel)   |  0.309 | 0.264 |
| GraphRAG             |  0.590 | 0.373 |
| CyANCHOR (fuzzy+lev) |  0.219 | 0.184 |
