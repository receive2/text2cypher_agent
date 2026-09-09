# Source-dataset license audit (task L1)

Can we legally release a **derivative** (entity-perturbed) benchmark built on
CypherBench / Mind-the-Query / ZOGRASCOPE? **Short answer: yes** — all three
source *datasets* are permissively licensed and permit derivative +
redistribution. The only real risk is the **third-party graph dumps**, which we
sidestep by not redistributing them.

_Audited 2026-07-15. Authoritative sources: the LICENSE/README files shipped in
`~/datasets/<ds>/`, cross-checked against each project's HF/GitHub/paper._

## What we actually redistribute

Our release = **(perturbed NL question, unchanged gold Cypher, graph pointer)**.
We modify only the entity mention in the question; we do **not** modify golds and
(recommended) do **not** ship the graph database dumps.

## License table

| source | graphs we use | license | authoritative source | derivative+redistribute? | our obligations |
|---|---|---|---|---|---|
| **CypherBench** | nba, movie, geography, politics, company, fictional_character, flight_accident | **Apache-2.0** | HF dataset card `megagonlabs/cypherbench` + repo README front-matter; arXiv 2412.18702 (Megagon Labs) | ✅ yes | include license, retain copyright/NOTICE, **state changes** |
| **Mind-the-Query** | covid (contact-tracing), healthcare, wwc, er | **Apache-2.0** (shipped `LICENSE`) — ⚠️ README has a *commented-out* "MIT" line (ambiguity) | `~/datasets/mindthequery/LICENSE`; ACL Anthology 2025.emnlp-industry.133 (IBM Research, EMNLP 2025 Industry) | ✅ yes (both are permissive) | attribution + cite paper; **resolve MIT-vs-Apache** with authors |
| **ZOGRASCOPE** | pole | **CC-BY-4.0** | `~/datasets/zograscope/README.md` (explicit); arXiv 2503.05268 (Cazzaro et al.) | ✅ yes | **attribution + indicate modifications**; cite paper |

### Underlying graph data (only matters if we ship the dumps)

| layer | origin | license | note |
|---|---|---|---|
| CypherBench graphs | Wikidata | **CC0 / public domain** | no obligation |
| MtQ + ZOGRASCOPE graphs | **neo4j-graph-examples** repos (pole, contact-tracing, healthcare-analytics, entity-resolution, wwc2019, …) | **NO explicit LICENSE file in those repos** ⚠️ | underlying data is public (POLE = Manchester UK public crime data; healthcare = FDA FAERS, US public domain) but the neo4j wrappers state no license |

## Verdict

- **No blocker.** All three source datasets permit our derivative release.
- **Aggregate obligations:** attribution to all three + **an explicit "we modified
  the entity mentions; gold queries unchanged" statement** (required by CC-BY-4.0's
  "indicate changes" and Apache-2.0's "state changes").
- **The one risk** is the unlicensed third-party graph dumps — do **not**
  redistribute them.

## Recommendations (actionable)

1. **Do not ship graph dumps.** Release only (perturbed question, gold, graph
   pointer); evaluators load graphs from the original neo4j-graph-examples repos,
   exactly as MtQ/ZOGRASCOPE users already do. This removes the unlicensed-dump
   question entirely. (Track A gold-fixes still happen against the live graphs;
   that's a local eval concern, not redistribution.)
2. **Release the derivative data under CC-BY-4.0**, with a per-source
   `ATTRIBUTION`/`LICENSES` file listing each source + its license (CypherBench
   Apache-2.0, MtQ Apache-2.0, ZOGRASCOPE CC-BY-4.0). CC-BY-4.0 is compatible
   with all three (Apache-2.0 is permissive → derivatives may be relicensed;
   CC-BY-4.0 attribution satisfies ZOGRASCOPE). Ship code under Apache-2.0/MIT.
3. **Attribution/NOTICE file** crediting the three papers + the changes statement.
4. **Resolve MtQ MIT-vs-Apache**: shipped `LICENSE` is Apache-2.0; the README's
   MIT line is commented out. Email the IBM authors to confirm, or rely on the
   Apache-2.0 file (both permissive → low risk either way). Record the answer.
5. **PII check (ties to task E1):** POLE = Manchester UK public crime data;
   healthcare = FDA FAERS aggregate — confirm no real-individual PII before
   release; both are public/aggregate sources.

## Open items to close L1

- [ ] Email MtQ authors to confirm Apache-2.0 (resolve README/LICENSE mismatch).
- [ ] Decide + document our release license (recommend CC-BY-4.0 for data).
- [ ] Write `ATTRIBUTION`/`LICENSES` + changes statement into the release bundle.
- [ ] Confirm decision to **not** redistribute graph dumps (ship pointers).
