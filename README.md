# Text-to-Cypher Agent

A natural-language-to-Cypher pipeline for Neo4j graph databases.  
Ask questions in plain English → it **grounds** the (possibly perturbed)
entities to canonical database values, generates Cypher, runs it, and returns a
human-readable answer.

> **New here? Start with [QUICKSTART.md](QUICKSTART.md)** — clone → run → experiments in ~10 minutes. This README is the full reference.

---

## How it works

```
User question
     │
     ▼
┌─────────────────────────────────────────────────────┐
│ 1. Value linking  (ner_agent_auto.py → plan_exec.py)│
│    • Ground the entities in the question to the      │
│      canonical DB values the WHERE clause needs      │
│    • Default = CyANCHOR: decompose the question →    │
│      route each mention to a field → retrieve        │
│      (fuzzy ∪ lev ∪ vec) with an LLM corrective loop  │
│    • Output: candidate canonical values per mention  │
└──────────────────┬──────────────────────────────────┘
                   │ candidate canonical values
                   ▼
┌─────────────────────────────────────────────────────┐
│ 2. Cypher generation  (GraphCypherQAChain)          │
│    • LLM writes Cypher from the graph schema + the   │
│      candidate values (it does the value-linking)    │
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

The method is selected by the `METHOD` axis — `no_val_link` · `fcav` · `react` ·
`graphrag` · `cyanchor` (see [Methods](#value-linking-modes)). The shipped method is
**CyANCHOR** (`cyanchor`); `No Val Link`, `FCAV`, `ReAct`, and `GraphRAG` are the
baselines. Ablation: [report/CypherBench/flight_accident.md](report/CypherBench/flight_accident.md).

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
| 3 | `schema.gen_schema_csv` | `schema_data/schema_nodes.csv`, `schema_data/schema_relations.csv` |
| 4 | `schema.gen_schema_meta` | `schema_data/schema_meta.json` (LLM-inferred `id_property`, topics, descriptions) |
| 5 | `neo4j_lib.neo4j_search` | Creates all fulltext indexes in Neo4j |
| 6 | `embedding.embedding_helper` | Auto-discovers embeddable properties, embeds all distinct values, writes back via `db.create.setNodeVectorProperty` |
| 7 | `embedding.embedding_helper` | Creates one native vector index per (label, property) entry |
| 8 | `tools.gen_tools` | `generated/generated_node_tools.py`, `generated/generated_rel_tools.py` |
| 9 | `schema.gen_system_prompt` | Fresh `agent/prompts.py` (system prompts + schema constants) |
| 10 | `ner_agent_auto` | `generated/faiss` tool-selection index |

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

## Value-linking modes

The method is chosen by a single `METHOD` axis in `config.py` (env-overridable),
plus CyANCHOR's retrieval/tool sub-axes, resolved into a `GroundingSpec`:

| axis | values |
|---|---|
| `METHOD` | `no_val_link` · `fcav` · `react` · `graphrag` · `cyanchor` |
| `RETRIEVAL_FUZZY` / `RETRIEVAL_VECTOR` / `RETRIEVAL_LEVENSHTEIN` | `0`/`1` each — CyANCHOR's retrieval arms (≥1 on; defaults `1`/`0`/`1`) |
| `TOOL_TYPE` | `node` · `node_rel`  (react / cyanchor) |
| `CYPHER_SEMANTIC_REPAIR` / `CYPHER_REPAIR_MAX_ROUNDS` / `CYPHER_EMPTY_IS_WRONG` | CyANCHOR-only result-level self-correction (defaults `1` / `4` / `1`) |

- **`no_val_link`** — grounding bypassed; only schema + question reach the Cypher LLM.
- **`fcav`** — retrieve-then-generate RAG baseline (embed question → retrieve values
  from a self-built value index → LLM generates the entity JSON). Build the index
  with `setup_fcav.py` first.
- **`react`** — ReAct NER-agent grounder (baseline); fixed fuzzy/BM25 retrieval over
  `TOOL_TYPE` tools.
- **`graphrag`** — Multi-Agent GraphRAG baseline: **no pre-grounding** — generate
  Cypher → execute → an LLM evaluator classifies (accept / semantic-defect /
  error-or-empty); on error/empty it extracts the query's labels, property–value
  pairs and relationships, validates them against the DB, proposes normalized-
  Levenshtein replacements for invalid values, and regenerates — up to
  `GRAPHRAG_MAX_ITER` rounds. Knobs: `GRAPHRAG_*` in `config.py`. Writeup:
  [docs/multi_agent_graphrag.md](docs/multi_agent_graphrag.md).
- **`cyanchor`** — **CyANCHOR**, the shipped method: decompose the question → route each
  mention to a field → retrieve candidates with an LLM corrective loop → hand candidates
  to the Cypher LLM, which generates, executes, and **self-corrects** on the result: a DB
  error triggers a CoT error-repair, and a successfully-executed but semantically wrong
  result (an LLM evaluator judges *incorrect / illogical / incomplete / empty*) triggers a
  **grounding-aware regeneration** — the candidate grounding is kept and the semantic
  feedback + CoT are added (anti-oscillation: the final query is the first *accepted*
  attempt, else the first executable one, so repair can only match-or-beat the no-repair
  result). Knobs: `CYPHER_SEMANTIC_REPAIR` / `CYPHER_REPAIR_MAX_ROUNDS` /
  `CYPHER_EMPTY_IS_WRONG`. Retrieval is the **union of three independently-toggleable arms**:
  `RETRIEVAL_FUZZY` (BM25), `RETRIEVAL_LEVENSHTEIN` (APOC normalized edit-distance — no
  embeddings, high-ROI), `RETRIEVAL_VECTOR` (in-graph embeddings). `TOOL_TYPE` = `node` | `node_rel`.

Example — CyANCHOR `fuzzy+lev` (no embeddings needed), node + relation tools:

```bash
METHOD=cyanchor RETRIEVAL_VECTOR=0 TOOL_TYPE=node_rel python eval_run.py
```

Example — a baseline (Multi-Agent GraphRAG):

```bash
METHOD=graphrag python eval_run.py
```

> Back-compat: the legacy `VAL_LINK_MODE` / `AGENT_TYPE` / `RETRIEVAL_TYPE` axes still
> resolve (`val_link`+`plan_exec` → `cyanchor`, `hybrid` → `+vector`).

Method writeup: [docs/multi_agent_graphrag.md](docs/multi_agent_graphrag.md) ·
results: [report/CypherBench/flight_accident.md](report/CypherBench/flight_accident.md).

---

## Hybrid retrieval (vector + fuzzy)

Each value-lookup tool corresponds to one `(node_label, property)` pair (e.g. `Movie.title`, `Person.name`). Vector retrieval is available on **node** value-lookup tools while relationship-property and structural-traversal tools stay on the fuzzy code path. The hybrid pipeline is what `RETRIEVAL_TYPE=hybrid` drives; defaults preserve fuzzy behavior bit-identically.

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
| `hybrid` | Run both, fuse via `HYBRID_STRATEGY` (`cascade` default — fuzzy-first, vector fills the tail; `rrf` / `weighted` available). On the perturbed benchmark `cascade` is strictly ≥ `fuzzy` and avoids RRF's "semantic-neighbour displaces the exact match" failure — see `docs/NER_GROUNDING_RETENTION_STUDY.md`. |

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

`generated/generated_node_tools.py`, `generated/generated_rel_tools.py`, `config.py`, `agent/prompts.py`, and `generated/faiss` are intentionally NOT touched.

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
from embedding.embedding_helper import (
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

`--mode` selects the method by its canonical name (or set `METHOD` + the retrieval
switches — see [Methods](#value-linking-modes)).

**CyANCHOR** — the shipped method:

```bash
# Full pipeline: value linking → Cypher → Neo4j → answer
python ner_agent_auto.py "Who acted in The Matrix?" --mode cyanchor_fl_node_rel

