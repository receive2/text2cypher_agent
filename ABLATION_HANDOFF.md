# CyANCHOR component ablation — run handoff

Date: 2026-09-29 · Repo: https://github.com/receive2/text2cypher_agent · Branch: `ablation/gpt-5.6-terra-judge-on-node` (`main` at `102db5a` plus the files listed in §4)

This file is everything a second machine needs to run and score the component ablation. It replaces nothing in the repo: machine setup follows `docs/EXPERIMENT_HANDOUT.md`, and the ablation itself is one command.

---

## 1. What is being run, in one paragraph

The ablation measures how much each CyANCHOR component contributes. For each graph we run the **reference** (the released configuration) once, then one run per component with exactly one switch flipped. Every run uses the same code, data (v2.3 release), backbone (`gpt-5.6-terra`), prompts and temperature 0. Scoring pairs each variant with the reference **per question** on identical questions, so a cell is "questions gained / lost by removing this component", tested with a two-sided sign test.

## 2. Decisions in force

| Item | Decision | Status |
|---|---|---|
| Relation tools in CyANCHOR | **Off.** CyANCHOR routes on node-property tools only (`CYANCHOR_TOOL_SCOPE=node`). Not a table row, not discussed as a component. Limitations states the scope. | Decided |
| Select-or-abstain judge | **On** in the reference. Its removal is one ablation cell. | Working decision, see §9 |
| Main-text table | Only components whose pooled effect is significant (p < 0.05). | Decided (advisor's rule) |
| Appendix table | All six rows, including those without a measurable effect, referenced from the main text. | Recommended |
| `CYPHER_EMPTY_IS_WRONG` | Off, never appears in any table. | Decided |
| Vector arm | Not part of this run. The archives carry no embeddings. | Deferred |
| Graphs | flight_accident, nba, healthcare, pole. pole runs **in full** (1,283 questions). | This run |

**One thing is not yet aligned in the repo.** `eval_config.py` on `main` still has `PLAN_EXEC_SELECT_JUDGE = False` from the 2026-09-28 config freeze. The ablation driver does not read that default, it sets every switch itself, so this run is unaffected. The default must be flipped before the main-table sweep if the judge stays on.

## 3. The cells

Reference = node-property tools, fuzzy + Levenshtein arms, escalation loop, select-or-abstain judge, semantic repair, value-snap, all on.

| Cell name | Switch flipped | Row in the table | What it isolates |
|---|---|---|---|
| `reference` | none | CyANCHOR (full) | the released system |
| `no_value_snap` | `PLAN_EXEC_VALUE_SNAP=0` | − value-snap guard | generator copied the question's corrupted literal although the right value was retrieved |
| `fuzzy_only` | `RETRIEVAL_LEVENSHTEIN=0` | − Levenshtein arm | character-level recall (dense typos, abbreviation-like codes) |
| `no_escalate` | `PLAN_EXEC_ESCALATE=0` | − escalation loop | recovery from routing misses and shallow retrieval |
| `no_semantic_repair` | `CYPHER_SEMANTIC_REPAIR=0` | − semantic repair | fixing queries that execute but answer wrongly |
| `no_select_judge` | `PLAN_EXEC_SELECT_JUDGE=0` | − select-or-abstain judge | pre-filtering of long candidate lists |
| `lev_only` | `RETRIEVAL_FUZZY=0` | − fuzzy arm | token-level BM25 recall |

7 cells × 4 graphs = **28 cells**. The driver runs them in this order, so the four rows most likely to reach the main table finish first on every graph.

Question counts a finished cell must show: flight_accident 168, nba 251, healthcare 418, pole 1,283.

## 4. Machine setup

Follow `docs/EXPERIMENT_HANDOUT.md`, sections 0, 1 and 3. In short:

```bash
git clone https://github.com/receive2/text2cypher_agent.git t2c && cd t2c
git checkout ablation/gpt-5.6-terra-judge-on-node
python3.12 -m venv venv && source venv/bin/activate      # Python 3.12 exactly
pip install -r requirements.txt                            # do this OFF the VPN
cp .env.example .env                                       # put OPENAI_API_KEY in it
python benchmarks/verify.py                                # must print VERIFIED
git log --oneline -3                                       # must list 102db5a
```

What the branch carries:

| Path | What it is | Needed for this run |
|---|---|---|
| `benchmarks/` | v2.3 release, 4,590 questions (part of `main`) | yes |
| `setup_artifacts/` | per-graph prompts, tools, schema files, tool-routing indexes (part of `main`) | yes |
| `scripts/tuning/run_ablation_model.py`, `score_ablation.py` | driver and scorer (part of `main`) | yes |
| `ABLATION_HANDOFF.md` | this file | — |
| `logs/ablation_gpt-5.6-terra/` | the 32 cells of the first run (§9), `records.jsonl` + `summary.json` each | no, reference only |
| `logs/ablation/`, `logs/verify_cols/`, `logs/dev_sweep/` | the 15 gpt-4.1 cells behind `report/ablation_table.md` | no, reference only |
| `datasets_dev/cypherbench_augmented_dev/` | development set on the CypherBench training graph terrorist_attack (1,420 questions), used for parameter tuning | no. The tuning scripts expect it under `~/datasets/cypherbench_augmented_dev/` |

- **VPN must be off** for the whole run. The graph databases live on a VM (34.9.85.21) that corporate VPNs block.
- `setup_artifacts/` ships in git. Never run `scripts/setup_and_archive.py`, never edit that folder.
- Do not edit `eval_config.py` for the ablation.

## 5. Run

### 5.1 Smoke test first (about 3 minutes, a few cents)

```bash
python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on \
    --graphs flight_accident --variants reference,no_select_judge --limit 3
```

Expected last lines:

```
DONE flight_accident/reference EA=... n=3 err=0 ...
DONE flight_accident/no_select_judge EA=... n=3 err=0 ...
ABLATION COMPLETE
```

This smoke test has **not** been run yet on the new driver end to end: on 2026-09-29 the VM was not reachable from the authoring machine. Everything up to the database connection was exercised, and the scorer was self-tested on existing cells. If the smoke test fails for any reason other than the network, stop and report the output.

Delete the smoke folder afterwards: `rm -rf logs/ablation_gpt-5.6-terra__judge-on-node__smoke3`.

### 5.2 Full run

```bash
nohup python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on --pole-full \
    > logs/ablation_terra_judge-on.log 2>&1 &
```

Output goes to `logs/ablation_gpt-5.6-terra__judge-on-node/<graph>__<cell>/` (`pole_full__<cell>` for pole).

### 5.3 Expected duration (gpt-5.6-terra, measured on the earlier run)

| Graph | Questions | Per cell | 7 cells |
|---|---:|---:|---:|
| flight_accident | 168 | 24 min | 2.8 h |
| nba | 251 | 44 min | 5.1 h |
| healthcare | 418 | 82 min | 9.6 h |
| pole (full) | 1,283 | 3.9 h | 27 h |
| **Total, one process** | | | **about 45 h** |

### 5.4 Optional: two checkouts in parallel (about 27 h wall clock)

One checkout can run only one driver. Clone the repo a second time into another folder, set it up the same way, then:

```bash
# checkout A
nohup python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on --pole-full --graphs pole \
    > logs/ablation_terra_pole.log 2>&1 &
# checkout B
nohup python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on --graphs flight_accident,nba,healthcare \
    > logs/ablation_terra_rest.log 2>&1 &
```

Afterwards move checkout B's `logs/ablation_gpt-5.6-terra__judge-on-node/*` into checkout A's folder of the same name. Do not go beyond two processes: CyANCHOR makes many LLM calls per question, and rate-limit timeouts are scored as wrong answers.

### 5.5 If time is short

Run pole in full only for the two cells that answer the judge question, everything else on the 400-question prefix:

```bash
python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on                      # 28 cells, pole = first 400, about 26 h
python scripts/tuning/run_ablation_model.py --model gpt-5.6-terra --judge on --pole-full \
    --graphs pole --variants reference,no_select_judge                                             # 2 cells, about 7.7 h
```

## 6. Watching, resuming, failures

- Progress of the driver: `grep -E "^(START|DONE|FAIL|SKIP|ABORT)" logs/ablation_terra_judge-on.log`
- Progress inside a running cell (the log is block-buffered, `records.jsonl` is written live):
  `wc -l "$(ls -td logs/runs/*cyanchor* | head -1)/records.jsonl"`
- **Resume:** run the same command again. Finished cells print `SKIP`. An interrupted cell starts over from its first question.
- `ABORT: graph database not answering` means VPN on or VM down. Nothing was started.
- `FAIL ... not as planned [...]` means the run did not record the switches, model or question count the cell requires. The run stays in `logs/runs/` and is not used. Report the line.
- `⚠ errors above 2%` on a `DONE` line usually means rate-limit timeouts. Delete that cell's folder and rerun the command.
- The run is complete when the log ends with `ABLATION COMPLETE` and the output folder holds 28 cell folders.

## 7. Score

```bash
python scripts/tuning/score_ablation.py --model gpt-5.6-terra --ref judge-on --pole-full --paper
```

Files written:

| File | Content |
|---|---|
| `report/ablation_table_gpt-5.6-terra__judge-on-node-polefull.md` | Δ EA per graph, paired flips with p-values, per-category breakdown, missing cells |
| `report/ablation_paper_table_gpt-5.6-terra__judge-on-node-polefull.md` | main-text table, full appendix table, flips, component glossary, provenance |
| `..._main.tex` | booktabs `table*` for the main text (`tab:ablation-components`) |
| `....tex` | booktabs `table*` for the appendix (`tab:ablation-full`) |

For the short plan of §5.5, score twice: once without `--pole-full` (seven rows, pole on 400 questions) and once with it (the judge row on the full graph).

## 8. Deliver back

Commit the results to the branch you are on. `logs/` is git-ignored, so the cells have to be added by force:

```bash
gzip -k logs/ablation_terra_*.log                       # driver logs carry every retrieval trace and are large
git add -f logs/ablation_gpt-5.6-terra__judge-on-node logs/ablation_terra_*.log.gz
git add report/ablation_table_gpt-5.6-terra__judge-on-node* report/ablation_paper_table_gpt-5.6-terra__judge-on-node*
git commit -m "ablation: gpt-5.6-terra, released reference (judge on, node tools), 4 graphs, pole in full"
git push
```

Each cell folder holds `records.jsonl` (one line per question: question, gold query, predicted query, EA, PSJS, strategy) and `summary.json` (scores, switches, model). Both are needed.

## 9. Background: what the first run showed

The first run (2026-09-24 to 09-28, `report/ablation_paper_table.md`) used a different reference: every component on, **including relation tools**, and pole on its first 400 questions. Its cells are not reused here because the reference differs.

Δ EA in points, † p < 0.05, ‡ p < 0.01:

| | flight_accident (168) | healthcare (418) | pole (400) | nba (251) | pooled (1,237) |
|---|---:|---:|---:|---:|---:|
| CyANCHOR (full) | 86.3 | 70.1 | 35.8 | 78.5 | 62.9 |
| − escalation loop | −9.5‡ | +0.2 | −2.2 | −8.8‡ | −3.7‡ |
| − select-or-abstain judge | +0.6 | +0.7 | −2.0 | −0.4 | −0.4 |
| − relation tools | +2.4 | +0.7 | −0.3 | −0.8 | +0.3 |
| − Levenshtein arm | −4.8 | −6.2‡ | −4.5‡ | −11.2‡ | −6.5‡ |
| − fuzzy arm | −0.6 | +0.0 | −1.7 | +0.0 | −0.6 |
| − semantic repair | −3.6 | −2.6 | −4.5‡ | −4.4 | −3.7‡ |
| − value-snap guard | −2.4 | −10.8‡ | −18.0‡ | −6.0‡ | −11.0‡ |

What this established:

- **Four components carry the method:** value-snap, the Levenshtein arm, the escalation loop and semantic repair.
- **Escalation is graph-dependent.** It pays off where the alias or abbreviation still shares tokens with the canonical value (flight_accident, nba) and not where it does not (healthcare medical synonyms).
- **The fuzzy arm has no measurable accuracy effect** once the Levenshtein arm is present. It stays in the system: it is the index-backed arm whose cost does not grow with the field, and escalation and value-snap use it regardless of the switch.
- **Relation tools never retrieved values in CyANCHOR.** They only added a traversal-pattern hint that repeats the schema. The benchmarks perturb node-property values only: 0 of 4,590 edits touch a relationship property, and 17 gold queries filter one by string, all in healthcare. Hence "off, stated as scope".
- **Per-question time** is 8 to 12 seconds on every variant. Retrieval is a small fraction, LLM calls dominate.

### The open question this run answers: the judge on pole

All paired judge results so far, Δ = judge on − judge off:

| When | Backbone | Graph | n | Δ EA | helped / hurt | p |
|---|---|---|---:|---:|---|---:|
| 06-22 smoke | gpt-4.1 | movie | 100 | +3.0 | 7 / 4 | 0.55 |
| 06-22 smoke | gpt-4.1 | covid | 100 | −5.0 | 5 / 10 | 0.30 |
| 08-23 | gpt-4.1 | flight_accident | 167 | +1.2 | 7 / 5 | 0.77 |
| 09 | terra | flight_accident | 168 | −0.6 | 5 / 6 | 1.0 |
| 09 | terra | healthcare | 418 | −0.7 | 17 / 20 | 0.74 |
| 09 | terra | pole | 400 | +2.0 | 21 / 13 | 0.23 |
| 09 | terra | nba | 251 | +0.4 | 14 / 13 | 1.0 |

- Pooled, the effect is zero. On pole there is a possible 1 to 3 point benefit, below what 400 questions can detect (about 3.5 points).
- On pole the mechanism is visible in single cases: without the judge the generator copied `'PC'`, `'Don'`, `'Caarol'`; with it, `'Police Constable'`, `'Donald'`, `'Carol'`.
- A test for differences between the four graphs gives p = 0.57, so the data do not yet show that pole differs from the others.
- With all 1,283 pole questions the detection floor drops to about 2 points. Estimated chance that the completed graph reaches p < 0.05: about 60%.

**Proposed reporting rule, to be confirmed before scoring.** The full-graph result is reported whatever it is. If the judge row reaches p < 0.05 with at least 2 points on any graph, the judge enters the main-text table as a graph-dependent component. Otherwise it is described in the method section as a safety component (it can only narrow or remove evidence, never add a value) and its row stays in the appendix.

## 10. Things that will bite

1. **VPN on.** The port can look open while the database does not answer. The driver now checks with a real query and aborts before starting.
2. **Two drivers in one checkout.** They share the live tree of per-graph prompts and tools. The driver refuses to start if an evaluation worker is already running from the same checkout.
3. **Mixing references.** Never copy cells from `logs/ablation_gpt-5.6-terra/` (first run) into the new folder.
4. **Editing `eval_config.py`.** Not needed and not wanted for the ablation.
5. **Judging progress from the log.** It is block-buffered and can look frozen for an hour. Use `records.jsonl`.
6. **Single runs.** Temperature is 0, but the API is not fully deterministic: between two runs that differ only by a component without effect, 5 to 12% of the questions change outcome. This is why every comparison is paired and tested, and why small differences are reported as "not detected" rather than "zero".
