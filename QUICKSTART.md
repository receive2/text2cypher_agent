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

> **If you hand-edit the inferred `schema_data/schema_meta.json`** (e.g. to fix a
> wrong `id_property`), re-run only the downstream steps that consume it —
> `python -m tools.gen_tools` → `python -m schema.gen_system_prompt` →
> `python ner_agent_auto.py --rebuild "test"` — **not** the full `setup_project.py`
> (it re-infers and overwrites your edits). See the README for detail.

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

Then, four steps:

```bash
python scripts/setup_and_archive.py   # one-time per graph: setup + archive artifacts
python verify_setup.py                # pre-flight: confirm each archive matches its graph
python eval_run.py                    # run the agent over every pair in EVAL_PAIRS
python eval_aggregate.py              # print per-difficulty + per-strategy tables
```

> **Always run `verify_setup.py` before evaluating, especially across many
> graphs.** The harness keeps a single live copy of each graph's artifacts and
> swaps the right one in per pair; if the wrong artifacts are live, value linking
> silently scores at the no-link floor with no error. `verify_setup.py` connects
> to each graph and confirms the archive's tools actually match it (green/red
> table). `eval_run.py` runs the same check automatically and skips any
> contaminated pair, but the pre-flight catches problems before you spend run
> time. See [docs/RUNNING_EXPERIMENTS.md](docs/RUNNING_EXPERIMENTS.md).

`eval_aggregate.py` prints, per dataset, an **EA / EM / PSJS** table bucketed by
**difficulty** (easy/medium/hard) and — for the perturbed `*_augmented` sets —
by **perturbation strategy** (casing/typo/partial/abbrev/alias). It also writes a
self-describing, timestamped `report_<timestamp>.md` into `OUT_DIR` (the run's
mode + config in the header).

### Experiment knobs

Value linking is selected by four orthogonal axes in `config.py` (each
env-overridable):

| axis | env var | values |
|---|---|---|
| value-link mode | `VAL_LINK_MODE` | `no_val_link` · `fcav` · `graphrag` · `val_link` |
| grounder | `AGENT_TYPE` | `react` · `plan_exec` (when `val_link`) |
| retrieval | `RETRIEVAL_TYPE` | `fuzzy` · `hybrid` (when `val_link`) |
| tool scope | `TOOL_TYPE` | `node` · `node_rel` (when `val_link`) |
| examples per pair | `LIMIT` in `eval_config.py` | int · `None` (all) |

`graphrag` is the Multi-Agent GraphRAG baseline (no pre-grounding; generate →
execute → evaluate → repair loop). See
[docs/multi_agent_graphrag.md](docs/multi_agent_graphrag.md) and the README
"Value-linking modes" table for all modes.

Example — plan-and-execute, hybrid retrieval, node+relation tools:

```bash
VAL_LINK_MODE=val_link AGENT_TYPE=plan_exec RETRIEVAL_TYPE=hybrid TOOL_TYPE=node_rel python eval_run.py
```

Example — the Multi-Agent GraphRAG baseline:

```bash
VAL_LINK_MODE=graphrag python eval_run.py
```

Re-running is incremental: each pair overwrites only its own two files in
`OUT_DIR`; `eval_aggregate.py` re-reads everything on disk, so a partial re-run
still prints the full table.

---

## Where to go next

- **Full reference** (all flags, backends, troubleshooting): [README.md](README.md)
- **Benchmark + method write-ups**: [docs/INDEX.md](docs/INDEX.md)
