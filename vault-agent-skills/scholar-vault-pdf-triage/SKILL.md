---
name: scholar-vault-pdf-triage
description: Triage Scholar Vault PDF and staging issues. Use when Codex is asked to inspect orphan or duplicate PDFs, active non-duplicate PDFs left in staging, historical unmatched manifest rows, staged PDF cleanup, targeted leftover-PDF imports, PDF attachment decisions, or rerun/import follow-up after Scholar Labs downloads.
---

# Scholar Vault PDF Triage

Use this skill to resolve PDF inventory and staging-folder problems without breaking run provenance or canonical paper cards.

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

## PDF Model

- Canonical PDF attachments are referenced from `papers/*.md` through the `pdf` field.
- `pdfs/` may contain orphan files, duplicate hashes, or suffix names such as `-2.pdf`; inspect before deleting or moving anything.
- Staging folders are external working queues. Matched staging PDFs should be imported through `import-labs`, targeted `match-staging --ui`, `rerun`, `attach-pdf`, or `clean-staging`, not by hand-moving files.
- `runs/**/index.yaml` and `runs/**/import-manifest.yaml` preserve why a PDF was selected, unmatched, rejected, or archived.
- Historical unmatched entries are not an action queue by themselves. They only matter when `pdf-doctor` shows active, non-duplicate PDFs still in staging.
- Scholar Labs candidate results without `paper_card` are optional discovery backlog, not missing canonical PDFs.

## Workflow

1. Read `AGENTS.md` and run `scholar-vault pdf-doctor --json`.
2. If `staging.actionable_pdf_count` is `0`, report that no remaining staging match work is needed even if historical unmatched entries exist.
3. If active non-duplicate staged PDFs remain, read `_indexes/unmatched.md`, `_indexes/missing-pdfs.md`, and the relevant run note or run YAML.
4. Use `scholar-vault match-staging` or `scholar-vault match-staging --ui` to score leftover staged PDFs against prior Scholar Labs results.
   - In the GUI, prefer the targeted workflow for one-off leftovers: enter the likely paper title, choose the exact staged PDF path, click `Search`, inspect candidate run summaries, then click `Import PDF` on the correct row.
   - This attaches that PDF to the selected run result, copies it into `pdfs/`, archives the staging original after verification, updates run manifests, syncs matching prior runs, and enriches the touched card.
5. Read the staged or attached PDF with `$scholar-vault-read-pdf` when deciding whether it is the right source, a better version, a thesis/report, or a duplicate with different metadata.
6. For a known one-off match, use `scholar-vault attach-pdf --citekey <citekey> --pdf <path>` so the vault copies and verifies the PDF, syncs related runs, and rebuilds derived files.
7. For true run-level batches or upgrade reviews, use `scholar-vault rerun --run <run-id> --ui`; keep `--keep-existing-pdfs` only when you do not want attached PDFs considered for replacement.
8. Use `scholar-vault clean-staging` only for staged files that are byte-identical to vault PDFs.
9. Report which files were only inspected, which commands changed vault state, and which files still require human judgment.

## Commands

```fish
conda activate scholar-vault
scholar-vault pdf-doctor
scholar-vault pdf-doctor --json
scholar-vault match-staging --ui
scholar-vault match-staging --pdf <staged-pdf> --unselected-only
scholar-vault match-staging --title "<paper title>" --pdf <staged-pdf> --unselected-only --ui
scholar-vault rerun --run <run-id> --ui
scholar-vault attach-pdf --citekey <citekey> --pdf <staged-pdf>
scholar-vault clean-staging
```

## Safety Rules

- Do not delete files from `pdfs/`, `raw/`, or staging by hand.
- Do not edit generated `_indexes/`, `topics/`, `_exports/`, `llms.txt`, or `llms-full.txt`.
- Prefer `match-staging --ui` for uncertain one-off staged matches because its targeted `Import PDF` action records the selected run result, manifest entry, staging archive, and enrichment pass together.
- Treat run candidates without `paper_card` as optional non-canonical discovery context until a selected/imported paper card exists.
- If a duplicate-style `pdfs/*-2.pdf` is attached to a card, do not rename it manually; use `scholar-vault rebuild` or a future dedicated PDF repair command.
