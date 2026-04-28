---
name: scholar-vault-synthesize
description: Create Obsidian-ready literature syntheses from a Scholar Vault. Use when Codex is asked to answer a research question, compare themes, build a literature review section, summarize evidence across papers, or write a durable synthesis note from canonical paper cards and Scholar Labs run provenance.
---

# Scholar Vault Synthesize

Use this skill to turn a research question or theme into a durable synthesis note grounded in the vault.

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
3. Read canonical `papers/*.md` for source metadata, abstract, keywords, PDF status, notes, and existing provenance.
4. Read relevant `runs/**/*.md` only to understand the original Scholar Labs prompt, ranking, rationale, and run-specific summary. Do not treat run candidates without paper cards as canonical evidence unless explicitly labeled.
5. Write the synthesis into `syntheses/<short-slug>.md`. Create `syntheses/` if it does not exist.
6. Link claims to paper cards with relative Markdown links.

## Source Rules

- `papers/*.md` are canonical. Prefer them over run notes for title, authors, year, venue, DOI, PDF, abstract, notes, keywords, and locks.
- `runs/` explains discovery context and prompt-specific rationale. It may include unselected candidates and should not be treated as a final bibliography.
- Keep `## Abstract` separate from `## Scholar Labs summary`: abstracts are provider/PDF/manual metadata; Scholar Labs summaries explain why a result matched a prompt.
- Preserve uncertainty. If a card has `enrichment_status: incomplete`, `citation_status: ambiguous`, missing DOI/venue/year, or no PDF, mention that limitation where relevant.
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
