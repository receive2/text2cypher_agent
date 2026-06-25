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

> Out of the box this runs **CyANCHOR** (the shipped grounder — `METHOD=cyanchor`
> is the default). To run a baseline instead, set `METHOD=no_val_link` (no
> grounding) / `fcav` / `react` / `graphrag`.

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

> **Only for the `fcav` baseline:** after `setup_and_archive.py`, also run
> `python setup_fcav.py` once — it builds the FCAV value index (per graph in
> `eval_config.EVAL_PAIRS`) that the retrieve-then-generate baseline needs.
> The other four methods (`no_val_link` / `react` / `graphrag` / `cyanchor`)
> need no extra step.

Each run writes a canonical per-run directory
`OUT_DIR/<dataset>__<graph>__<method>/` (`records.jsonl` + `summary.json`) — the
method is part of the path, so a five-method sweep into one `OUT_DIR` keeps each
method's records separate (see `eval_paths.py`, the single source of truth for
this layout). `eval_aggregate.py` reads those dirs and prints, per
`(dataset, method)`, an **EA / EM / PSJS** table bucketed by **difficulty**
(easy/medium/hard) and — for the perturbed `*_augmented` sets — by **perturbation
strategy** (casing/typo/partial/abbrev/alias). It also writes a self-describing,
timestamped `report_<timestamp>.md` into `OUT_DIR`.

### Experiment knobs

The method is selected by `METHOD` in `config.py` (env-overridable), plus
CyANCHOR's retrieval/tool sub-axes:

| axis | env var | values |
|---|---|---|
| method | `METHOD` | `no_val_link` · `fcav` · `react` · `graphrag` · `cyanchor` |
| CyANCHOR arms | `RETRIEVAL_FUZZY` / `RETRIEVAL_VECTOR` / `RETRIEVAL_LEVENSHTEIN` | `0`/`1` each (≥1 on; defaults `1`/`0`/`1`) |
| tool scope | `TOOL_TYPE` | `node` · `node_rel` (react / cyanchor) |
| examples per pair | `LIMIT` in `eval_config.py` | int · `None` (all) |
| intra-graph parallelism | `SHARDS` in `eval_config.py` | int (default `4`; `1` = single process) |
| CyANCHOR self-correction | `CYPHER_SEMANTIC_REPAIR` / `CYPHER_REPAIR_MAX_ROUNDS` / `CYPHER_EMPTY_IS_WRONG` | defaults `1` / `4` / `1` |
| report location | `REPORT_DIR` in `eval_config.py` | path (default `report`) |

`SHARDS` splits each graph's examples into N stride-shards run as N parallel
worker processes against the same container, then merges them — wall-clock ≈
1/N. Graphs still run **sequentially** (one shared live artifact tree is swapped
per graph), so only the examples *within* a graph parallelise. `SHARDS=1`
reproduces the original single-process coverage exactly. Lower it if you hit LLM
rate limits.

`cyanchor` is **CyANCHOR**, the shipped method; `no_val_link` / `fcav` / `react` /
`graphrag` are baselines. CyANCHOR grounds the mentions, then the Cypher LLM
**self-corrects**: a DB error → CoT error-repair; a wrong-but-executable result
(LLM evaluator: incorrect/illogical/incomplete/empty) → grounding-aware
regeneration (keeps the candidates + adds feedback), up to `CYPHER_REPAIR_MAX_ROUNDS`,
keeping the first accepted (else first executable) attempt. See
[report/CypherBench/flight_accident.md](report/CypherBench/flight_accident.md)
for the ablation and the README "Methods" table for details.

Example — CyANCHOR `fuzzy+lev` (no embeddings), node + relation tools:

```bash
METHOD=cyanchor RETRIEVAL_VECTOR=0 TOOL_TYPE=node_rel python eval_run.py
```

Example — the Multi-Agent GraphRAG baseline:

```bash
METHOD=graphrag python eval_run.py
```

> Back-compat: the legacy `VAL_LINK_MODE` / `AGENT_TYPE` / `RETRIEVAL_TYPE` still resolve.

Re-running is incremental: each `(dataset, graph, method)` overwrites only its own
run directory under `OUT_DIR`; `eval_aggregate.py` re-reads everything on disk, so
a partial re-run still prints the full table.

---

## Where to go next

- **Full reference** (all flags, backends, troubleshooting): [README.md](README.md)
- **Benchmark + method write-ups**: [docs/INDEX.md](docs/INDEX.md)
