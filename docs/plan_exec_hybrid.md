# Plan&Exec Hybrid (Node + Rel) — Method

This is the strongest value-linking grounder in the repo. It turns a perturbed
natural-language question (e.g. *"How many TWA accidents departed from JFK?"*,
where "TWA" is an alias and "JFK" is partial) into the **canonical database
values** the Cypher generator needs, then writes and runs the Cypher.

It is a **plan-and-execute** grounder (not a free-form ReAct agent): the control
flow is fixed, and the LLM is used at three well-scoped points — decompose the
question, judge/steer retrieval, and generate the Cypher. "Hybrid" = retrieval
unions BM25 fuzzy with the in-graph vector index. "Node + Rel" = both node and
relation tools are in scope.

---

## How to select it

Four orthogonal config axes (each env-overridable) in [`config.py`](../config.py):

```
VAL_LINK_MODE  = val_link
AGENT_TYPE     = plan_exec
RETRIEVAL_TYPE = hybrid
TOOL_TYPE      = node_rel
```

```bash
VAL_LINK_MODE=val_link AGENT_TYPE=plan_exec RETRIEVAL_TYPE=hybrid TOOL_TYPE=node_rel python eval_run.py
```

The corrective loop (below) is **on by default** (`PLAN_EXEC_ESCALATE=1`) and is
considered part of the method, not a toggle.

---

## Pipeline overview

```
question
   │
   ▼  ① PLAN          (1 LLM call)
   │   decompose into entity mentions: {mention, kind(node|relation), descriptor}
   ▼  ② EXECUTE       (per mention; no agent loop, deterministic control)
   │   a. route descriptor → top-2 fields via the tool FAISS index
   │   b. initial hybrid retrieval: 10 fuzzy ∪ 5 vector per field
   │   c. corrective loop (≤3 rounds): an LLM judge returns
   │        done | value (deepen) | <Label.property> (add a field it picks)
   ▼  ③ GENERATE
   │   inject the per-mention candidate lists into the Cypher prompt;
   │   GraphCypherQAChain writes + executes the Cypher
   ▼
 answer + predicted Cypher
```

Code: [`ner_agent_auto.ask_auto`](../ner_agent_auto.py) dispatches on the resolved
spec and calls [`plan_exec.get_plan_exec_evidence`](../plan_exec.py); the per-mention
work is in `plan_exec.execute_entity`.

---

## ① PLAN — decompose the question

One LLM call ([`plan_exec.plan_entities`](../plan_exec.py), uses the NER LLM =
`config.NER_LLM_CONFIG`, currently gpt-4.1) turns the question into a JSON list of
mentions, each tagged:

```json
[
  {"mention": "TWA",        "kind": "node",     "descriptor": "airline operator name"},
  {"mention": "JFK",        "kind": "node",     "descriptor": "airport name"},
  {"mention": "departed from","kind": "relation","descriptor": "departure airport relation"}
]
```

* `mention` is the **verbatim surface form** (perturbations kept — they are
  fuzzy/vector-matched downstream).
* `kind` is `node` (a named value) or `relation` (a verb/preposition phrase).
* `descriptor` is a short type phrase used to route to a field.

---

## ② EXECUTE — ground each mention

For every mention, `execute_entity` runs three sub-steps. **No ReAct loop** — the
control flow is fixed; the LLM only judges.

### a. Route to fields

The `descriptor` is embedded and matched against the **tool FAISS index** (one
document per `Label.property` field), returning the top
`PLAN_EXEC_TOOLS_PER_ENTITY` (= 2) fields, preferring those whose kind matches the
mention. The tool index is the small per-tool index that `react` already builds
— **no per-value embedding index is required**.

### b. Initial hybrid retrieval

Each routed field is searched **both ways** and the results unioned
(`plan_exec._retrieve_values`, `hybrid=True`):

| source | size knob | what it is |
|---|---|---|
| fuzzy | `PLAN_EXEC_HYBRID_FUZZY_K` = 10 | BM25 / Lucene full-text (`search_tool(mode="fuzzy")`) |
| vector | `PLAN_EXEC_HYBRID_VECTOR_K` = 5 | in-graph Neo4j vector index (`search_tool(mode="vector")`) |

Fuzzy hits come first, then the vector hits not already present (dedup). Vector
recall is the lever for **aliases** ("TWA" → "Trans World Airlines") that share no
characters with the canonical value; fuzzy covers casing / typo / partial.

The initial vector budget is deliberately small (5): a static 10 fuzzy + **10**
vector was measured to be *worse* than 10 + 5 (extra vector candidates add noise
the Cypher LLM must wade through). The corrective loop adds more vector **only
when needed** (next).

Relation mentions do not value-search; they emit the structural pattern
`(:A)-[:rel]->(:B)` for the Cypher LLM.

### c. Corrective loop — the LLM picks the next move

