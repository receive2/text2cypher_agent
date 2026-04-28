# Text-to-Cypher Agent

A natural-language-to-Cypher pipeline for Neo4j graph databases.  
Ask questions in plain English → the agent extracts entities, generates Cypher, runs it, and returns a human-readable answer.

---

## How it works

```
User question
     │
     ▼
┌─────────────────────────────────────────────────────┐
│ 1. NER Agent  (ner_agent_auto.py)                   │
│    • FAISS selects the most relevant @tools         │
│    • Tools run fulltext search to get canonical     │
│      entity values from the graph                   │
│    • Output: {"Movie.title": ["The Matrix"], ...}   │
└──────────────────┬──────────────────────────────────┘
                   │ entity values
                   ▼
┌─────────────────────────────────────────────────────┐
│ 2. Cypher Generator  (GraphCypherQAChain)           │
│    • LLM generates a Cypher query using the         │
│      graph schema + extracted entity filters        │
└──────────────────┬──────────────────────────────────┘
                   │ Cypher query
                   ▼
┌─────────────────────────────────────────────────────┐
│ 3. Neo4j execution + QA formatting                  │
│    • Query runs on the live database                │
│    • LLM formats the rows into a natural-language   │
│      answer                                         │
└─────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10 – 3.12 |
| Neo4j | **5.18+** (native vector indexes required for hybrid retrieval; fulltext-only fallback works on 4.4+ if you `--skip-embeddings`) |
| OpenAI API key | GPT-4 class model recommended; also used by the default `text-embedding-3-small` embedding backend |

---

## Quick Start

### 1 — Install dependencies

```bash
git clone <repo-url>
cd t2c

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
pip install faiss-cpu            # or faiss-gpu for CUDA
```

### 2 — Create your `.env` file

Create a `.env` file in the project root:

```dotenv
# ── Neo4j (required) ──────────────────────────────────────────────────────────
NEO4J_URI=bolt://localhost:7687     # or neo4j+s://... for AuraDB
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j                # the database name inside Neo4j

# ── OpenAI (required) ─────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1                # or gpt-4o, gpt-4-turbo, etc.
OPENAI_BASE_URL=                    # leave blank for api.openai.com
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# ── Azure OpenAI (optional — replaces OpenAI when all three are set) ──────────
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=
AZURE_OPENAI_API_VERSION=2024-05-01-preview
```

> **AuraDB note:** URI format is `neo4j+s://<id>.databases.neo4j.io`, database name is usually `neo4j`.

### 3 — Run the one-click setup

```bash
python setup_project.py
```

That's it. The script runs all 10 setup steps automatically and prints the status of each one:

```
══════════════════ Text-to-Cypher Project Setup ══════════════════

──────────────────────────────────────────────────────────────────
  Step 1 / 10 — Checking environment variables
──────────────────────────────────────────────────────────────────
  ✓  NEO4J_URI = bolt://...
  ✓  NEO4J_DATABASE = 'neo4j'
  ✓  Embedding backend = 'openai'  (text-embedding-3-small, dim=1536)
  ✓  LLM credentials found (OpenAI / Azure OpenAI)

──────────────────────────────────────────────────────────────────
  Step 2 / 10 — Testing Neo4j connection
──────────────────────────────────────────────────────────────────
  ✓  Connected to database 'movies'
  ✓  Node labels found: ['Movie', 'Person']
  ✓  Neo4j version 5.28.3 (>= 5.18 required)

  ... (steps 3–10) ...

══════════════════════ Setup Complete ════════════════════════════

  Embedding backend  : 'openai' (text-embedding-3-small, dim=1536)
  Retrieval mode     : 'fuzzy'
  Vector indexes     :
                       • vec_idx_node_movie_title
                       • vec_idx_node_movie_tagline
                       • vec_idx_node_person_name

  Try a query:
    python ner_agent_auto.py "Your question here" --verbose
```

**What each step does:**