# --verbose shows the intermediate steps:
#   PLAN     entity mentions decomposed from the question
#   EXECUTE  per-mention field routing, retrieved candidates, and the
#            LLM corrective-loop decisions (done / deepen / pick a field)
#   GENERATE the candidate block + the generated Cypher
python ner_agent_auto.py "How many movies were released before 2000?" \
    --mode cyanchor_fl_node_rel --verbose
```

> Canonical names encode the arms: `cyanchor_fl_node_rel` = fuzzy+lev (no embeddings),
> `cyanchor_fvl_node_rel` = fuzzy+lev+vector (needs an in-graph vector index;
> falls back gracefully if absent). Or just set `METHOD=cyanchor` + the
> `RETRIEVAL_*` switches and omit `--mode`.

**ReAct** agent — baseline (also shows its agent trace under `--verbose`):

```bash
python ner_agent_auto.py "How many movies were released before 2000?" \
    --mode react_node_rel --verbose

# Grounding step only (skip Cypher generation)
python ner_agent_auto.py "movies by Tom Hanks" --mode react_node_rel --ner-only
```

Or call from Python:

```python
from ner_agent_auto import ask_auto

result = ask_auto("What movies did Keanu Reeves star in?",
                  mode="cyanchor_fl_node_rel")   # or omit to use the config axes