After the initial retrieval, up to `PLAN_EXEC_MAX_ITER` (= 3) rounds run **only
while the mention is not yet grounded**. Each round an LLM judge
(`plan_exec._judge_step`, NER LLM) sees the question, the mention, the candidates
retrieved so far, **and a menu of other available name-like fields**, and returns
exactly one token:

| judge output | action |
|---|---|
| `done` | a candidate already is the canonical value (allowing perturbations), or nothing more could help → **stop** |
| `value` | right kind of field, value just not retrieved yet → **deepen the used field(s)** |
| `<Label.property>` | wrong field → **add this specific field the LLM chose from the menu** |

* A **fast path** short-circuits to `done` (no LLM call) when a normalised
  substring already matches — cheap for the easy cases.
* `value` deepening for hybrid (`plan_exec._escalate_fetch`, `hybrid=True`) pulls
  **more fuzzy AND more vector** at a growing depth (`k = depth + budget`, budget
  shrinking `5 → 3 → 1` across rounds). Because the initial vector budget was only
  5, the first deepen jumps vector ~5 → 15 — i.e. vector gets the biggest boost
  exactly when grounding failed.
* `<Label.property>` adds the LLM's chosen field with a **full** initial-style
  hybrid fetch (10 fuzzy ∪ 5 vector). The LLM picks the field by reasoning about
  the candidate types (e.g. "the candidates are airport names but the mention is
  an airline → search `Operator.name`"), which beats walking a fixed routing rank.

The output is one token (matched against the menu / `done` / `value` keywords),
**not JSON** — so there is no structured-output parsing risk.

---

## ③ GENERATE — hand candidates to the Cypher LLM

`plan_exec.build_injection` formats the evidence as a mention-grouped candidate
block and injects it into the Cypher prompt's `{relevant_entities}` slot:

```
Retrieved candidate values for each entity mention ... choose the SINGLE
best-matching canonical value for the WHERE clause ...
- "TWA"          →  Operator.name: "Trans World Airlines" | "Trans World Express" | ...
- "JFK"          →  Airport.name:  "John F. Kennedy International Airport" | ...
- "departed from"→  relationship pattern: (:FlightAccident)-[:departsFrom]->(:Airport)
```

The Cypher LLM (`config.CYPHER_LLM_CONFIG`) does the final **value-linking** — it
chooses the right canonical value per mention while writing the Cypher. Crucially,
the grounder never forces a single value: it hands a short candidate list and lets
generation decide. `GraphCypherQAChain` then runs the Cypher and returns the
answer + the predicted query.

---

## Why this design

* **Per-mention decomposition** beats whole-question RAG (FCAV): a single
  question embedding blurs multiple entities; decomposing routes each precisely.
* **Candidates, not a forced pick** avoids the lossy single-value synthesis that
  cripples the ReAct agent.
* **Conditional escalation** gets vector/extra-field recall **without** the noise
  penalty of statically dumping more candidates.
* **LLM picks the field** (not next-ranked routing) — the biggest win on aliases,
  which are usually a *wrong-field* problem, not a recall problem.

---

## Config knobs

All in [`config.py`](../config.py):

| knob | default | meaning |
|---|---|---|
| `PLAN_EXEC_TOOLS_PER_ENTITY` | 2 | fields routed per mention (initial) |
| `PLAN_EXEC_HYBRID_FUZZY_K` | 10 | fuzzy candidates per field |
| `PLAN_EXEC_HYBRID_VECTOR_K` | 5 | vector candidates per field |
| `PLAN_EXEC_ESCALATE` | 1 (on) | run the corrective loop |
| `PLAN_EXEC_MAX_ITER` | 3 | max corrective rounds per mention |
| `PLAN_EXEC_ESCALATE_BUDGET` | (5, 3, 1) | values added per successive round |

Fuzzy mode (`RETRIEVAL_TYPE=fuzzy`) is identical except retrieval is BM25-only
(no vector, zero embedding infrastructure); on flight_accident it trails hybrid
by a few points (0.774 vs 0.792 EA). See
[`ablation_flight_accident.md`](ablation_flight_accident.md).

---

## Worked example — "TWA" (alias)

1. **PLAN** → mention `"TWA"`, kind `node`, descriptor `"airline operator name"`.
2. **Route** → top-2 fields, say `AircraftModel.name`, `Airport.name` (routing
   guessed wrong — "TWA" looks generic).
3. **Initial hybrid** → 10 fuzzy + 5 vector on each; none is "Trans World Airlines".
4. **Round 1** judge sees candidates are *aircraft/airport* names, mention is an
   airline → returns `Operator.name`. → full hybrid fetch on `Operator.name`;
   vector surfaces "Trans World Airlines".
5. **Round 2** judge → `done` (grounded).
6. **GENERATE** → Cypher LLM writes `... WHERE o.name = "Trans World Airlines" ...`.
