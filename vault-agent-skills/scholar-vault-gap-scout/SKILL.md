---
name: scholar-vault-gap-scout
description: Scout research, metadata, PDF, synthesis, and typed queue gaps in a Scholar Vault. Use when Codex is asked what to import next, which PDFs or metadata need attention, which candidate Scholar Labs results deserve follow-up, which typed queue items should be created, or what prompt packs should be generated after import and enrichment.
---

# Scholar Vault Gap Scout

Use this skill to turn vault maintenance and literature gaps into actionable
task notes, typed queue items, or Scholar Labs prompt-pack recommendations.

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

1. Orient from `AGENTS.md`, `llms.txt`, `llms-full.txt`, `scholar-vault status --json`, and `_indexes/`.
2. Treat `_indexes/missing-pdfs.md` as optional Scholar Labs candidate discovery context, not a maintenance defect list.
3. Treat `_indexes/unmatched.md` as historical staging-manifest audit data. Check `scholar-vault pdf-doctor --json` before calling it actionable.
4. Search `papers/*.md` for `enrichment_status: incomplete`, `citation_status: ambiguous`, `citation_status: unresolved`, `abstract_status: missing`, `abstract_status: ambiguous`, `publication_keywords_status: missing`, and `pdf_status: missing`.
5. Read relevant `runs/**/index.yaml` or run notes to understand candidate rank, prompt context, and rationale.
6. Check graph-assisted candidates with `scholar-vault discover list` and
   `scholar-vault discover doctor --json` when the user is deciding what to
   search or import next.
7. Check existing `syntheses/`, `tasks/`, `tasks/queue/`, and
   `_indexes/self-improvement.md` if present to avoid duplicating active work.
8. Write `tasks/<YYYY-MM-DD>-research-gaps.md` when a narrative report is
   useful. Use `scholar-vault maintenance-report --write-queue` or
   `$scholar-vault-self-improvement` / `scholar-vault queue add ...` when the
   output should be durable typed work.
9. When the next action is a Google Scholar Labs search, prefer a durable prompt
   pack via `$scholar-vault-labs-prompts` / `scholar-vault labs-prompts generate`
   instead of embedding full prompt text only in the gap report.

## What To Prioritize

Prioritize gaps that materially improve the vault as an LLM-readable wiki:

- Active non-duplicate PDFs still in staging after import runs.
- User-requested next-import candidates from Scholar Labs run results.
- Canonical cards with attached PDFs but incomplete/ambiguous citation metadata.
- Cards with missing abstracts, missing publication keywords, or no useful notes.
- Cards whose linked PDFs have not been read deeply enough to support reliable synthesis.
- Topic noise that blocks retrieval or synthesis.
- Areas where syntheses show thin evidence, conflicting claims, or outdated coverage.

Separate canonical paper issues from candidate-result issues. A run candidate without a `paper_card` is not yet a canonical source, and is only worth tasking when the user wants another import/search pass. Historical unmatched rows are only worth tasking when the staged file still exists and is not a vault duplicate.

## CLI Helpers

Use these when useful:

```fish
conda activate scholar-vault
scholar-vault status --json
scholar-vault pdf-doctor --json
scholar-vault runs
scholar-vault maintenance-report --write-queue
scholar-vault queue list --json
scholar-vault labs-prompts list
scholar-vault labs-prompts doctor --json
scholar-vault discover list
scholar-vault discover doctor --json
scholar-vault match-staging
scholar-vault enrich --dry-run
scholar-vault enrich --only missing-abstract --dry-run
scholar-vault enrich --only missing-keywords --dry-run
```

Use `$scholar-vault-read-pdf` when a gap requires checking what the selected PDF actually says rather than relying on card metadata or Scholar Labs summaries.

Use non-dry-run commands only when the user asked to repair the vault, not when only scouting.

## Task Note Shape

Use this structure:

````markdown
---
type: research_gap_report
created: "<YYYY-MM-DD>"
---

# Research gaps - <YYYY-MM-DD>

## Highest priority
- <Action> | Evidence: <links> | Suggested command or search.

## PDF triage
- <active non-duplicate staged PDF issue, or "none">

## Optional candidate discovery
- <Scholar Labs candidate to revisit only if the user wants more imports>

## Metadata and card follow-up
- <card link> - <missing/ambiguous state> - <next command>

## Synthesis gaps
- <theme> - <why the vault is thin or conflicted>

## Scholar Labs prompt-pack recommendations
- <query/project/gap that should get a prompt pack> - Suggested command:
  `scholar-vault labs-prompts generate --query <slug>` / `--project <slug>` /
  `--from-gaps`

## Typed queue recommendations
- <gap> - Suggested command:
  `scholar-vault queue add --kind <kind> --title "..." --required-evidence <pdf|metadata|web|none>`
````

Keep tasks concrete enough that a later agent can execute them without rediscovering the whole vault.