print(result["cypher"])   # the generated Cypher query
print(result["result"])   # natural-language answer
print(result["context"])  # raw rows returned by Neo4j
```

---

## Testing

### Fulltext search deduplication test

`tests/test_neo4j_search.py` verifies that the fulltext search functions return **unique property values** (no duplicates), ranked by the best matching score.

```bash
python -m tests.test_neo4j_search
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

### Per-graph evaluation harness (CypherBench / Mind-the-Query / ZOGRASCOPE)

The repo ships a **per-graph** evaluation harness that runs the live agent over one or more `(dataset, graph)` pairs, each pointing at its own Neo4j container, and reports bucketed metrics across all of them. The harness is a Python module + three top-level scripts — there is no CLI; you edit `eval_config.py` and re-run.

**Pipeline:**

```
eval_config.py            ← edit: connections, test paths, which pairs to run
       │
       ▼
scripts/setup_and_archive.py        (no args — reads EVAL_PAIRS)
       │   • For each pair in EVAL_PAIRS, runs setup_project.py against
       │     that graph's Neo4j
       │   • Archives schema_data/, generated/, agent/prompts.py,
       │     FAISS index, EMBEDDABLE_PROPERTIES → setup_artifacts/<dataset>__<graph>/
       │   • REFUSES to archive if the live tools don't match the graph
       ▼
verify_setup.py                     (pre-flight — run before every eval batch)
       │   • For each pair, connects to its graph and confirms the
       │     archive's node tools search labels that actually have nodes
       │   • Green/red table; red = contaminated archive, do not evaluate
       ▼
eval_run.py
       │   • For each pair in EVAL_PAIRS:
       │       1. swap_in archived artifacts into the live repo
       │       2. graph-identity guard — skip the pair if the live tools
       │          don't match the graph (same check as verify_setup.py)
       │       3. spawn `python -m eval._worker <dataset> <graph> ...`
       │          with EVAL_NEO4J_* env vars pointing at that container
       │       4. write logs/eval/<dataset>__<graph>.records.jsonl
       │                   logs/eval/<dataset>__<graph>.summary.json
       ▼
eval_aggregate.py
           • Re-aggregates every records.jsonl on disk by difficulty
             bucket and prints one table per dataset
```

#### 1 — Configure `eval_config.py`