| Step | Script called | Output |
|---|---|---|
| 1 | *(env check)* | Validates `.env` + reports active embedding backend |
| 2 | *(Neo4j driver)* | Confirms connection, lists labels, probes Neo4j ≥ 5.18 |
| 3 | `gen_schema_csv` | `schema_nodes.csv`, `schema_relations.csv` |
| 4 | `gen_schema_meta` | `schema_meta.json` (LLM-inferred `id_property`, topics, descriptions) |
| 5 | `neo4j_search` | Creates all fulltext indexes in Neo4j |
| 6 | `embedding_helper` | **NEW** — auto-discovers embeddable properties, embeds all distinct values, writes back via `db.create.setNodeVectorProperty` |
| 7 | `embedding_helper` | **NEW** — creates one native vector index per (label, property) entry |
| 8 | `gen_tools` | `generated_node_tools.py`, `generated_rel_tools.py` |
| 9 | `gen_system_prompt` | Fresh `config.py` (system prompts + schema constants) |
| 10 | `ner_agent_auto` | `faiss_tools_auto/` tool-selection index |

> **Step 4** is what makes the pipeline domain-agnostic. It uses the LLM to analyze the schema CSVs and infer which property identifies each node label (e.g. `title` for Movie, `name` for Person), plus short topic phrases used for NER extraction. This metadata flows into Step 6 (auto-discovery decides which properties get embedded) and Step 8 (so generated tools have accurate descriptions for any database).

**Optional flags:**

```bash
python setup_project.py --database my_db        # target a specific database
python setup_project.py --skip-faiss            # skip step 10
python setup_project.py --skip-embeddings       # skip steps 6 + 7 (legacy fuzzy-only)
python setup_project.py --rediscover            # re-run embeddable-property discovery
python setup_project.py --reset-embeddings      # drop + null + re-embed (e.g. after backend swap)
python setup_project.py --yes                   # non-interactive (CI / scripting)
python setup_project.py --verbose               # show full tracebacks on errors
```

---

## Hybrid retrieval (vector + fuzzy)

Each value-lookup tool corresponds to one `(node_label, property)` pair (e.g. `Movie.title`, `Person.name`). v1 adds vector retrieval to **node** value-lookup tools while keeping relationship-property tools and structural-traversal tools on the legacy fuzzy code path. The hybrid pipeline is opt-in via a single config switch — defaults preserve existing behavior bit-identically.

### One-command setup on a fresh Neo4j database

```bash
# Point .env at the new database, then:
python setup_project.py
```

The setup auto-discovers which properties to embed (text-typed, name-hint match, or long-enough fallback), prompts you to confirm the list, and writes it into `vector_config.py:EMBEDDABLE_PROPERTIES`. From then on every run reads that curated list — no rediscovery happens unless you pass `--rediscover`.

### Switching retrieval mode (ablation studies)

Edit one line in `vector_config.py`:

```python
TOOL_RETRIEVAL_MODE = "fuzzy"     # "fuzzy" | "vector" | "hybrid"
```

| Mode | Path |
|---|---|
| `fuzzy` | Legacy Lucene fulltext (default; bit-identical to pre-hybrid behavior) |
| `vector` | Embed query → `db.index.vector.queryNodes` → top `HYBRID_FINAL_TOP_K` |
| `hybrid` | Run both, fuse via `HYBRID_STRATEGY` (RRF default; `weighted` available) |

**No regeneration of `generated_*_tools.py` is needed** — the node value-lookup tools read `TOOL_RETRIEVAL_MODE` at call time. Just edit the config and re-run:

```bash
python ner_agent_auto.py "Who directed Memento?" --verbose
```

### Swapping embedding backends

Two backends ship in `vector_config.py`:

| Backend | Model | Dim | When to use |
|---|---|---|---|
| `openai` (default) | `text-embedding-3-small` | 1536 | Cheap, fast, no local GPU needed |
| `sentence_transformers` | `BAAI/bge-base-en-v1.5` | 768 | Open-source; required for paper reproducibility runs |

Switch by editing one line:

