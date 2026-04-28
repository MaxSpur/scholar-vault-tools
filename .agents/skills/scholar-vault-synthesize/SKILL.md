---
name: scholar-vault-synthesize
description: Create Obsidian-ready literature syntheses from a Scholar Vault, using linked PDFs as primary evidence and paper cards as indexes/provenance. Use when Codex is asked to answer a research question, compare themes, build a literature review section, summarize evidence across papers, or write a durable synthesis note from selected PDFs, paper cards, and Scholar Labs run provenance.
---

# Scholar Vault Synthesize

Use this skill to turn a research question or theme into a durable synthesis note grounded in the vault's selected PDFs and their paper cards.

## CLI Environment

Before any `scholar-vault ...` command, activate the project Conda environment in the same shell:

```fish
conda activate scholar-vault
scholar-vault runs
```

If activation is unavailable or `scholar-vault` is still not on `PATH`, use the explicit fallback:

```fish
/Users/MadMax/miniforge3/condabin/conda run -n scholar-vault scholar-vault runs
```

Do not retry plain `scholar-vault` commands without one of these environment paths.

## Workflow

1. Orient first: read `AGENTS.md`, `llms.txt`, relevant `llms-full.txt` entries, and targeted `_indexes/` files.
2. Find candidate evidence with `rg` across `papers/`, `runs/`, `topics/`, and existing `syntheses/`.
3. Read `papers/*.md` for source metadata, PDF links, abstracts, keywords, notes, and provenance.
4. Read linked PDFs for the claims that matter. Use `$scholar-vault-read-pdf` when the synthesis depends on methods, findings, limitations, definitions, or exact distinctions not already captured in notes.
5. Read relevant `runs/**/*.md` only to understand the original Scholar Labs prompt, ranking, rationale, and run-specific summary. Do not treat run candidates without paper cards as canonical evidence unless explicitly labeled.
6. Write the synthesis into `syntheses/<short-slug>.md`. Create `syntheses/` if it does not exist.
7. Link claims to paper cards with relative Markdown links and mention when evidence comes from a PDF read.

## Source Rules

- Linked PDFs are the primary evidence artifacts. `papers/*.md` are canonical card/index records for metadata, links, provenance, notes, abstracts, keywords, and locks.
- `runs/` explains discovery context and prompt-specific rationale. It may include unselected candidates and should not be treated as a final bibliography.
- Keep `## Abstract` separate from `## Scholar Labs summary`: abstracts are provider/PDF/manual metadata; Scholar Labs summaries explain why a result matched a prompt.
- Preserve uncertainty. If a PDF is unread, a card has `enrichment_status: incomplete`, `citation_status: ambiguous`, missing DOI/venue/year, expected thesis/report DOI absence, or no PDF, mention that limitation where relevant.
- Do not cite `_indexes/`, `topics/`, or `llms*.txt` as evidence. They are navigation aids.

## Output Template

Use this structure unless the user asks for a different format:

```markdown
---
type: synthesis
title: "<Title>"
question: "<User question or theme>"
created: "<YYYY-MM-DD>"
sources:
  - papers/example.md
---

# <Title>

## Short answer
<One to three paragraphs.>

## Evidence
- **Claim:** <claim>
  Evidence: [Paper title](../papers/example.md) ...

## Tensions and caveats
- <Disagreement, limitation, weak metadata, missing PDF, or scope caveat.>

## Useful sources
- [Paper title](../papers/example.md) (Author, year). DOI: ...

## Next questions
- <Follow-up search, PDF triage, or synthesis need.>
```

Use relative links appropriate to the note location. From `syntheses/`, link papers as `../papers/<slug>.md`.

## After Writing

Do not edit generated folders for synthesis. If the synthesis reveals metadata or topic issues, suggest `scholar-vault-refine-card`, `scholar-vault-curate-topics`, or `scholar-vault-gap-scout` as the next task.
