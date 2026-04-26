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
| Neo4j | 4.4+ (fulltext index support required) |
| OpenAI API key | GPT-4 class model recommended |

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
OPENAI_EMBEDDING_MODEL=text-embedding-ada-002

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

That's it. The script runs all 7 setup steps automatically and prints the status of each one:

```
══════════════════ Text-to-Cypher Project Setup ══════════════════

──────────────────────────────────────────────────────────────────
  Step 1 / 7 — Checking environment variables
──────────────────────────────────────────────────────────────────
  ✓  NEO4J_URI = bolt://...
  ✓  NEO4J_DATABASE = 'movies'
  ✓  LLM credentials found (OpenAI / Azure OpenAI)

──────────────────────────────────────────────────────────────────
  Step 2 / 7 — Testing Neo4j connection
──────────────────────────────────────────────────────────────────
  ✓  Connected to database 'movies'
  ✓  Node labels found: ['Movie', 'Person']

  ... (steps 3–7) ...

══════════════════════ Setup Complete ════════════════════════════

  Everything is ready.  Try a query:

    python ner_agent_auto.py "Your question here" --verbose
```

**What each step does:**

| Step | Script called | Output |
|---|---|---|
| 1 | *(env check)* | Validates all required `.env` vars |
| 2 | *(Neo4j driver)* | Confirms connection + lists node labels |
| 3 | `gen_schema_csv` | `schema_nodes.csv`, `schema_relations.csv` |
| 4 | `neo4j_search` | Creates all fulltext indexes in Neo4j |
| 5 | `gen_tools` | `generated_node_tools.py`, `generated_rel_tools.py` |
| 6 | `gen_system_prompt` | Fresh `config.py` (system prompts + schema constants) |
| 7 | `ner_agent_auto` | `faiss_tools_auto/` vector index |

**Optional flags:**

```bash
python setup_project.py --database my_db    # target a specific database
python setup_project.py --skip-faiss        # skip step 7 (no OpenAI key yet)
python setup_project.py --verbose           # show full tracebacks on errors
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

## Re-running after a schema change

If your Neo4j database schema changes (new labels, properties, or relationships added), just re-run the setup script:

```bash
python setup_project.py
```

Or run only the affected steps manually:

```bash
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
| 3 | `python neo4j_search.py` | Create all Neo4j fulltext indexes |
| 4 | `python gen_tools.py` | Generate `@tool` functions from the live schema |
| 5 | `python gen_system_prompt.py` | Generate `config.py` from scratch |
| 6 | `python ner_agent_auto.py --rebuild "test"` | Build the FAISS tool-selection index |

> **Tip:** Verify fulltext indexes in the Neo4j Browser with  
> `SHOW FULLTEXT INDEXES YIELD name, state`  
> All states should be `ONLINE` before running queries.

---

## Project file overview

| File | Purpose |
|---|---|
| `.env` | Credentials — **never commit this file** |
| `requirements.txt` | Python dependencies |
| `setup_project.py` | **One-click setup** — runs all 7 setup steps automatically |
| `config.py` | **Auto-generated** system prompts + schema constants |
| `neo4j_search.py` | Fulltext index management + `search_tool()` / `search_rel_tool()` |
| `gen_schema_csv.py` | Export full schema to `schema_nodes.csv` + `schema_relations.csv` |
| `gen_tools.py` | Generate `@tool` functions from the live schema |
| `generated_node_tools.py` | **Auto-generated** node property search tools |
| `generated_rel_tools.py` | **Auto-generated** relationship search tools |
| `gen_system_prompt.py` | Generate complete `config.py` from the live schema |
| `tool_search.py` | FAISS-based tool search engine |
| `ner_agent.py` | NER agent (fixed tool list — for reference) |
| `ner_agent_auto.py` | NER agent with automatic FAISS tool selection |
| `faiss_tools_auto/` | **Auto-generated** FAISS vector index (gitignore this) |
| `schema_nodes.csv` | **Auto-generated** node schema export |
| `schema_relations.csv` | **Auto-generated** relationship schema export |

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