```python
EMBEDDING_BACKEND = "sentence_transformers"
```

If the new backend has a different dimension (1536 → 768), you must rebuild the embeddings AND drop the old vector indexes:

```bash
pip install sentence-transformers torch    # install the optional backend
python setup_project.py --reset-embeddings
```

The OpenAI path requires no extra installs — it reuses the `openai` package already pinned in `requirements.txt`.

### Switching backend WITHOUT re-generating tools / system prompt / FAISS

Already ran `setup_project.py` once and only want to swap the embedding backend (e.g. OpenAI ↔ BGE)? Use the dedicated one-click helper — it skips schema regen, tool regen, system-prompt regen, and FAISS rebuild, because those artefacts are independent of which embedding backend powers vector retrieval.

**Procedure (OpenAI → BGE):**

```bash
# 1. Install the open-source backend if you haven't
pip install sentence-transformers torch
```

```python
# 2. Edit vector_config.py — change ONE line
EMBEDDING_BACKEND = "sentence_transformers"
```

```bash
# 3. Run the one-click swap
python switch_embedding_backend.py
```

**Procedure (BGE → OpenAI):**

```python
# 1. Edit vector_config.py — change ONE line
EMBEDDING_BACKEND = "openai"
```

```bash
# 2. Run the one-click swap
python switch_embedding_backend.py
```

(No `pip install` needed for this direction — the `openai` package is already in `requirements.txt`.)

**What the script does (5 steps, fully automated):**

1. Reads `EMBEDDING_BACKEND` / model / dim from `vector_config.py`
2. Pre-flight checks (deps installed, Neo4j env vars, live dim probe via `verify_backend()`)
3. Drops the old vector indexes + clears the old embedding properties
4. Re-embeds every distinct value with the new backend
5. Recreates vector indexes at the new dim

`generated_node_tools.py`, `generated_rel_tools.py`, `config.py`, and `faiss_tools_auto/` are intentionally NOT touched.

**Flags:**

```bash
python switch_embedding_backend.py --yes          # skip confirmation prompt
python switch_embedding_backend.py --database X   # override NEO4J_DATABASE
```

**Verify the swap:**

```bash
python -c "import vector_config as vc; \
print(vc.EMBEDDING_BACKEND, vc.EMBEDDING_MODEL_NAME, vc.EMBEDDING_DIMENSIONS)"
# → sentence_transformers BAAI/bge-base-en-v1.5 768

python ner_agent_auto.py "Who directed Memento?" --verbose
# t2c.retrieval log line should show vector_top5=[...] populated.
```

### Reading tool-call logs (paper error analysis)

Every value-lookup call emits a structured line on the `t2c.retrieval` logger, including the query, the active mode, the top-5 fuzzy candidates with scores, the top-5 vector candidates with scores, and the final fused result:

```
[t2c.retrieval] query='matrix' label=Movie prop=title mode=hybrid
                fuzzy_top5=[{'value': 'The Matrix', 'score': 4.8123}, ...]
                vector_top5=[{'value': 'The Matrix Revolutions', 'score': 0.9132}, ...]
                final=['The Matrix', 'The Matrix Reloaded', 'The Matrix Revolutions', ...]
```

To capture the trace into a file:

```python
import logging
logging.getLogger("t2c.retrieval").setLevel(logging.INFO)
logging.getLogger("t2c.retrieval").addHandler(logging.FileHandler("retrieval.log"))
```

To silence it during interactive use:

```python
logging.getLogger("t2c.retrieval").setLevel(logging.WARNING)
```

### Standalone backfill (without rebuilding the graph)

Use this when you already ran `setup_project.py` once and just need to rebuild embeddings (e.g. after swapping backends, or after Neo4j data changes):

```bash
python setup_project.py --skip-faiss --reset-embeddings
```

Or call the helpers directly from Python:

