# Quick Start

A 10-minute path from clone to a working agent, then to running experiments.
For full detail see [README.md](README.md); for the design/research docs see
[docs/INDEX.md](docs/INDEX.md).

---

## 0. What you need

- Python 3.10–3.12
- A Neo4j 5.18+ instance with **APOC installed** (required — the agent reads the
  schema via `apoc.meta.data()`)
- An OpenAI API key (GPT-4-class model + `text-embedding-3-small`)

## 1. Install

```bash
git clone <repo-url> && cd t2c
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install faiss-cpu          # or faiss-gpu for CUDA
```

## 2. Point it at your Neo4j + OpenAI

`.env` holds **credentials + the embedding model** only. Create it in the repo root:

```dotenv
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j

OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

> **The three pipeline LLMs are chosen in `config.py`, not in `.env`.** Each
> stage has its own freely-configurable model: `NER_LLM_CONFIG` (the ReAct
> entity-grounding agent), `CYPHER_LLM_CONFIG` (Cypher generation), and
> `QA_LLM_CONFIG` (final answer). Mix providers freely (OpenAI / Azure /
> Anthropic / any OpenAI-compatible endpoint) — see the examples at the top of
> `config.py`. (`.env`'s optional `OPENAI_MODEL` is only a fallback default for
> an OpenAI stage that leaves `model` unset.)

## 3. One-click setup

```bash
python setup_project.py
```

This introspects your graph and generates everything the agent needs (schema,
fulltext + vector indexes, per-property lookup tools, system prompts, FAISS tool
index). Re-run it after the graph schema changes. Useful flags:
`--skip-embeddings` (fuzzy-only, no vector index), `--yes` (non-interactive),
`--rediscover` (re-pick embeddable properties).

## 4. Ask a question (does it work?)

```bash
python ner_agent_auto.py "Who directed The Matrix?" --verbose
```

You should see: entities resolved → Cypher generated → rows → a natural-language
answer. That's the whole pipeline.

---

## 5. Run experiments (the evaluation harness)

The harness runs the agent over one or more `(dataset, graph)` pairs and reports
bucketed metrics. It is driven entirely by **`eval_config.py`** — no CLI.

```bash
cp eval_config_example.py eval_config.py     # gitignored; credentials live here
```

Edit `eval_config.py`:

```python
GRAPH_CONNS = {                              # one Neo4j per graph
    ("cypherbench", "movie"): GraphConn(uri="bolt://localhost:7687", user="neo4j", password="..."),
}
EVAL_PAIRS = [("cypherbench", "movie")]      # which pairs to run next
CYPHERBENCH_PATH = "/path/to/cypherbench/test.json"
LIMIT   = 20                                 # cap per pair while smoke-testing; None = all
OUT_DIR = "logs/eval"
```

Then, three steps:

```bash
python scripts/setup_and_archive.py   # one-time per graph: setup + archive artifacts
python eval_run.py                    # run the agent over every pair in EVAL_PAIRS
python eval_aggregate.py              # print per-difficulty + per-strategy tables
```

`eval_aggregate.py` prints, per dataset, an **EA / EM / PSJS** table bucketed by
**difficulty** (easy/medium/hard) and — for the perturbed `*_augmented` sets —
by **perturbation strategy** (casing/typo/partial/abbrev/alias).

### Experiment knobs

| what | where | values |
|---|---|---|
| NER mode | `NER_MODE` env var | `full` (node+relation tools) · `node_only` · `no_ner` |
| retrieval mode | `TOOL_RETRIEVAL_MODE` in `vector_config.py` | `fuzzy` (default) · `vector` · `hybrid` |
| hybrid fusion | `HYBRID_STRATEGY` in `vector_config.py` | `cascade` (default) · `rrf` · `weighted` |
| examples per pair | `LIMIT` in `eval_config.py` | int · `None` (all) |

Example — run `full` mode in hybrid retrieval:

```bash
NER_MODE=full python eval_run.py
```

Re-running is incremental: each pair overwrites only its own two files in
`OUT_DIR`; `eval_aggregate.py` re-reads everything on disk, so a partial re-run
still prints the full table.

---

## Where to go next

- **Full reference** (all flags, backends, troubleshooting): [README.md](README.md)
- **Benchmark + method write-ups**: [docs/INDEX.md](docs/INDEX.md)
