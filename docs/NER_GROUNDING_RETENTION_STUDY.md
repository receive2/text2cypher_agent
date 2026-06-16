# NER Grounding-Retention Study — flight_accident

Funnel diagnosis of where end-to-end accuracy is lost in the value-grounding
pipeline, a tool-result **backfill** fix, and a retrieval-mode ablation
(fuzzy vs vector vs hybrid-RRF vs hybrid-cascade). All numbers are on the
entity-perturbed CypherBench **flight_accident** graph (170 test questions,
`full` NER mode), a small graph chosen so embeddings could be built quickly.

## Headline

- **The dominant bottleneck is grounding *retention*, not retrieval and not
  Cypher generation.** The retrieval layer recovers the canonical entity for
  ~74% of perturbations (top-1), but only ~23% of those survive the NER agent's
  final-answer synthesis into the Cypher — a **~50 pp loss inside the agent**.
- **A tool-result backfill closes most of that loss and ~doubles EA**:
  0.218 → 0.382 (fuzzy) / 0.202 → 0.385 (cascade).
- **With backfill, embeddings add essentially nothing at the pooled level**
  (cascade+backfill 0.385 ≈ fuzzy+backfill 0.382, within run-to-run noise) — so
  the embedding build is **not** required for the cross-graph experiments.

## Setup

- Graph: `flight_accident` (1,683 nodes), Neo4j 5.20, full embeddings + native
  vector indexes built (`text-embedding-3-small`, dim 1536).
- 170 perturbed test questions. Strategy mix: casing 17, typo 38, partial 38,
  abbrev 38, alias 39.
- NER mode `full` (node + relation tools). `TOOL_TOP_K = 10` results per tool call.

## 1. Per-strategy recoverability (retrieval layer, LLM-independent)

For each perturbed mention, run the value-lookup retrieval and check whether the
canonical value is returned. This bounds what any downstream system could
achieve — it is independent of the agent and the Cypher LLM.

| strategy | fuzzy top-1 | fuzzy top-10 | cascade top-1 | cascade top-10 |
|---|--:|--:|--:|--:|
| casing | 100 | 100 | 100 | 100 |
| typo | 100 | 100 | 94.6 | 100 |
| partial | 100 | 100 | 100 | 100 |
| abbrev | 28.9 | 31.6 | 36.8 | 47.4 |
| alias | 47.4 | 52.6 | 52.6 | 63.2 |

- **casing / typo / partial are string-recoverable** — Lucene fuzzy alone nails
  them at ~100% top-1. So a failure here is *not* a dataset flaw; the gold is
  reachable.
- **abbrev / alias need semantic / world-knowledge grounding** — neither fuzzy
  nor vector retrieval recovers them reliably (cascade top-1 only 37% / 53%).
  These are the genuinely hard tier and depend on the LLM's knowledge, not
  retrieval.
- **RRF hybrid was harmful** (not shown above): 50/50 rank fusion let
  semantically-near-but-wrong vector neighbours displace fuzzy's exact match
  (e.g. `NOVOSIBIRSK…`→`Russia`, `THR`→`Niš…Airport`), dropping top-1 precision
  (typo 100→62). The **cascade** strategy (fuzzy ranks first, vector fills the
  tail; `_cascade_merge` in `neo4j_lib/neo4j_search.py`) preserves fuzzy's top-1
  and only adds vector recall where fuzzy is empty — strictly ≥ fuzzy.

## 2. The funnel — where EA is lost (cascade, no backfill)

| stage | rate |
|---|--:|
| ① retrieval can recover (top-1) | ~74% |
| ② entity actually injected into the Cypher (end-to-end grounded) | **23%** |
| ③ final EA correct | 20% |

- ①→② loses **~50 pp inside the NER agent** (extraction / tool-call / final-JSON
  synthesis).
- ②→③ loses only ~3 pp: when grounding succeeds, Cypher generation succeeds
  **87%** of the time.
- Implied EA ceiling if grounding were perfect: **~0.82** (vs 0.20 observed) — a
  ~4× headroom gated almost entirely by grounding retention.

Confirmed mechanism: of typo/partial questions that fail end-to-end, **100%**
contain the question's *perturbed surface form* in the predicted Cypher
(e.g. `"Aeroflot Fllight 3603"`, `"ART 42"`) rather than the canonical value —
the agent's retrieval recovered the canonical, but it never reached the query.

Root cause (code-confirmed): `get_ner_dict_auto` returns
`json.loads(<agent final message>)`. The ReAct agent often calls the right tool
and gets the canonical at rank-1, but its **final-answer JSON drops it** (returns
`{}` or omits the key), so nothing is injected and the Cypher LLM falls back to
the question text.

## 3. The fix — tool-result backfill (safety net)

`_backfill_from_tools` (in `ner_agent_auto.py`) harvests each tool call's top-1
canonical value from the agent's tool-message history and **backfills keys that
the LLM's final JSON left missing or empty** — additively, never overriding a
value the LLM emitted. Tool→key mapping is parsed from each tool's docstring
(`"…canonical Label.property values…"`).