```python
from neo4j import GraphDatabase
from embedding_helper import (
    backfill_embeddings, create_vector_indexes, verify_backend,
)
import vector_config as vc, os

verify_backend()                           # dim sanity check
driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
)
db = os.environ.get("NEO4J_DATABASE", "neo4j")
backfill_embeddings(driver, db, vc.EMBEDDABLE_PROPERTIES)
create_vector_indexes(driver, db, vc.EMBEDDABLE_PROPERTIES)
driver.close()
```

### 4 — Ask a question

```bash
# Full pipeline: NER → Cypher → Neo4j → answer
python ner_agent_auto.py "Who acted in The Matrix?"

# Show tool selection, agent trace, and generated Cypher
python ner_agent_auto.py "How many movies were released before 2000?" --verbose

# NER step only (skip Cypher generation)
python ner_agent_auto.py "movies by Tom Hanks" --ner-only
```

Or call from Python:

```python
from ner_agent_auto import ask_auto

result = ask_auto("What movies did Keanu Reeves star in?")
print(result["cypher"])   # the generated Cypher query
print(result["result"])   # natural-language answer
print(result["context"])  # raw rows returned by Neo4j
```

---

## Testing

### Fulltext search deduplication test

`test_neo4j_search.py` verifies that the fulltext search functions return **unique property values** (no duplicates), ranked by the best matching score.

```bash
python test_neo4j_search.py
```

The script runs 5 test cases:

| # | Test | What it checks |
|---|---|---|
| 1 | `top_similar_values` — Movie.title | No duplicate values, descending scores, no nulls, k limit |
| 2 | `top_similar_values` — Person.name | Same checks on a different node label |
| 3 | `search_tool` — Movie.title | Returns `list[str]` with no duplicates |
| 4 | `top_similar_rel_values` — ACTED_IN.roles | No duplicate values, descending scores, no nulls, k limit |
| 5 | `search_rel_tool` — REVIEWED.summary | Returns `list[str]` with no duplicates |

Example output:

```
─── Test: top_similar_values (Movie.title) ───
  Query: 'The Matrix' | Label: Movie | Property: title | k=10
     1. The Matrix  (score=2.5390)
     2. The Matrix Reloaded  (score=1.4138)
     3. The Matrix Revolutions  (score=1.4138)
  [PASS] No duplicate values  (3 results)
  [PASS] Scores in descending order
  [PASS] No None values
  [PASS] Result count (3) <= k (10)

==================================================
Results: 5 passed, 0 failed, 5 total
==================================================
```

> **Note:** Requires a running Neo4j instance with the movies dataset loaded and `.env` configured.

### CypherBench-style evaluation (Execution Accuracy / Match)

`metrics_CypherBench.py` runs the agent over a CypherBench-style test set and reports **Execution Accuracy (EA, multiset)** and **Execution Match (EM, ordered)**. Result-set comparison is delegated to `cypher_eval_normalize.normalize_result_set`, which structurally expands `Node` / `Relationship` / `Path` cells (label-set + property-set, **never** `element_id`), rounds floats to a configurable epsilon (default `1e-6`), and sorts `collect()`-style list cells unless the gold query has a top-level `ORDER BY`. EA stays multiset and EM stays ordered in both modes — the `ORDER BY` heuristic only governs `sort_collections` inside `collect()` cells, so the EA−EM gap remains a meaningful "fraction of items where ordering matters" signal.

```bash
# Default (handles RETURN p, RETURN p, m, RETURN path correctly)
python metrics_CypherBench.py --dataset path/to/test.jsonl --out results.jsonl

# Reproduce upstream CypherBench's published numbers exactly
python metrics_CypherBench.py --dataset path/to/test.jsonl --strict-cypherbench-mode
```

Offline unit tests for the normaliser:

```bash
python test_cypher_eval_normalize.py
```

---

## Re-running after a schema change

If your Neo4j database schema changes (new labels, properties, or relationships added), just re-run the setup script:

```bash
python setup_project.py
```

Or run only the affected steps manually:

