---
name: scholar-vault-research-loop
description: "Run PDF-grounded Scholar Vault improvement cycles. Use when Codex is asked to do actual research work after import/enrichment: read selected PDFs, understand figures/tables, refine touched paper cards, create concept/metacards, write syntheses, strengthen source connections, or improve the vault as an LLM-readable research wiki."
---

# Scholar Vault Research Loop

Use this skill for post-import research work, not maintenance triage. For the
normal user-facing path, prefer `scholar-vault answer "question"` because it
writes a session-linked Codex handoff. Use this skill when a user directly asks
for a manual research loop or when you are already inside that handoff. The
goal is to make future broad vault queries better by reading PDFs and adding
durable, evidence-grounded structure.

## CLI Environment

Before any `scholar-vault ...` command, activate the project Conda environment in the same shell:

```fish
conda activate scholar-vault
scholar-vault status --json
```

If activation is unavailable or `scholar-vault` is still not on `PATH`, use the explicit fallback:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault status --json
```

Do not retry plain `scholar-vault` commands without one of these environment paths.

## Research Cycle

1. Orient with `$scholar-vault-orient`, `AGENTS.md`, `llms.txt`,
   `scholar-vault session current --json`, and `scholar-vault status --json`.
2. Choose a focused question, concept, method, dataset, or cluster of related selected sources.
3. Build a reading set from `papers/*.md` cards with attached PDFs. Use `scholar-vault notes-missing --heading "PDF reading notes"` when you need the unread selected-card queue. Do not treat unselected Scholar Labs candidates as evidence.
4. For each source that matters, use `$scholar-vault-read-pdf`: extract full text, inspect relevant rendered pages/figures/tables, and note exact evidence from the PDF.
5. Update touched paper cards with concise `## Notes` that capture methods, claims, datasets, evaluation setup, limitations, visual encodings, and links to related cards. Use `$scholar-vault-compile-paper` when a source should also leave the compile queue with a durable `paper-digests/<citekey>.md` artifact.
6. Create or update metacards when they improve retrieval:
   - `concepts/<slug>.md` for reusable concepts, methods, datasets, visual encodings, evaluation protocols, and terminology.
   - `syntheses/<slug>.md` for cross-paper answers, tensions, and evidence-backed literature review sections.
   - `tasks/<date>-research-gaps.md` for narrative follow-up reading or missing evidence.
   - Typed queue items via `$scholar-vault-self-improvement` when the follow-up
     should be tracked, planned, closed, or linked to feedback.
   - Scholar Labs prompt packs via `$scholar-vault-labs-prompts` when the next
     action is a human-run Labs search.
7. Improve retrieval labels through `topics` only when the PDF evidence supports the label. Use `$scholar-vault-curate-topics` for broad cleanup.
8. Run `scholar-vault concept-index` after concept-only edits, or `scholar-vault rebuild` after broader edits, then re-run `scholar-vault status --json` to confirm generated views are refreshed.
9. For proposal workspaces, start with `scholar-vault proposal-sprint scaffold <slug>`, point outline frontmatter `evidence_matrix` at any shared source matrix such as `syntheses/<matrix>.md`, then run `scholar-vault proposal-audit proposals/<slug>` and fix structural evidence gaps before treating the draft as ready.
10. For formatted APA-style bibliography text in proposals, syntheses, or external drafts, use `scholar-vault reference <citekey>` or `scholar-vault references`; do not hand-format references from cards.

## Durable Note Shapes

Card notes should be short and evidence-oriented:

```markdown
### PDF reading notes - <YYYY-MM-DD>
- **Contribution:** ...
- **Method/data:** ...
- **Evidence:** ...
- **Figures/tables:** Figure 2 shows ...
- **Limitations:** ...
- **Connections:** Related to [Other card](other.md) because ...
```

Concept cards should connect sources, not duplicate paper summaries:

```markdown
---
type: concept
title: "<Concept>"
created: "<YYYY-MM-DD>"
sources:
  - papers/example.md
---

# <Concept>

## Definition
<Concise working definition grounded in PDFs.>

## Evidence Across Sources
- [Paper](../papers/example.md): <role of concept, method, or finding>.

## Distinctions
- <How this differs from nearby concepts.>

## Open Questions
- <What still needs reading or import.>
```

## Boundaries

- Do not write claims from Scholar Labs summaries unless the PDF confirms them.
- Do not bulk-read every PDF when the user asked for a focused research question; build a defensible reading set.
- Do not create concept cards for one-off labels that are better as card notes.
- Do not edit generated folders. Use `rebuild` after durable edits.
- Keep query/session links current when working from an autopilot handoff; link
  syntheses back to the query and update the session report through the CLI
  workflow when available.
- Keep final synthesis coordinated in the main thread. Subagents can be useful for parallel read-only PDF passes only when the active environment and user instructions allow them.
