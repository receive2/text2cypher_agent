# LLM-use disclosure (for the paper body, per ACL policy)

ACL policy requires disclosing LLM/AI-assistant use in the **paper body**, not
only the datasheet. Paste the LaTeX block below as an unnumbered section
(before Acknowledgments), and use the checklist mapping for the Responsible
NLP Checklist answers. Keep model identifiers pinned exactly as written —
they are recorded per-edit in the released manifest.

## LaTeX block (ready to paste)

```latex
\section*{Use of AI Assistants}

Large language models were used in this work in three disclosed roles; in no
case did an LLM act as a judge of data validity.

\paragraph{Perturbation proposal (data construction).}
Candidate abbreviations and aliases for benchmark entities were proposed by
LLMs when no attested knowledge-base form existed: initially
\texttt{gpt-4.1}, later replaced by \texttt{claude-opus-5} under an
abstention-first protocol (the model must return \emph{no form} unless a
real, attested one exists, and must cite one-sentence evidence). Proposals
were never accepted automatically: every LLM-proposed surface form passed
deterministic database gates (collision and uniqueness checks against the
live graph) and 100\% human verification (double-annotated census with
adjudication; \S\ref{sec:verification}). Validity was judged only by the
database, attested resources, and human annotators --- never by an LLM ---
so any LLM, including evaluated systems, can serve as proposer without
contaminating the labels. Every released LLM-proposed edit carries its proposer model and
the evidence the proposer cited, frozen in the released manifest
(`release_manifest_v2.2.jsonl`), and the released dataset is a verified
deterministic function of that manifest.

\paragraph{Engineering and writing assistance.}
Dataset-pipeline and audit tooling were developed with AI assistance
(Claude); all code is released and was reviewed by the authors, who take
full responsibility for the content of this paper. Because evaluated systems
include models from the same family as the proposer, every released edit is
labelled with its provenance (LLM-proposed, attested, or algorithmic) so that
results can be split by it.
```

## Responsible NLP Checklist mapping

| Checklist item | Answer / pointer |
|---|---|
| Use of AI assistants disclosed? | Yes — section above; roles: proposer, engineering |
| Models identified? | `gpt-4.1`, `claude-opus-5` (pinned per edit in `release_manifest_v2.2.jsonl`) |
| Human oversight of AI-generated content? | every LLM-proposed edit double-annotated and adjudicated; fixed verdict rules (`docs/VERIFICATION_PROTOCOL.md` §5) |
| Contamination / circularity risk? | LLM never judges; DB + attested + human judges only; provenance ablation reported |
| Artifacts released? | manifest (every released edit with proposer model + evidence), rebuild script, proposer prompts (`scripts/regenerate_llm_tier.py`), per-item verdicts (`audit/verification/`) |

## Notes for the writer

- Wire `\S\ref{sec:verification}` to the actual section label in paper.tex.
- If reviewers ask "which snapshot of claude-opus-5": the API alias is
  undated by provider design; the manifest records the call date
  (2026-08) — state that.
- The number to cite for LLM-proposed edits is the verified validity rate:
  97.2% [95.9, 98.1] (abbrev 96.7%, alias 98.7%, partial 92.1%;
  `docs/VERIFICATION_PROTOCOL.md` §6). The earlier ~85% A/B figure
  (`audit/llm_proposer_ab_results.md`) is raw proposer precision before the
  database gates, not the released rate.
