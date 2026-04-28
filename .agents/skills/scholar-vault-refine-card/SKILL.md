---
name: scholar-vault-refine-card
description: Safely refine canonical Scholar Vault paper cards. Use when Codex is asked to improve notes, fix safe metadata, add manual context, clean paper-card wording, or prepare cards for better agent use while preserving generated sections, provenance, abstracts, locks, and enrichment-managed fields.
---

# Scholar Vault Refine Card

Use this skill to improve canonical `papers/*.md` cards without breaking importer idempotence or generated views.

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

## Safe Editing Boundary

Edit only canonical paper cards in `papers/` unless the user explicitly asks for a broader change.

Safe durable targets:

- Compact frontmatter corrections the user or source evidence supports.
- `topics` frontmatter when coordinating with topic curation.
- `keywords` only when using source/provider/PDF keywords or the `set-keywords` command.
- `## Notes`, for agent-written reading notes, synthesis hooks, limitations, or user annotations.

Avoid hand-editing:

- `runs/`, `topics/`, `_indexes/`, `_exports/`, `llms.txt`, and `llms-full.txt`; these are generated or derived.
- `raw/` provider/export data.
- Attached files in `pdfs/` unless the user is doing PDF maintenance through the CLI.
- Long generated sections such as `## Scholar Labs summary`, run-specific summaries, `## Files`, `## Links`, and `## Provenance` unless you are deliberately preserving their parseable structure.

## Preserve These Fields

Do not overwrite or clear these without explicit evidence and intent:

- `discovered_in`, `source_kind`, `scholar_cid`, links, and run provenance.
- `metadata_lock: true`, `abstract_lock: true`, `citation_status: verified`, and `abstract_status: manual_lock`.
- `doi_*`, `citation_*`, `abstract_*`, `enrichment_*`, and retry/fingerprint fields managed by enrichment.
- Scholar Labs summaries and `summary_sources`; those are prompt-specific provenance, not general notes.

## Prefer CLI Commands

Use the CLI for tool-managed changes:

```fish
conda activate scholar-vault
scholar-vault resolve-citation --citekey <citekey> --doi <doi> --authors "Author A; Author B" --year <year> --venue "<venue>"
scholar-vault set-abstract --citekey <citekey> --file <text-file> --source-url <url>
scholar-vault set-keywords --citekey <citekey> --text "Keyword A; Keyword B"
scholar-vault enrich --citekey <citekey>
scholar-vault enrich --citekey <citekey> --only missing-abstract
scholar-vault enrich --citekey <citekey> --only missing-keywords
scholar-vault rebuild
```

Use `metadata_lock`, `abstract_lock`, and explicit refresh flags according to the card's current state.

## Workflow

1. Read `AGENTS.md`, then the target paper card and any linked run notes needed for provenance.
2. Inspect frontmatter and body sections with the parser model in mind: `## Abstract`, `## Keywords`, `## Scholar Labs summary`, `## Why this source matters`, and `## Notes` are parsed by the tool.
3. Make the smallest durable edit that satisfies the request.
4. If any generated or indexed view should reflect the edit, run `scholar-vault rebuild` using the CLI environment above.
5. Report what changed, what was preserved, and whether rebuild/verification ran.

## Notes Style

Put agent-written interpretation in `## Notes` with short dated or titled subsections when useful. Link related cards with relative links, and separate facts from interpretation.