```bash
python gen_schema_csv.py                        # re-export schema CSVs
python gen_schema_meta.py                       # re-infer schema metadata (LLM)
python gen_tools.py                             # regenerate @tool functions
python gen_system_prompt.py                     # regenerate config.py
python ner_agent_auto.py --rebuild "test"       # rebuild the FAISS index
```

---

## Advanced: manual step-by-step setup

If you prefer to run each step individually or need to debug a specific stage:

| # | Command | What it does |
|---|---|---|
| 1 | `python neo4j_diag.py` | Verify connection and list node labels |
| 2 | `python gen_schema_csv.py --print-summary` | Export schema to CSV and print a summary |
| 3 | `python gen_schema_meta.py --verbose` | Infer `id_property`, topics, descriptions via LLM |
| 4 | *(fulltext indexes — handled by setup_project.py)* | Create all Neo4j fulltext indexes |
| 5 | `python gen_tools.py` | Generate `@tool` functions from the live schema |
| 6 | `python gen_system_prompt.py` | Generate `config.py` from scratch |
| 7 | `python ner_agent_auto.py --rebuild "test"` | Build the FAISS tool-selection index |

> **Tip:** Verify fulltext indexes in the Neo4j Browser with  
> `SHOW FULLTEXT INDEXES YIELD name, state`  
> All states should be `ONLINE` before running queries.

---

## Project file overview

| File | Purpose |
|---|---|
| `.env` | Credentials — **never commit this file** |
| `requirements.txt` | Python dependencies |
| `setup_project.py` | **One-click setup** — runs all 10 setup steps automatically |
| `switch_embedding_backend.py` | **One-click backend swap** — re-embeds + rebuilds vector indexes after editing `EMBEDDING_BACKEND` in `vector_config.py`; does NOT regenerate tools / system prompt / FAISS |
| `config.py` | **Auto-generated** system prompts + schema constants |
| `neo4j_search.py` | Fulltext index management + `search_tool()` / `search_rel_tool()` |
| `test_neo4j_search.py` | Tests for fulltext search deduplication + score ordering |
| `gen_schema_csv.py` | Export full schema to `schema_nodes.csv` + `schema_relations.csv` |
| `gen_schema_meta.py` | LLM-infer `id_property`, topics, descriptions → `schema_meta.json` |
| `gen_tools.py` | Generate `@tool` functions from the live schema + `schema_meta.json` |
| `generated_node_tools.py` | **Auto-generated** node property search tools |
| `generated_rel_tools.py` | **Auto-generated** relationship search tools |
| `gen_system_prompt.py` | Generate complete `config.py` from the live schema |
| `tool_search.py` | FAISS-based tool search engine |
| `ner_agent.py` | NER agent (fixed tool list — for reference) |
| `ner_agent_auto.py` | NER agent with automatic FAISS tool selection |
| `faiss_tools_auto/` | **Auto-generated** FAISS vector index (gitignore this) |
| `schema_nodes.csv` | **Auto-generated** node schema export |
| `schema_relations.csv` | **Auto-generated** relationship schema export |
| `schema_meta.json` | **Auto-generated** LLM-inferred schema metadata |

---

## Troubleshooting

**Connection refused / DNS error**  
→ Check `NEO4J_URI` in `.env`. For local Neo4j use `bolt://localhost:7687`. For AuraDB use `neo4j+s://`.

**`No module named 'generated_node_tools'`**  
→ Run `python setup_project.py` or `python gen_tools.py` first.

**`Missing required env var: OPENAI_API_KEY`**  
→ Make sure `.env` exists in the project root and all required keys are set.

**Fulltext index search returns no results**  
→ Check that indexes are `ONLINE` in the Neo4j Browser.  
→ Re-run `python setup_project.py` or `python neo4j_search.py`.

**FAISS index stale after schema change**  
→ Re-run `python setup_project.py` or `python ner_agent_auto.py --rebuild "test"`.

**`SyntaxError` in `generated_rel_tools.py`**  
→ Re-run `python gen_tools.py` — caused by a Neo4j relType formatting artifact, now fixed.
