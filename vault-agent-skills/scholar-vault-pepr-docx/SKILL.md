---
name: scholar-vault-pepr-docx
description: Render PEPR MobiDec postdoc proposal DOCX files from Markdown drafts in this Scholar Vault. Use when Codex is asked to create, update, format, translate, paginate, or verify `AAP_postdoc*.docx` proposal files, especially when references must be generated from linked paper cards with `scholar-vault reference`, citations must be converted to numeric `[1]` style, or the PEPR template page limits need checking.
---

# Scholar Vault PEPR DOCX

Use this skill for template-bound PEPR postdoc DOCX work after the proposal prose already exists in Markdown. Keep research/evidence work in `$scholar-vault-proposal-evidence-sprint`; use this skill for rendering, reference formatting, and pagination.

## Main Tools

- `scripts/build_pepr_docx.py` renders a PEPR DOCX from a Markdown draft. By default it copies `sources/pepr-mobidec/AAP_postdoc_template.docx` and replaces content while preserving template styles, headers, tables, margins, and numbering.
- `scripts/render_docx.sh` renders a DOCX to PDF and per-page PNGs under `output/docx-render/<basename>/`, then prints page count.
- `scholar-vault reference` is called by the builder for deterministic APA-style references. Do not hand-format proposal bibliographies.

## Draft Requirements

The Markdown draft should have:

- `## Header fields` with bullet entries such as `**Titre de la proposition:**`.
- `## Resume du projet de post-doctorat` or `## Résumé du projet de post-doctorat`.
- `## Description du post-doctorat`.
- Optional `## References` / `## Références`; normally let the builder generate references from linked `papers/*.md` citations.

The builder strips Markdown links for DOCX output. Linked paper cards are still used to generate references.

## Standard Render

Use author-year prose citations and alphabetized APA references when page pressure is low:

```sh
scripts/build_pepr_docx.py \
  proposals/pepr-mobidec/proposal-prose-draft-v4.md \
  --output proposals/pepr-mobidec/AAP_postdoc_next_english.docx
```

This default render preserves the original template styles. Do not use `--layout compact` unless page limits require it, because compact mode deliberately changes font sizes and spacing.

For French drafts, pass the French reference heading:

```sh
scripts/build_pepr_docx.py \
  proposals/pepr-mobidec/proposal-prose-draft-french.md \
  --output proposals/pepr-mobidec/AAP_postdoc_next_French.docx \
  --references-heading Références
```

## Page-Safe Render

Use numeric citations and a separate reference page when Pages/Word pagination is tight. First try `references-compact`, which preserves the template body/header styles and only tightens generated references:

```sh
scripts/build_pepr_docx.py \
  proposals/pepr-mobidec/proposal-prose-draft-french.md \
  --output proposals/pepr-mobidec/AAP_postdoc_next_French.docx \
  --citation-style numeric \
  --reference-order appearance \
  --reference-page-break \
  --references-heading Références \
  --layout references-compact
```

If the prose itself is still too long, shorten the Markdown draft. Use full compact mode only as a last resort because it changes body typography:

```sh
scripts/build_pepr_docx.py \
  proposals/pepr-mobidec/proposal-prose-draft-french.md \
  --output proposals/pepr-mobidec/AAP_postdoc_next_French.docx \
  --citation-style numeric \
  --reference-order appearance \
  --reference-page-break \
  --references-heading Références \
  --layout compact
```

This converts linked paper-card citations to `[1]`, `[1-3]`, etc., and creates matching numbered APA-style references in first-appearance order.

## Verification

Always render after building:

```sh
scripts/render_docx.sh --max-pages 5 proposals/pepr-mobidec/AAP_postdoc_next_French.docx
```

Inspect the generated page PNGs. Check:

- page count and A4 page size;
- header table and abstract table are intact;
- references start on the intended page;
- bibliography entries are readable and not split into empty bullet boxes;
- no raw Markdown links, `**`, `<!--`, or `[ANNOTATIONS]` remain.

Pages can paginate differently from LibreOffice. If the user reports a Pages mismatch, prefer numeric citations, `references-compact`, and a reference page break, then shorten prose before using full compact mode. If AppleScript export from Pages is unavailable or fails, state that limitation and treat LibreOffice plus user Pages inspection as the verification boundary.
