# Multi-Agent GraphRAG baseline (`VAL_LINK_MODE=graphrag`)

A self-correcting text-to-Cypher baseline, after *Multi-Agent GraphRAG: A
Text-to-Cypher Framework for Labeled Property Graphs*. It is the structural
opposite of the repo's other modes: **it does no value-linking before
generation.** It generates Cypher first, then repairs it from execution +
database-validation feedback over up to `GRAPHRAG_MAX_ITER` rounds.

Implementation: [`graphrag.py`](../graphrag.py) (self-contained, like
[`fcav.py`](../fcav.py) / [`plan_exec.py`](../plan_exec.py)). Dispatched by a
one-line early return in `ner_agent_auto.ask_auto`, so the whole eval/CLI path
is unchanged and `run_graphrag` returns the same result dict as every other mode
(`entities` / `cypher` / `result` / `context` / `mode`), plus a
`graphrag_trace` list for per-round analysis.

## Loop

```
generate Cypher → execute → Evaluator classifies
                   │
                   ├─ Accept                       → format & return the answer
                   │
                   ├─ Incorrect / Illogical /      → hand the semantic/logical
                   │  Incomplete                     feedback to the Generator
                   │
                   └─ Error or Empty               → STRUCTURAL repair:
                        • extract node labels, property–value pairs and
                          relationship patterns from the generated Cypher
                        • verify each against the database
                        • for invalid values, retrieve normalized-Levenshtein
                          candidate replacements and let the LLM pick one
                        • aggregate execution + semantic + validation feedback
                        • Generator rewrites the Cypher
```

### Agents / stages
- **Generator** — `cypher_llm` (config `CYPHER_LLM_CONFIG`) fills the existing
  `TEXT2CYPHER_SP` template. Round 1 has no entity hints; later rounds inject the
  aggregated repair feedback into the `{relevant_entities}` slot.
- **Executor** — reuses `eval.metrics_CypherBench.execute_cypher` (timeout +
  `(rows, error)` classification: `rows == []` is empty, `rows is None` on error).
- **Evaluator** — `ner_llm` (config `NER_LLM_CONFIG`). Error/empty go straight to
  structural repair; non-empty results are judged `accept | incorrect | illogical
  | incomplete`.
- **Extractor** — regex pulls labels (`:Label`), relationship types (`[:TYPE]`)
  and equality predicates, covering `alias.prop = 'v'`, `toLower(alias.prop) =
  toLower('v')`, and inline-map `(:Label {prop: 'v'})` forms.
- **Validator** — labels/rel-types checked against `db.labels()` /
  `db.relationshipTypes()`; values checked with a `MATCH ... WHERE n.prop = $v
  RETURN count(n)>0` existence query.
- **Retriever + Selector** — candidate replacements are ranked by **normalized
  Levenshtein** over the full `(label, property)` value set via APOC
  (`apoc.text.levenshteinSimilarity`, server-side), with a capped Python-scan
  fallback. The LLM selector picks the best candidate (or none) per invalid value.

## Configuration (`config.py`)

| knob | default | meaning |
|---|---|---|
| `GRAPHRAG_MAX_ITER` | `4` | generate→execute→correct rounds (paper = 4) |
| `GRAPHRAG_CANDIDATE_K` | `10` | Levenshtein candidates per invalid value |
| `GRAPHRAG_LEV_THRESHOLD` | `0.0` | min normalized-Levenshtein similarity to keep a candidate |
| `GRAPHRAG_SCAN_CAP` | `50000` | distinct-value cap for the Python fallback scan (no APOC) |
| `GRAPHRAG_EMPTY_IS_WRONG` | `1` | treat an empty result as a correction trigger |
| `GRAPHRAG_LLM_EVALUATOR` | `1` | run the LLM evaluator on non-empty results (off ⇒ auto-accept) |

Generator = `CYPHER_LLM_CONFIG`; evaluator + selector = `NER_LLM_CONFIG`.

## Run

```bash
VAL_LINK_MODE=graphrag python eval_run.py
VAL_LINK_MODE=graphrag python ner_agent_auto.py "Who directed the matriks?" --verbose
```

## Faithfulness notes

This is a **baseline** — it reproduces the paper's method, including its
weaknesses, so the gap to our own method is not understated. Two implementation
points were necessary to make it *the paper's* method (not a crippled version),
and one tempting "improvement" was deliberately **not** made:

1. **Extraction covers `alias.prop = 'x'`, `toLower(...)`-wrapped equality, and
   inline-map `(:Label {prop: 'x'})` forms.** Generators emit all three; an
   extractor that only catches the first silently extracts nothing and the
   value-grounding step no-ops. This is fixing a broken implementation, not
   strengthening the baseline beyond the paper.
2. **Candidate retrieval uses normalized Levenshtein over the real `(label,
   property)` value set (APOC `levenshteinSimilarity`), as the paper specifies.**
   Lucene fuzzy fulltext does NOT surface "The Matrix" for "the matriks" at any
   fuzziness, so using it would make the baseline *weaker than the paper* — also
   a misrepresentation.
3. **The evaluator is deliberately kept perturbation-naive.** The paper's
   evaluator does not know mentions are perturbed; it judges plainly
   (accept/incorrect/illogical/incomplete). We do NOT tell it "mentions may be
   typo'd → ground to canonical," and we do NOT add a best-non-empty
   anti-oscillation safety net. Both would make the baseline stronger than the
   paper and leak our own method's insight — exactly what a baseline must not
   do. The loop returns the last (or accepted) attempt, faithfully.

Note on retrieval scope (relevant when comparing against our method): normalized
Levenshtein wins **typo/casing** but loses **partial** (length mismatch) and
**abbrev/alias** (no surface overlap). Lucene wins partial; embeddings are needed
for alias/abbrev. The retrievers are complementary, not ranked.

## Smoke results (faithful baseline)

20-example smoke batch on `cypherbench_augmented / movie` (port 15066), GPT-4.1 in
all slots, faithful baseline: **EA 8/20 = 0.40, PSJS avg 0.587, 0 execution
errors, ~12 s/example.** By perturbation strategy (EA): casing 2/2, typo 3/6,
partial 2/4, alias 1/5, **abbrev 0/3**. The profile matches the retrieval
analysis above — char-level perturbations (casing/typo) are handled by normalized
Levenshtein, while abbrev/alias collapse (no surface overlap for edit distance to
exploit). Indicative only — run the full pair + `eval_aggregate.py` for headline
numbers.

Tests: [`tests/test_graphrag.py`](../tests/test_graphrag.py) (offline; extraction,
normalized Levenshtein, selector fallback, loop stop conditions).
