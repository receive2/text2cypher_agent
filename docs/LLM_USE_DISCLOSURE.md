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
contaminating the labels. All proposals, including rejected ones and their
per-item evidence, are frozen in the released decision manifest, and the
released dataset is a verified deterministic function of that manifest.

\paragraph{Supply measurement.}
The applicability-ceiling analysis (\S\ref{sec:applicability}) used the same
abstention-first proposer to estimate, per graph and strategy, the fraction
of entities admitting an attested alternative form; LLM-derived supply
estimates are discounted by the human-measured proposal precision.

\paragraph{Engineering and writing assistance.}
Dataset-pipeline and audit tooling were developed with AI assistance
(Claude); all code is released and was reviewed by the authors, who take
full responsibility for the content of this paper. Because evaluated systems
include models from the same family as the proposer, we report the
LLM-proposed vs.\ attested provenance split and an ablation over it, which
bounds any proposer-familiarity effect.
```

## Responsible NLP Checklist mapping

| Checklist item | Answer / pointer |
|---|---|
| Use of AI assistants disclosed? | Yes — section above; roles: proposer, supply probe, engineering |
| Models identified? | `gpt-4.1`, `claude-opus-5` (pinned per-edit in `release_manifest_v2.1.jsonl`) |
| Human oversight of AI-generated content? | 100% census of LLM-proposed edits, double annotation + adjudication, pre-registered rejection rules (DATASHEET §7 curation log) |
| Contamination / circularity risk? | LLM never judges; DB + attested + human judges only; provenance ablation reported |
| Artifacts released? | Manifest (all proposals + evidence), rebuild script, prompts (in `scripts/regenerate_llm_tier.py`, `scripts/measure_applicability_ceiling.py`) |

## Notes for the writer

- Wire `\S\ref{sec:verification}` / `\S\ref{sec:applicability}` to the actual
  section labels in paper.tex.
- If reviewers ask "which snapshot of claude-opus-5": the API alias is
  undated by provider design; the manifest records the call date
  (2026-08) — state that.
- The proposer-precision number to cite: ~85% (A/B,
  `audit/llm_proposer_ab_results.md`); final per-strategy acceptance rates
  come from the adjudicated census (auto-generated post-annotation).