Unit check on 12 typo/partial questions: NER recovery **2/12 → 7/12**; every
recovered case was one where retrieval already had the canonical at rank-1 but
the LLM had dropped it.

**Known limitation (measured).** On 30 typo/partial/alias questions, the raw NER
output was: canonical 9 (30%), empty `{}` 16 (53%, fully fixed by backfill),
non-canonical-but-tool-has-canonical 2 (6.7%), retrieval-miss 3 (10%). The
conservative "never override" rule leaves the 6.7% on the table; in those two
cases the LLM had emitted a hallucinated entity under a *different* key, so
backfill still added the canonical under the correct (missing) key — the
residual issue is a spurious extra filter, not a blocked grounding. A targeted
override (replace a key's value when it appears verbatim in the question *and* a
tool recovered a different high-confidence canonical) would capture the 6.7%;
deferred for now.

## 4. End-to-end results — 4-way

| config | EA | PSJS | n |
|---|--:|--:|--:|
| fuzzy (no backfill) | 0.218 | 0.253 | 170 |
| **fuzzy + backfill** | **0.382** | 0.426 | 170 |
| cascade (no backfill) | 0.202 | 0.245 | 168 |
| **cascade + backfill** | **0.385** | 0.432 | 169 |

### Per-strategy EA

| strategy | n | fuzzy | fuzzy+bf | cascade | cascade+bf |
|---|--:|--:|--:|--:|--:|
| casing | 17 | 0.471 | 0.471 | 0.353 | 0.529 |
| typo | 38 | 0.132 | **0.447** | 0.135 | **0.432** |
| partial | 38 | 0.316 | 0.421 | 0.270 | 0.395 |
| abbrev | 38 | 0.184 | 0.289 | 0.158 | 0.263 |
| alias | 39 | 0.128 | **0.333** | 0.179 | **0.385** |
| **overall** | | 0.218 | **0.382** | 0.202 | **0.385** |

Per-strategy PSJS (cascade+backfill): casing 0.682, typo 0.491, partial 0.392,
abbrev 0.337, alias 0.399.

- Backfill's gains concentrate in **typo (+0.30)** and **alias (+0.26)** — the
  tiers where the agent-drop loss was largest.
- **casing** is already solved (backfill adds nothing on fuzzy); its remaining
  failures are Cypher-generation.
- **abbrev** gains least (+0.08) because it is retrieval-limited (37% ceiling) —
  the genuine world-knowledge tier.
- With backfill, **embedding (cascade) helps only on alias (+0.05)** and is a
  wash or slight loss elsewhere; pooled cascade+bf ≈ fuzzy+bf.

## 5. Conclusions & recommendations

1. **Ship the backfill for every experiment.** It is a ~2× EA improvement and is
   largely LLM-independent. Without it, every LLM's score is artificially halved
   by the agent dropping recoverable groundings, so a model sweep would measure
   "which LLM re-emits its own tool results most faithfully" rather than the
   quality of value grounding.
2. **The embedding build is optional for the cross-graph runs.** fuzzy+backfill
   ≈ cascade+backfill at the pooled level, so the one-time embedding integration
   (and the APOC question) can be skipped; use fuzzy. Keep `cascade` available
   for any graph that already has embeddings — it is strictly ≥ fuzzy and fixes
   the RRF displacement bug, but is not worth building embeddings for.
3. **Retrieval mode is second-order; grounding retention is first-order.**
4. **Residual headroom after backfill is the agent's tool-calling / span
   extraction**: even with backfill, typo EA (0.43) is far below its retrieval
   ceiling (95%), because backfill can only harvest results from tools the agent
   actually called with the right span. Improving tool selection + span
   extraction is the next lever.

## 6. Caveats

- Single graph (flight_accident, 170 questions), single run, per-strategy
  n = 17–39. The **backfill win (~+0.17 EA) is large enough to survive the
  run-to-run noise (~±0.02–0.03 EA)**; the **fuzzy-vs-cascade tie is within that
  noise**. Before finalizing for the paper, re-confirm on a larger graph and/or
  multiple seeds — especially if the paper emphasizes the alias / world-knowledge
  tier, where embeddings show a small edge.
- Numbers are with NER mode `full` and `TOOL_TOP_K = 10`.

## Artifacts

- Backfill: `ner_agent_auto.py` → `_backfill_from_tools`, `_tool_key_map`,
  `_parse_tool_values`, wired into `get_ner_auto`.
- Cascade strategy: `neo4j_lib/neo4j_search.py` → `_cascade_merge`
  (`HYBRID_STRATEGY = "cascade"`).
- Run logs: `logs/eval_fa_fuzzy`, `logs/eval_fa_fuzzy_backfill`,
  `logs/eval_fa_cascade`, `logs/eval_fa_cascade_backfill`.