The repo ships an `eval_config_example.py`. Copy it to `eval_config.py` (gitignored — credentials live here, not in `.env`) and fill in:

```python
# Per-(dataset, graph) Neo4j connection registry.  Each graph runs in
# its own Docker container with its own bolt port.
GRAPH_CONNS: dict[tuple[str, str], GraphConn] = {
    ("cypherbench",  "movie"):    GraphConn(uri="bolt://localhost:7687", user="neo4j", password="..."),
    ("cypherbench",  "nba"):      GraphConn(uri="bolt://localhost:7688", user="neo4j", password="..."),
    ("mindthequery", "bloom50"):  GraphConn(uri="bolt://localhost:7689", user="neo4j", password="..."),
    ("zograscope",   "pole"):     GraphConn(uri="bolt://localhost:7690", user="neo4j", password="..."),
}

# Test-set paths (one combined file per dataset; the worker filters by graph).
CYPHERBENCH_PATH  = "/path/to/cypherbench/test.json"
MINDTHEQUERY_PATH = "/path/to/mindthequery/Train_Test_Splits/Manual"
ZOGRASCOPE_PATH   = "/path/to/zograscope/data/zograscope_test_v1.csv"

# Which pairs to evaluate on the next `python eval_run.py`.
EVAL_PAIRS: list[tuple[str, str]] = [
    ("cypherbench", "movie"),
    ("cypherbench", "nba"),
]

LIMIT:   int | None = None      # cap examples per pair (None = all)
VERBOSE: bool       = False     # per-example log lines
SHARDS:  int        = 4         # intra-graph parallelism (1 = single process)
OUT_DIR              = "logs/eval"
REPORT_DIR           = "report" # where gen_*_report.py write report/<dataset>/<graph>.md + _summary.md
SETUP_ARTIFACTS_ROOT = "setup_artifacts"
```

> **`SHARDS`** splits each graph's examples into N stride-shards run as N
> parallel worker processes against the same container, merged afterwards
> (wall-clock ≈ 1/N). Graphs still run **sequentially** — a single shared live
> artifact tree is swapped per graph, so only the examples *within* a graph
> parallelise. `SHARDS=1` is the original single-process behaviour (identical
> coverage). This supersedes the old movie-only `_run_sharded.py` script.

#### 2 — Set up + archive each graph (one-time per graph)

`setup_and_archive.py` takes **no arguments** — it reads `eval_config.EVAL_PAIRS` as the single source of truth and sets up + archives every pair listed there. To set up only a subset, shrink `EVAL_PAIRS` first.

```bash
python scripts/setup_and_archive.py
```

For each pair in `EVAL_PAIRS` the script:

1. Wipes any live-state artifacts left by a previous run (so stale data can't be bundled into the new archive).
2. Looks up the pair's `eval_config.GraphConn`.
3. Drops every vector index and nulls every embedding property on that pair's live database, so setup re-embeds against the current `vector_config` identity.
4. Subprocess-invokes `setup_project.py --yes` with the connection injected via `NEO4J_*` env vars and the pair's `database` passed on `--database`.
5. Archives the per-graph outputs under `setup_artifacts/<dataset>__<graph>/` (always overwriting any existing archive), then runs a manifest round-trip check so a buggy archive is caught — and deleted — immediately.

The run is **fail-fast**: if any pair fails (subprocess non-zero, archive/round-trip failure, Neo4j reset failure, …) the whole run aborts. On abort the script prints a per-pair summary plus a copy-pasteable `EVAL_PAIRS` retry block listing the failed pair and every pair skipped by the abort, so you can resume from where it broke. The working tree is always left clean (post-pair wipe runs in `finally`).

> The legacy `python scripts/setup_and_archive.py <dataset> <graph>` positional-args form is intentionally rejected with a non-zero exit — drive everything through `EVAL_PAIRS`.

#### 2½ — Verify each archive matches its graph (pre-flight)

```bash
python verify_setup.py          # checks every pair in EVAL_PAIRS
python verify_setup.py --all    # checks every pair in GRAPH_CONNS
python verify_setup.py --live   # checks the live tree vs .current_setup
```

**Why this matters for multi-graph runs.** The harness keeps a *single live copy* of each graph's artifacts (node tools, schema, prompts, FAISS / FCAV indexes) and swaps the right archive in per pair. If the wrong artifacts are live — an interrupted swap, a failed tool regen, a hand recovery — value linking runs against the wrong tools and **silently scores at the no-link floor with no error**. (Tell-tale sign: ReAct / CyANCHOR collapse to ≈ the `no_val_link` score while **FCAV still works**, because FCAV uses the schema + prompts, which stay correct, not the per-graph tools.)

`verify_setup.py` connects to each graph and confirms the archive's node tools search labels that **actually have nodes** there — a count check, not just `db.labels()`, because Neo4j keeps emptied labels in the registry as ghosts. Green = safe to run; red names the offending labels and the fix. Full procedure for collaborators: [docs/RUNNING_EXPERIMENTS.md](docs/RUNNING_EXPERIMENTS.md).

> Reaching the graphs needs the corporate VPN **disconnected**; an `UNREACH` row is a connection issue, not a contaminated archive.

#### 3 — Run the evaluation

```bash
python eval_run.py
```

For each pair in `EVAL_PAIRS` the driver:

1. Calls `eval.artifact_swap.swap_in(dataset, graph)` to copy the archived setup outputs into the live repo locations (so `agent/`, `generated/`, `schema_data/`, FAISS index all match that graph).
2. **Graph-identity guard** — connects to the pair's graph and confirms the live node tools search labels that have nodes there. A mismatch (contaminated archive) is **skipped with a loud reason**, not silently mis-scored. This is the same check as `verify_setup.py`; bypass with `EVAL_SKIP_GRAPH_GUARD=1` only if you know what you're doing.
3. Looks up the `GraphConn`, builds the worker env (`EVAL_NEO4J_URI` / `_USER` / `_PASSWORD` / `_DATABASE`).
4. Spawns `python -m eval._worker <dataset> <graph> <test_path> <records_out> <summary_out>` as a fresh subprocess so each pair gets a clean Python interpreter.
5. Writes:
   - `logs/eval/<dataset>__<graph>.records.jsonl` — one line per example (gold cypher, predicted cypher, EA / EM verdict, normalised result-sets, error info)
   - `logs/eval/<dataset>__<graph>.summary.json` — aggregate summary for that pair

A failure on one pair (missing archive, worker crash, etc.) is logged and skipped — the rest of `EVAL_PAIRS` still runs. The driver only exits non-zero if **every** pair failed.

#### 4 — Print the bucketed table

```bash
python eval_aggregate.py
```

Scans `logs/eval/` for every `*.summary.json`, groups by dataset (parsed from the `<dataset>__<graph>` filename prefix), re-aggregates the underlying `.records.jsonl` files via `eval.difficulty.aggregate_by_difficulty`, and prints one bucketed table per dataset (rows: `all` / `easy` / `medium` / `hard` / `extra`) with a footer naming the graphs that contributed. Records persist on disk across runs, so partial re-evals just overwrite the affected pair's two files and leave everything else untouched.

#### Metrics & normalisation

Each per-dataset metric module under `eval/` computes the headline numbers; for CypherBench-style datasets the harness reports **Execution Accuracy (EA, multiset)** and **Execution Match (EM, ordered)**. Result-set comparison is delegated to `eval/cypher_eval_normalize.py:normalize_result_set`, which structurally expands `Node` / `Relationship` / `Path` cells (label-set + property-set, **never** `element_id`), rounds floats to a configurable epsilon (default `1e-6`), and sorts `collect()`-style list cells unless the gold query has a top-level `ORDER BY`. EA stays multiset and EM stays ordered in both modes — the `ORDER BY` heuristic only governs `sort_collections` inside `collect()` cells, so the EA−EM gap remains a meaningful "fraction of items where ordering matters" signal.

Offline unit tests for the normaliser:

```bash
python -m pytest tests/test_cypher_eval_normalize.py
```

#### Typical workflows

**Add one new graph and re-run the full table:**

```bash
# 1. Add a row to GRAPH_CONNS in eval_config.py
# 2. Add ("cypherbench", "fictional_university") to EVAL_PAIRS
# 3. Set up + archive every pair in EVAL_PAIRS:
python scripts/setup_and_archive.py
# 4. Pre-flight, then run + aggregate:
python verify_setup.py
python eval_run.py
python eval_aggregate.py
```

**Re-run just one pair after a code change** (existing records for other pairs are reused):

```bash
# Set EVAL_PAIRS = [("cypherbench", "movie")] in eval_config.py
python eval_run.py            # overwrites only that pair's two files
python eval_aggregate.py      # table still includes every other pair on disk
```

**Smoke-test on 20 examples per pair:**

```python
# In eval_config.py
LIMIT   = 20
VERBOSE = True
```

```bash
python eval_run.py
```

---

## Re-running after a schema change

If your Neo4j database schema changes (new labels, properties, or relationships added), just re-run the setup script:

```bash
python setup_project.py
```

Or run only the affected steps manually:

```bash
python -m schema.gen_schema_csv                 # re-export schema CSVs
python -m schema.gen_schema_meta                # re-infer schema metadata (LLM)
python -m tools.gen_tools                       # regenerate @tool functions
python -m schema.gen_system_prompt              # regenerate agent/prompts.py
python ner_agent_auto.py --rebuild "test"       # rebuild the FAISS index
```

> **Hand-edited `schema_data/schema_meta.json`?** (e.g. to fix a wrong
> `id_property` or a topic.) It is **re-inferred by the LLM and overwritten** by
> both `schema.gen_schema_meta` and a full `setup_project.py`. After editing it
> by hand, re-run **only the downstream steps that consume it** —
> `tools.gen_tools` → `schema.gen_system_prompt` → FAISS rebuild — and do **not**
> re-run `schema.gen_schema_meta` or the full `setup_project.py`, or your edits
> are clobbered.

---

## Advanced: manual step-by-step setup

If you prefer to run each step individually or need to debug a specific stage:

| # | Command | What it does |
|---|---|---|
| 1 | `python -m neo4j_lib.neo4j_diag` | Verify connection and list node labels |
| 2 | `python -m schema.gen_schema_csv --print-summary` | Export schema to CSV and print a summary |
| 3 | `python -m schema.gen_schema_meta --verbose` | Infer `id_property`, topics, descriptions via LLM |
| 4 | *(fulltext indexes — handled by setup_project.py)* | Create all Neo4j fulltext indexes |
| 5 | `python -m tools.gen_tools` | Generate `@tool` functions from the live schema |
| 6 | `python -m schema.gen_system_prompt` | Generate `agent/prompts.py` from scratch |
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
| `config.py` | **User-managed** runtime settings — LLM configs per stage, the `METHOD` axis + CyANCHOR's `RETRIEVAL_FUZZY`/`RETRIEVAL_VECTOR`/`RETRIEVAL_LEVENSHTEIN`/`TOOL_TYPE`, + sampling/validation knobs. **Not** auto-generated; safe to edit by hand |
| `vector_config.py` | Retrieval mode (`fuzzy`/`vector`/`hybrid`), embedding backend + dim, `EMBEDDABLE_PROPERTIES` |
| `paths.py` | Centralized filesystem-layout constants for every generated artifact |
| `ner_agent_auto.py` | Value-linking → Cypher pipeline (main entrypoint); `ask_auto` dispatches to the grounding mode and runs `GraphCypherQAChain` |
| `plan_exec.py` | **CyANCHOR** grounder (the shipped method, `METHOD=cyanchor`): decompose → route → retrieve (3 toggleable arms: fuzzy / Levenshtein / vector) with the LLM corrective loop |
| `fcav.py` | `fcav` mode — retrieve-then-generate RAG baseline over a self-built value index (built by `setup_fcav.py`) |
| `agent/prompts.py` | **Auto-generated** system prompts (`NER_SP`, `TEXT2CYPHER_SP`, `QA_SP`, `PROMPT_ALIGNER_SP`) + schema constants |
| `schema/gen_schema_csv.py` | Export full schema to `schema_data/schema_nodes.csv` + `schema_relations.csv` |
| `schema/gen_schema_meta.py` | LLM-infer `id_property`, topics, descriptions → `schema_data/schema_meta.json` |
| `schema/gen_system_prompt.py` | Generate `agent/prompts.py` from the live schema |
| `tools/gen_tools.py` | Generate `@tool` functions from the live schema + `schema_meta.json` |
| `tools/tool_search.py` | FAISS-based tool search engine |
| `neo4j_lib/neo4j_search.py` | Fulltext index management + `search_tool()` / `search_rel_tool()` |
| `neo4j_lib/neo4j_diag.py` | Connection diagnostics (run with `python -m neo4j_lib.neo4j_diag`) |
| `embedding/embedding_helper.py` | Embeddable-property discovery, backfill, vector-index creation |
| `generated/generated_node_tools.py` | **Auto-generated** node property search tools |
| `generated/generated_rel_tools.py` | **Auto-generated** relationship search tools |
| `generated/faiss/` | **Auto-generated** FAISS tool-selection index (gitignored) |
| `schema_data/schema_nodes.csv` | **Auto-generated** node schema export |
| `schema_data/schema_relations.csv` | **Auto-generated** relationship schema export |
| `schema_data/schema_meta.json` | **Auto-generated** LLM-inferred schema metadata |
| `tests/test_neo4j_search.py` | Tests for fulltext search deduplication + score ordering |

---

## Troubleshooting

**Connection refused / DNS error**  
→ Check `NEO4J_URI` in `.env`. For local Neo4j use `bolt://localhost:7687`. For AuraDB use `neo4j+s://`.

**`No module named 'generated_node_tools'`**  
→ Run `python setup_project.py` or `python -m tools.gen_tools` first.

**`Missing required env var: OPENAI_API_KEY`**  
→ Make sure `.env` exists in the project root and all required keys are set.

**Fulltext index search returns no results**  
→ Check that indexes are `ONLINE` in the Neo4j Browser.  
→ Re-run `python setup_project.py` to rebuild the fulltext indexes.

**FAISS index stale after schema change**  
→ Re-run `python setup_project.py` or `python ner_agent_auto.py --rebuild "test"`.

**Mind-the-Query / ZOGRASCOPE containers not running after VM reboot**  
→ The systemd services (`mindthequery.service`, `zograscope.service`) fail on boot when stopped containers from the previous session still exist. Restart them manually:
```bash
gcloud compute ssh cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923 \
  --command="sudo systemctl start mindthequery.service zograscope.service"
```
→ The start scripts have been patched with `docker rm -f` before each `docker run`, so this should not recur.

**VM external IP changed after reboot**  
→ GCP assigns ephemeral IPs; the IP may change each time the VM stops and starts. Check the current IP with:
```bash
gcloud compute instances describe cypherbench-neo4j --zone=us-central1-a --project=research-infra-494923 --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```
→ Update `docs/GRAPHS.md` and any local `eval_config.py` connections to use the new IP.

**`SyntaxError` in `generated/generated_rel_tools.py`**  
→ Re-run `python -m tools.gen_tools` — caused by a Neo4j relType formatting artifact, now fixed.
