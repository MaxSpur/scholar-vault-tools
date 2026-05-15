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

1. Start from `AGENTS.md`, `scholar-vault status --json`, and the target `papers/*.md` card. Use `scholar-vault notes-missing --heading "PDF reading notes"` when building a queue of selected cards that still need PDF reading.
2. Resolve the linked `pdf` field relative to the vault root and read the actual PDF before making factual claims.
3. Use the card and run notes for metadata, provenance, Scholar Labs rationale, and existing notes. Use the PDF for evidence, methods, findings, limitations, definitions, and citation-worthy claims.
4. For serious reading, extract the full PDF text first, then search within that text for abstract, introduction, methods, datasets, evaluation, results, discussion, conclusion, limitations, and references to related vault papers.
5. Use Codex's available PDF-reading/rendering capabilities for important figures, tables, diagrams, maps, visual encodings, equations, or scanned content. If the paper is figure-heavy or the user asks about visuals, inspect the rendered PDF pages before summarizing claims.
6. Use page ranges only for targeted revisits after full-text orientation, for very long documents, or when rendering selected figures/pages. Do not treat a first-page excerpt as enough for synthesis.
7. Write durable findings to the card's `## Notes`, to a new `syntheses/*.md`, to a new `concepts/*.md`, or to a new `tasks/*.md` depending on the user's goal.
8. When the goal is to leave one paper ready for future syntheses, use `$scholar-vault-compile-paper` to fill `paper-digests/<citekey>.md` and mark the compile state.
9. Run `scholar-vault concept-index` after concept-only edits, or `scholar-vault rebuild` after card, topic, synthesis, task, or proposal edits so indexes, exports, and LLM files reflect the changes.

## PDF Text Helper

Use the bundled helper when shell PDF tools are unavailable:

```fish
python .agents/skills/scholar-vault-read-pdf/scripts/extract_pdf_text.py pdfs/example.pdf --output /tmp/example-full.txt
python .agents/skills/scholar-vault-read-pdf/scripts/extract_pdf_text.py pdfs/example.pdf --head-chars 8000
python .agents/skills/scholar-vault-read-pdf/scripts/extract_pdf_text.py pdfs/example.pdf --pages 3-8,14 --output /tmp/example-pages.txt
```

From a copied skill folder, resolve the script path relative to this `SKILL.md`. Prefer temporary files under `/tmp` for extracted text unless the user asks for a durable artifact.

## Figures And Visual Evidence

Text extraction misses figures, tables, visualizations, page layout, and sometimes scanned text. Do not reimplement generic PDF rendering inside this skill. When visuals matter, use Codex's PDF-reading skill/tooling or other available PDF rendering workflow to inspect pages directly.

Inspect rendered pages for maps, diagrams, charts, screenshots, tables, mathematical layouts, figure captions, and appendix material. Summaries that depend on visual encodings or study results should mention that rendered pages were inspected. If no rendering/visual inspection path is available in the active environment, state that limitation instead of relying on text extraction alone.

## What To Add

Useful card-level additions:

- `## Notes` entries with claims, methods, datasets, evaluation type, limitations, terminology, and links to related cards.
- `concepts/<slug>.md` cards for reusable concepts, methods, datasets, evaluation protocols, or visual encodings that connect several papers.
- Safer `topics` frontmatter when the PDF reveals better retrieval labels. For broad cleanup, use `$scholar-vault-curate-topics` or `scholar-vault topic-map`.
- Publication keywords via `scholar-vault set-keywords` only when the PDF contains explicit keywords or index terms.
- Abstracts via `scholar-vault set-abstract` only when using the paper's actual abstract, not an agent-written summary.
- Thesis/report metadata resolution via `scholar-vault resolve-citation --lock` when DOI or journal/conference venue is genuinely absent.

Useful metacards:

- `syntheses/<slug>.md` for cross-paper claims grounded in multiple PDFs.
- `concepts/<slug>.md` for concept/method/metacards that improve retrieval across papers.
- `tasks/<date>-research-gaps.md` for missing follow-up reads, unclear evidence, or next Scholar Labs prompts.
- `tasks/<date>-pdf-reading-log.md` when reading many PDFs in batches.

## Boundaries

- Do not treat Scholar Labs summaries, run rankings, `_indexes/`, `topics/`, or `llms*.txt` as evidence.
- Do not overwrite provider/manual abstracts with an agent-written summary.
- Do not hand-edit generated folders.
- Preserve `raw/`, provenance, locks, and enrichment fingerprints.
- If a PDF is a thesis, report, preprint, or dataset paper, name that in `## Notes` and use `resolve-citation --lock` rather than inventing DOI or venue metadata.
