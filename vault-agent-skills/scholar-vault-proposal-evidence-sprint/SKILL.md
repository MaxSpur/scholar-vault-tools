---
name: scholar-vault-proposal-evidence-sprint
description: Run proposal-focused, PDF-grounded evidence sprints in a Scholar Vault. Use when Codex is asked to refine a grant/postdoc proposal from a vault by reading a selected paper batch, updating paper cards, preserving or enriching a raw idea card, creating claim/source matrices and concept cards, updating proposal outlines, and rebuilding/verifying the vault.
---

# Scholar Vault Proposal Evidence Sprint

Use this skill for repeatable proposal-building batches. It orchestrates the existing vault skills; it does not replace `$scholar-vault-read-pdf`, `$scholar-vault-refine-card`, `$scholar-vault-synthesize`, or `$scholar-vault-research-loop`.

## Goal

Convert a focused selection of papers into durable proposal evidence:

- paper-card PDF notes that can be reused later;
- a source matrix mapping papers to claims, work packages, use cases, and caveats;
- concept cards only for recurring proposal concepts;
- sourced proposal-outline bullets or prose;
- updated task/memory files and verified derived vault outputs.

## CLI Environment

Before any `scholar-vault ...` command, use the project Conda environment:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault status --json
```

Use the same explicit prefix for `rebuild`, `pdf-doctor`, or other vault commands unless the active shell is already in the `scholar-vault` environment.

## Sprint Workflow

1. Read `AGENTS.md`, `ARCHITECTURE.md`, the active proposal outline, the raw idea card if present, and the relevant call/template source notes.
2. Confirm the sprint question and choose a batch size:
   - 5-8 papers for proposal refinement and sharper prose;
   - 9-13 papers only for a broad first-pass overview.
3. Build the reading set from selected `papers/*.md` cards with attached PDFs. Treat Scholar Labs summaries as discovery context only.
4. Read PDFs with `$scholar-vault-read-pdf`. For each relevant source, capture contribution, method/data, evidence, figures/tables, limitations, proposal role, and proposal use.
5. If current instructions allow delegation, use read-only subagents for independent paper batches. Ask each subagent for card-note-ready bullets and no file edits.
6. Update each read paper card under `## Notes` with:

```markdown
### PDF reading notes - <YYYY-MM-DD>

- **Proposal role:** Core / Supporting / Discarded after reading.
- **Contribution:** ...
- **Method/data:** ...
- **Relevant evidence:** ...
- **Figures/tables:** ...
- **Limitations:** ...
- **Proposal use:** ...
```

7. Preserve raw proposal ideas. If enriching a raw idea card, keep the user's original text under:

```markdown
## Original User Notes - Verbatim
```

Put interpretation, sourced claims, gaps, and draft phrasing in later sections such as `## Working Enrichment`, `## Open Questions`, or `## Source Links`.

8. Create/update a source matrix in `syntheses/<date>-<proposal>-pdf-grounded-source-matrix.md` with:
   - short answer;
   - table of source, role, grounded claim, work package/use, caveat;
   - draftable English/French blocks;
   - work-package mapping;
   - external anchors and remaining caveats.
9. Create concept cards in `concepts/` only when a concept links several sources or will recur in the proposal. Do not create concept cards for one-paper notes.
10. Update the proposal outline with sourced bullets or prose. Keep full DOCX drafting separate unless the user asks to write into the DOCX.
11. Update `tasks/` and lightweight memory files when the sprint changes project state.
12. Run `scholar-vault rebuild`, then `scholar-vault status --json`, `git diff --check`, `git diff --stat`, and `git status --short`.

## Source Matrix Template

```markdown
---
type: synthesis
title: "<Proposal> PDF-grounded source matrix"
question: "<What proposal claims does this batch ground?>"
created: "<YYYY-MM-DD>"
evidence_status: "PDF-grounded first pass"
sources:
  - ../papers/example.md
---

# <Proposal> PDF-grounded source matrix

## Short answer

<Synthesis of what this batch proves, does not prove, and how it changes the proposal.>

## Source Matrix

| Source | Proposal role | Grounded claim | Work package / use | Caveat |
|---|---|---|---|---|
| [Author year](../papers/example.md) | Core | ... | ... | ... |

## Draftable Blocks

### <Block title>

<Proposal-ready paragraph with links nearby, not excessive citation clutter.>

## Work Package Mapping

- **WP1 ...:** ...

## Caveats Before Drafting

- ...
```

## Efficiency Rules

- Normalize all card notes from the same batch in one editing pass.
- Use synthesis/concept cards for cross-paper ideas; do not repeat the same synthesis in every paper card.
- Prefer fewer, deeper papers before drafting full prose.
- Keep claims traceable: every proposal-facing claim should link to a paper card with PDF notes or to the source matrix.
- Do not render the DOCX until actual proposal prose is inserted.
- Do not edit generated folders directly; rely on `scholar-vault rebuild`.
