---
name: scholar-vault-orient
description: Orient an agent inside a Scholar Vault research vault. Use when Codex needs to inspect the vault structure, find relevant canonical papers, Scholar Labs runs, topics, active staging/PDF issues, optional candidate discovery context, metadata issues, or prepare for later synthesis/refinement work without editing files.
---

# Scholar Vault Orient

Use this skill to build a compact working map of a Scholar Vault before doing research or maintenance work.

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

1. Confirm the current folder is a vault root or locate it by finding `config.yaml`, `papers/`, `runs/`, and `llms.txt`.
2. Read `AGENTS.md` first, then `llms.txt`, then the relevant parts of `llms-full.txt`.
3. Use `_indexes/papers.md`, `_indexes/topics.md`, `_indexes/missing-pdfs.md`, and `_indexes/unmatched.md` as navigation surfaces. Do not scan every PDF.
4. Use `rg` over `papers/`, `runs/`, `_indexes/`, and `syntheses/` for user-provided terms, author names, citekeys, topics, and methods.
5. Read only the paper cards and run notes needed for the question. Prefer canonical `papers/*.md` for source state and `runs/**/*.md` or `runs/**/index.yaml` for Scholar Labs prompt provenance.
6. Return a concise orientation report with file links, not a long literature review.

## Vault Model

- `papers/*.md` are canonical source records.
- `runs/<run_id>/<Short Title>.md` is the Obsidian-facing Scholar Labs run note; `runs/<run_id>/index.yaml` is the machine-readable run record.
- `pdfs/` stores attached canonical PDFs.
- `raw/` stores raw exports, staged/archive data, and provider metadata; treat it as immutable unless the user explicitly asks for vault maintenance.
- `_indexes/`, `_exports/`, `topics/`, `llms.txt`, and `llms-full.txt` are generated or derived views.
- `topics` on paper cards are prompt/navigation labels, not publication keywords. `keywords` are publication/provider/PDF keywords.
- `## Abstract` is provider/PDF/manual metadata. `## Scholar Labs summary` explains why Scholar Labs surfaced the source. Keep those concepts separate.
- Candidate results without paper cards are optional discovery context in the selected-only workflow. They are not canonical source defects unless the user wants to revisit those Scholar Labs suggestions.
- Historical unmatched manifest entries are actionable only when matching non-duplicate PDFs still exist in staging.
- `enrichment_status: missing` is a diagnostic/stale-or-not-yet-complete state, not automatically a follow-up issue. Prefer `status --json` issue counts and `enrich --ui` actionable rows.

## CLI Context

Prefer the configured CLI when it answers the question faster than manual parsing:

```fish
conda activate scholar-vault
scholar-vault status --json
scholar-vault configure
scholar-vault runs
scholar-vault enrich --dry-run
scholar-vault match-staging
```

Use `scholar-vault rebuild` only after actual manual edits to canonical cards. Orientation should normally be read-only.

## Report Shape

When orienting, include:

- Vault root and relevant indexes read.
- Relevant runs, with run note links and the user-facing run titles.
- Relevant canonical papers, with paper-card links, PDF status, enrichment status, abstract status, and topics.
- Candidate results only when the user is deciding what to import next, clearly labeled as optional non-canonical discovery context.
- Unmatched/staged PDF issues only when active, non-duplicate PDFs remain in staging.
- Recommended next files or commands for the user's goal.

Keep the report factual. Mark uncertainty instead of filling gaps from memory.
