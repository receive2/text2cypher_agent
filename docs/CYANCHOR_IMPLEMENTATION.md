# CyANCHOR — Implementation Reference

CyANCHOR is this project's text-to-Cypher **value-grounding** method: a
deterministic *plan → execute → generate* grounder with LLM-guided corrective
loops, plus two post-generation safety guards. It is the paper's contribution
and the only method that gets optimized (the other four — `no_val_link`,
`fcav`, `react`, `graphrag` — are baselines and are held fixed).

This document traces the actual code path end to end. Unless noted, file
references are `plan_exec.py` (the grounder) and `ner_agent_auto.py` (the
orchestrator that calls it).

> Naming note: the method is **CyANCHOR** externally, but the code still calls
> it `plan_exec`. `mode` strings like `cyanchor_fl_node_rel` and the legacy
> `plan_exec_*` both dispatch here ([ner_agent_auto.py:131](../ner_agent_auto.py#L131)).

---

## 1. Where it lives

| Concern | Location |
|---|---|
| Grounder (PLAN/EXECUTE/GENERATE, value-snap) | [plan_exec.py](../plan_exec.py) |
| Orchestration, Cypher gen, retry + semantic repair | [ner_agent_auto.py](../ner_agent_auto.py) `ask_auto` |
| Per-(label,property) search tools (auto-generated) | [generated/generated_node_tools.py](../generated/generated_node_tools.py), [generated/generated_rel_tools.py](../generated/generated_rel_tools.py) |
| Tool routing (FAISS over tool descriptions) | [tools/tool_search.py](../tools/tool_search.py) |
| Retrieval primitives (fuzzy / vector / Levenshtein) | [neo4j_lib/neo4j_search.py](../neo4j_lib/neo4j_search.py) |
| Semantic evaluator (reused read-only from graphrag) | [graphrag.py](../graphrag.py) `_evaluate_semantics` |
| Config knobs | [config.py](../config.py) |

---

## 2. Configuration surface

CyANCHOR's behavior is fully described by a `GroundingSpec`
([config.py:303](../config.py#L303)) resolved from `METHOD=cyanchor` plus these knobs:

**Retrieval arms** (≥1 must be on; unioned per field):

| Knob | Default | Arm |
|---|---|---|
| `RETRIEVAL_FUZZY` | on | BM25 / Lucene full-text |
| `RETRIEVAL_VECTOR` | off | in-graph embedding kNN (needs embeddings; the `hybrid` flag) |
| `RETRIEVAL_LEVENSHTEIN` | on | APOC normalized edit-distance scan |

**Tool scope**: `TOOL_TYPE = node | node_rel` (default `node_rel`).

**Corrective escalation** ([config.py:426-447](../config.py#L426)):

| Knob | Default | Meaning |
|---|---|---|
| `PLAN_EXEC_TOOLS_PER_ENTITY` | 2 | fields searched in the initial retrieval |
| `PLAN_EXEC_VALUES_PER_TOOL` | 10 | top-K values per field (fuzzy) |
| `PLAN_EXEC_HYBRID_FUZZY_K` / `_VECTOR_K` | 10 / 5 | per-arm K when vector arm is on |
| `RETRIEVAL_LEVENSHTEIN_K` | 10 | candidates from the Levenshtein arm |
| `PLAN_EXEC_ESCALATE` | on | enable the corrective LLM-judge loop |
| `PLAN_EXEC_MAX_ITER` | 3 | max escalation rounds per mention |
| `PLAN_EXEC_ESCALATE_BUDGET` | (5,3,1) | extra values per successive `value` round |
| `PLAN_EXEC_SKIP_GROUNDED` | on | skip escalation when already cleanly grounded |
| `PLAN_EXEC_PARALLEL_MENTIONS` | on | run mentions concurrently |

**Semantic repair** ([config.py:520-522](../config.py#L520), CyANCHOR-only):

| Knob | Default | Meaning |
|---|---|---|
| `CYPHER_SEMANTIC_REPAIR` | on | enable result-evaluate → regenerate loop |
| `CYPHER_REPAIR_MAX_ROUNDS` | 4 | round budget when semantic repair is on |
| `CYPHER_EMPTY_IS_WRONG` | on | treat a 0-row result as a defect |
| `CYPHER_RETRY_MAX_ROUNDS` | 2 | error-only retry budget (react baseline + repair-off) |
| `PLAN_EXEC_VALUE_SNAP` | on | post-generation existence-gated snap guard |

---

## 3. End-to-end pipeline

```
ask_auto(question, mode="cyanchor_…")          ner_agent_auto.py
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ get_plan_exec_evidence()           plan_exec.py:724       │
│                                                           │
│  ① PLAN     plan_entities()  ── 1 LLM call ──►            │
│             [{mention, kind, descriptor}, …]              │
│                                                           │
│  ② EXECUTE  execute_entity()  per mention (parallel):     │
│       a. route descriptor → top-2 fields  (FAISS)         │
│       b. initial retrieval = fuzzy ∪ vector ∪ Levenshtein │
│       c. corrective escalation loop (≤3 rounds, LLM judge)│
│       d. pre-generation ABSTAIN judge (keep/select/drop)  │
│                                                           │
│  ③ build_injection() → {relevant_entities} block          │
└─────────────────────────────────────────────────────────┘
        │  injection block + structured evidence
        ▼
┌─────────────────────────────────────────────────────────┐
│ ④ Cypher generation                ner_agent_auto.py:1645 │
│    filled = shared system prompt                          │
│           + injection block                               │
│           + _UNION_GUIDANCE (fair, all modes)             │
│    _generate_execute_cypher_with_retry():                 │
│       generate → execute                                  │
│       ├─ DB error → CoT error-repair                      │
│       └─ ok → semantic evaluate → regenerate (CyANCHOR)   │
│       anti-oscillation: keep accepted, else 1st executable│
└─────────────────────────────────────────────────────────┘
        │  cypher + rows
        ▼
┌─────────────────────────────────────────────────────────┐
│ ⑤ value-snap guard          plan_exec.snap_values_to_…    │
│    existence-gated: only non-existent WHERE values        │
│    one LLM closed-list pick → substitute → re-execute     │
└─────────────────────────────────────────────────────────┘
        │
        ▼   result dict {cypher, result, context, …}
```

Stages ②b–②d run **per mention, concurrently** (thread pool sized to
`min(#mentions, MAX_THREAD=5)`, order preserved) when
`PLAN_EXEC_PARALLEL_MENTIONS` is on ([plan_exec.py:759-776](../plan_exec.py#L759)).

---

## 4. Stage ① — PLAN

`plan_entities(query, llm)` ([plan_exec.py:208](../plan_exec.py#L208)) makes **one**
LLM call decomposing the question into a list of mentions, each:

```json
{"mention": "<verbatim span>", "kind": "node" | "relation", "descriptor": "<2-5 word type>"}
```

Key prompt rules ([plan_exec.py:143-172](../plan_exec.py#L143)):

- `mention` is the **verbatim surface form** — typos, casing, and abbreviations
  are kept on purpose, because they are what the retrieval arms fuzzy-match.
- A complete proper name stays **one** node mention (e.g. *"South African
  Airways Flight 201"* is one node, not split on the flight number).
- `node` = a named thing/value; `relation` = a verb/preposition phrase
  describing how two things connect (`directed`, `departed from`).
- `descriptor` describes the **type** (so it routes to the right tool) — it is
  the FAISS query in the next stage, not the mention itself.

`_parse_plan` ([plan_exec.py:175](../plan_exec.py#L175)) strips code fences, tolerates
prose around the JSON array, and defaults a missing/invalid kind to `node`. A
PLAN failure returns `[]` (the question then free-generates with no grounding).

Design note: **the mention IS the search phrase** — grounding is lossless
between stages. The verbatim span extracted here is exactly the string the
retrieval arms will match; there is no intermediate re-extraction or
normalization step through which a mention could be silently rewritten or
dropped before it reaches retrieval.

---

## 5. Stage ② — EXECUTE

`execute_entity(entity, …)` ([plan_exec.py:527](../plan_exec.py#L527)) grounds one
mention and returns structured evidence:

```python
{"mention", "kind",
 "candidates": [{"label", "property", "values": [...]}],
 "patterns": ["(:A)-[:rel]->(:B)", ...]}
```

### 5a. Routing — descriptor → fields

`_route_tools(descriptor, kind, …)` ([plan_exec.py:226](../plan_exec.py#L226)):

1. Pick the FAISS tool index — node-only or node+rel — per `TOOL_TYPE`
   (`_get_vectorstore(mode="react_node_only" | "react_node_rel")`).
2. `search_tools(vs, user_query=descriptor, top_l=…)` returns ranked tool
   `func_name`s.
3. `_tool_meta()` ([plan_exec.py:126](../plan_exec.py#L126)) maps each `func_name` →
   `{label, property, kind, rel_pattern, desc}` by **AST-parsing** the generated
   tool source for its fixed `search_tool(node_label=…, property_name=…)` call
   ([plan_exec.py:84](../plan_exec.py#L84)). Built once, cached.
4. Tools whose `kind` matches the mention's are preferred; the list is
   rank-ordered so the first `PLAN_EXEC_TOOLS_PER_ENTITY` (=2) drive the initial
   retrieval and the rest form an escalation pool.

For a **relation** mention, routing emits the `(:A)-[:rel]->(:B)` pattern from
the tool docstring instead of retrieving values
([plan_exec.py:571-573](../plan_exec.py#L571)).

### 5b. Initial retrieval — the three arms

`_retrieve_values(mention, label, prop, hybrid)` ([plan_exec.py:278](../plan_exec.py#L278))
unions the enabled arms per field, deduped, insertion-ordered:

1. **Fuzzy** (`RETRIEVAL_FUZZY`) — `search_tool(…, mode="fuzzy")`, Neo4j
   Lucene/BM25 full-text. Catches casing, mild typos, partial names. K =
   `PLAN_EXEC_HYBRID_FUZZY_K` if the vector arm is on, else `PLAN_EXEC_VALUES_PER_TOOL`.
2. **Vector** (`RETRIEVAL_VECTOR`, the `hybrid` flag) — `mode="vector"`,
   in-graph embedding kNN. The lever for **aliases that share no characters**
   with the canonical value. Top `PLAN_EXEC_HYBRID_VECTOR_K`. Failures are
   swallowed (only ever adds recall).
3. **Levenshtein** (`RETRIEVAL_LEVENSHTEIN`) — `_levenshtein_fetch`
   ([plan_exec.py:253](../plan_exec.py#L253)), a server-side
   `apoc.text.levenshteinSimilarity` scan over the full value set, best-first.
   Catches **char-level perturbations fuzzy misses** (abbrev codes, dense
   typos). Handles scalar **and** array properties (e.g. `aliases`): tries the
   scalar query, retries with `UNWIND` on a type error. Returns `[]` on any
   failure (e.g. APOC missing), so it only adds recall.

Candidate values are grouped by `(label, property)` in an insertion-ordered,
deduped `OrderedDict`; array properties are flattened to plain strings
(`_add`, [plan_exec.py:555](../plan_exec.py#L555)).

### 5c. Corrective escalation loop

If `escalate` is on, the mention is a node, candidates exist, and the mention
is **not** already cheaply grounded, run up to `PLAN_EXEC_MAX_ITER` (=3) rounds
([plan_exec.py:597-621](../plan_exec.py#L597)). Each round an LLM judge
(`_judge_step`, [plan_exec.py:491](../plan_exec.py#L491)) returns exactly one of:

- **`done`** — a candidate already is the canonical value (allowing typo/casing/
  abbrev/partial/alias), or no field could plausibly hold it → stop.
- **`value`** — right *kind* of field but no match → **deepen** the used
  field(s). `_escalate_fetch` ([plan_exec.py:338](../plan_exec.py#L338)) pulls
  `depth + budget` more values (budget walks `(5,3,1)`); fuzzy mode deepens
  fuzzy, hybrid deepens fuzzy **and** vector. Dedup keeps only the new tail.
- **`<Label.property>`** — the mention belongs in a **different** field; the
  judge copies one field name verbatim from a menu of available name-like node
  fields (`_field_menu`, [plan_exec.py:454](../plan_exec.py#L454), restricted to
  `name`/`title`/`alias`-style props, excluding already-searched ones). That
  field gets a full initial-style fetch.

Fast paths and safety: `_judge_step` returns `done` without an LLM call when a
normalized substring already matches ([plan_exec.py:499-501](../plan_exec.py#L499)),
and falls back to `done` on any parse/LLM error (stop rather than loop).
`PLAN_EXEC_SKIP_GROUNDED` + `_cheap_grounded` ([plan_exec.py:360](../plan_exec.py#L360))
skips the whole loop when a candidate already exact/substring-matches the
mention (latency win, ~EA-neutral).

### 5d. Pre-generation ABSTAIN judge

After escalation, for a node mention that is **not** cheaply grounded (the
abbrev / alias / misroute region), one LLM call (`_judge_select`,
[plan_exec.py:412](../plan_exec.py#L412)) decides ([plan_exec.py:629-642](../plan_exec.py#L629)):

- **`select`** → the one candidate the mention means (validated to be verbatim
  in the list, exact then normalized match). Evidence is **filtered to that
  single value**.
- **`abstain`** (judge says `NONE` or names a non-listed value) → evidence is
  **suppressed** (`by_target` emptied) so the Cypher LLM free-generates the
  predicate from the question + schema. No forced pick, no fabricated value.
- **`keep`** (transient failure / nothing to judge) → leave the list as-is, so a
  flaky LLM degrades to the no-judge behavior rather than dropping grounding.

Cheaply-grounded mentions skip this judge entirely (free, zero regression).

---

## 6. Stage ③ — GENERATE (build injection)

`build_injection(evidence)` ([plan_exec.py:660](../plan_exec.py#L660)) formats the
per-mention evidence into the `{relevant_entities}` block. It is
**mention-grouped**, candidates kept as a best-first list (not a single resolved
`{key: value}` dict), e.g.:

```
- "Tmo Hooper"  →  Person.name: "Tom Hooper" | "Tobe Hooper" | …
- "directed"    →  relationship pattern: (:Person)-[:DIRECTED]->(:Movie)
```

A self-contained header ([plan_exec.py:679-688](../plan_exec.py#L679)) instructs the
Cypher LLM that these are **suggestions, not a closed set**: use a candidate if
one fits, ignore them and write the predicate yourself if none fits, and use
**at most one value per mention** (overriding the template's default "use all
pairs" framing). Empty evidence renders as `{}`.

The block is injected into the shared Cypher system prompt as `{relevant_entities}`.

---

## 7. Stage ④ — Cypher generation, error retry, semantic repair

`ask_auto` dispatches CyANCHOR (and `react`) through the **transparent manual**
generate→execute path so the retry budget is the only variable
([ner_agent_auto.py:1645-1664](../ner_agent_auto.py#L1645)). The Cypher prompt is:

```
shared system prompt  +  injection block  +  _UNION_GUIDANCE
```

`_UNION_GUIDANCE` ([plan_exec.py:702](../plan_exec.py#L702)) is a static,
schema-independent block on how to structure "either A or B" disjunctions
(COUNT inside one `CALL { … UNION … }` vs. parallel `UNION` for LISTING). For
**fair comparison it is appended to every mode's prompt**, not just CyANCHOR's.

`_generate_execute_cypher_with_retry` ([ner_agent_auto.py:1292](../ner_agent_auto.py#L1292))
loops up to `max_rounds` (= `CYPHER_REPAIR_MAX_ROUNDS`=4 when semantic repair is
on, else `CYPHER_RETRY_MAX_ROUNDS`=2):

1. **Generate** Cypher from the (possibly correction-prefixed) prompt; clean
   code fences.
2. **Execute** via `execute_cypher`.
3. **DB error** → CoT **error-repair** ([ner_agent_auto.py:1348-1361](../ner_agent_auto.py#L1348)):
   feed back the error + failed query, ask the LLM to *first reason about the
   error and the required structure, then rewrite*. (Used by both `react` and
   CyANCHOR.) The doc-comment notes blind re-rolls fix ~0/12 of the UNION
   failures, whereas one reasoned repair corrects far more per round.
4. **Executed OK**:
   - If semantic repair is **off** (react baseline) → accept the first
     executable result and stop.
   - **CyANCHOR-only semantic evaluation**: a 0-row result with
     `CYPHER_EMPTY_IS_WRONG` is `empty`; otherwise `_evaluate_semantics`
     ([graphrag.py:569](../graphrag.py#L569), reused read-only) classifies into
     `accept` / `incorrect` / `illogical` / `incomplete`.
     - `accept` → stop.
     - otherwise → build a **grounding-aware repair header** (keeps the
       candidate injection from `filled_prompt`, **adds** the semantic feedback +
       a CoT request) and regenerate ([ner_agent_auto.py:1392-1418](../ner_agent_auto.py#L1392)).

**Anti-oscillation** ([ner_agent_auto.py:1420-1423](../ner_agent_auto.py#L1420)): if no
round is ever accepted, the loop returns the **first executable** attempt — so
semantic repair can only match-or-beat the no-repair result, never regress it.

This is the key difference from the `graphrag` baseline: GraphRAG does the same
generate→execute→evaluate→repair loop but with **no pre-grounding**; CyANCHOR
carries its retrieved candidates into every repair round.

---

## 8. Stage ⑤ — value-snap guard

`snap_values_to_candidates` ([plan_exec.py:854](../plan_exec.py#L854), called at
[ner_agent_auto.py:1697](../ner_agent_auto.py#L1697)) fixes the
"retrieved-but-not-used" failure: the LLM copied the question's perturbed
surface form into a `WHERE` clause even though the canonical value was in the
candidate list. It is deliberately conservative:

1. **Existence gate** — `_snap_value_targets` ([plan_exec.py:825](../plan_exec.py#L825))
   extracts `(label, prop, value)` from `=` and inline-map literals **only**
   (it skips `=~` / `CONTAINS` / `STARTS WITH` — intentional partial matches).
   A value that **exists** in the DB (`_value_exists`) is **never touched**, so
   correct/normal queries are safe. On any check failure it fails *safe* (treats
   the value as existing).
2. For each non-existent value, gather candidates: a fresh fuzzy retrieval keyed
   on the **field the generator actually used** (robust to routing differences),
   unioned with the per-field candidates from PLAN_EXEC's evidence.
3. **One** LLM call (`_SNAP_SELECT_PROMPT`, [plan_exec.py:801](../plan_exec.py#L801))
   maps each broken value → a chosen candidate (verbatim) or `NONE` — a
   closed-list discriminative task, far more reliable than Cypher generation.
4. Substitute only **validated** picks (must be a real candidate, not `NONE`/
   unchanged) into the Cypher.
5. Back in `ask_auto`, the snapped query is re-executed and **adopted only if it
   still runs without error** ([ner_agent_auto.py:1704-1708](../ner_agent_auto.py#L1704)).

---

## 9. Safety / fairness properties (by construction)

- **At least one retrieval arm** is required (`config` raises otherwise) — recall
  is never zero by misconfiguration.
- **Fail-safe everywhere**: PLAN/judge/retrieval failures degrade to "no
  grounding" or "stop", never to a fabricated value or an infinite loop.
- **Abstain over force**: both the pre-gen ABSTAIN judge and value-snap can only
  pick a real candidate or decline — they cannot hallucinate a value.
- **Monotone repair**: anti-oscillation + "adopt-only-if-still-runs" mean the
  corrective stages can only match-or-improve the executable baseline result.
- **Fair comparison**: every method sees the identical shared system prompt and
  `_UNION_GUIDANCE`; CyANCHOR's only privilege is the injection block + its
  own (CyANCHOR-gated) semantic repair / snap stages.

---

## 10. Ablation axes (what the paper can toggle)

| Axis | Off → On effect |
|---|---|
| `RETRIEVAL_FUZZY` / `_VECTOR` / `_LEVENSHTEIN` | which recall arms feed candidates |
| `PLAN_EXEC_ESCALATE` | static initial retrieval vs. LLM-judge corrective loop |
| ABSTAIN judge (implicit, on) | suppress bad groundings vs. always inject |
| `CYPHER_SEMANTIC_REPAIR` | error-only retry vs. result-evaluate→regenerate |
| `CYPHER_EMPTY_IS_WRONG` | whether 0 rows triggers repair |
| `PLAN_EXEC_VALUE_SNAP` | post-generation snap guard on/off |
| `TOOL_TYPE` | `node` vs. `node_rel` tool scope |

Example invocations:

```bash
# CyANCHOR, all three arms, node+rel tools
METHOD=cyanchor RETRIEVAL_VECTOR=1 python eval_run.py

# CyANCHOR, fuzzy+Levenshtein only (no embeddings needed) — the shipped default
METHOD=cyanchor python eval_run.py

# Single question, verbose trace
python ner_agent_auto.py "Who directed The Matrix?" --mode cyanchor_fl_node_rel --verbose
```

---

## 11. Worked example (perturbed mention)

Question: *"How many movies did **Tmo Hooper** direct?"* (typo for *Tom Hooper*)

1. **PLAN** → `[{"Tmo Hooper", node, "film director name"}, {"direct", relation, "directed relation"}]`.
2. **EXECUTE** "Tmo Hooper":
   - route `"film director name"` → `Person.name`, `Person.aliases`.
   - fuzzy + Levenshtein over `Person.name` → `["Tom Hooper", "Tobe Hooper", …]`.
   - not cheaply grounded ("tmohooper" ⊄ "tomhooper") → escalation judge says
     `done` (right kind, candidate present) → ABSTAIN judge `select`s
     `"Tom Hooper"` → evidence filtered to that one value.
   - "direct" (relation) → pattern `(:Person)-[:DIRECTED]->(:Movie)`.
3. **GENERATE** injection:
   `- "Tmo Hooper" → Person.name: "Tom Hooper"` /
   `- "direct" → relationship pattern: (:Person)-[:DIRECTED]->(:Movie)`.
4. Cypher LLM writes `MATCH (p:Person {name:"Tom Hooper"})-[:DIRECTED]->(m:Movie) RETURN count(m)`,
   executes, semantic verdict `accept`.
5. value-snap: `"Tom Hooper"` exists → existence gate skips it. Done.

Had the ABSTAIN judge mis-fired and the LLM copied `"Tmo Hooper"` into the
`WHERE`, **value-snap** would have caught it: the value doesn't exist → closed-list
pick → substitute `"Tom Hooper"` → re-execute.
