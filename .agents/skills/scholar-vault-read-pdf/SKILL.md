---
name: scholar-vault-read-pdf
description: Read linked PDFs in a Scholar Vault and use their content to refine paper cards, notes, topics, syntheses, and metadata. Use when Codex is asked to deeply read selected PDFs, extract claims/methods/findings/limitations, improve connections between sources, resolve thesis/report/non-article metadata, or make the vault more useful as an LLM-readable research wiki.
---

# Scholar Vault Read PDF

Use this skill when the PDF itself must be treated as the source of truth. In this vault model, `papers/*.md` cards are durable indexes and notes over PDFs; the linked PDF is the canonical evidence artifact.

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

## Reading Workflow

1. Start from `AGENTS.md`, `scholar-vault status --json`, and the target `papers/*.md` card.
2. Resolve the linked `pdf` field relative to the vault root and read the actual PDF before making factual claims.
3. Use the card and run notes for metadata, provenance, Scholar Labs rationale, and existing notes. Use the PDF for evidence, methods, findings, limitations, definitions, and citation-worthy claims.
4. For large PDFs, extract targeted page ranges or first-pass text, then search within extracted text for method terms, datasets, evaluations, conclusions, limitations, and references to related vault papers.
5. Write durable findings to the card's `## Notes`, to a new `syntheses/*.md`, or to a new `tasks/*.md` depending on the user's goal.
6. Run `scholar-vault rebuild` after card edits so indexes, exports, and LLM files reflect the changes.

## PDF Text Helper

Use the bundled helper when shell PDF tools are unavailable:

```fish
python .agents/skills/scholar-vault-read-pdf/scripts/extract_pdf_text.py pdfs/example.pdf --max-pages 5
python .agents/skills/scholar-vault-read-pdf/scripts/extract_pdf_text.py pdfs/example.pdf --pages 3-8,14 --output /tmp/example-pages.txt
```

From a copied skill folder, resolve the script path relative to this `SKILL.md`. Prefer temporary files under `/tmp` for extracted text unless the user asks for a durable artifact.

## What To Add

Useful card-level additions:

- `## Notes` entries with claims, methods, datasets, evaluation type, limitations, terminology, and links to related cards.
- Safer `topics` frontmatter when the PDF reveals better retrieval labels. For broad cleanup, use `$scholar-vault-curate-topics` or `scholar-vault topic-map`.
- Publication keywords via `scholar-vault set-keywords` only when the PDF contains explicit keywords or index terms.
- Abstracts via `scholar-vault set-abstract` only when using the paper's actual abstract, not an agent-written summary.
- Thesis/report metadata resolution via `scholar-vault resolve-citation --lock` when DOI or journal/conference venue is genuinely absent.

Useful metacards:

- `syntheses/<slug>.md` for cross-paper claims grounded in multiple PDFs.
- `tasks/<date>-research-gaps.md` for missing follow-up reads, unclear evidence, or next Scholar Labs prompts.
- `tasks/<date>-pdf-reading-log.md` when reading many PDFs in batches.

## Boundaries

- Do not treat Scholar Labs summaries, run rankings, `_indexes/`, `topics/`, or `llms*.txt` as evidence.
- Do not overwrite provider/manual abstracts with an agent-written summary.
- Do not hand-edit generated folders.
- Preserve `raw/`, provenance, locks, and enrichment fingerprints.
- If a PDF is a thesis, report, preprint, or dataset paper, name that in `## Notes` and use `resolve-citation --lock` rather than inventing DOI or venue metadata.
