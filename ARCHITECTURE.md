# Architecture

## Repository

- `scholar_vault/cli.py`: Typer CLI entrypoint and command wiring.
- `scholar_vault/models.py`: typed records for exports, paper cards, runs, logs, and PDF candidates.
- `scholar_vault/sources.py`: vault path management, slug and citekey utilities, Markdown parsing, and frontmatter helpers.
- `scholar_vault/matcher.py`: PDF extraction, metadata inference, and fuzzy matching helpers.
- `scholar_vault/importer.py`: end-to-end workflows for `init`, import commands, rebuilds, and derived exports.
- `scholar_vault/render.py`: Jinja-backed Markdown rendering for cards, run pages, indexes, topics, and LLM summary files.
- `scholar_vault/bibtex.py`: BibTeX parsing and export helpers.
- `templates/`: Markdown body templates for the generated paper, run, and index documents.
- `browser/`: browser-side exporter for visible Google Scholar Labs results.
- `tests/`: regression coverage for naming, parsing, matching, rendering, and idempotence.

## CLI Workflows

- `import-labs`: Scholar Labs convenience flow. It keeps all JSON results on the run record, creates canonical paper cards only for selected results by default, and archives matched PDFs out of staging only after the verified vault copy exists.
- `import-run`: lower-level transactional Scholar Labs import. It uses the same matching and manifest logic but leaves staging untouched unless another command archives files later.
- `import-pdf`, `import-bibtex`, and `import-doi`: non-Scholar-Labs ingestion paths that still converge on canonical `papers/*.md` cards.

## Canonical Data Model

- Canonical source record: `papers/<slug>.md`
- Scholar Labs provenance record: `runs/<date>_<prompt-slug>/index.md` and `index.yaml`
- Raw inputs: `raw/`
- Derived indexes and exports: `_indexes/`, `_exports/`, `llms.txt`, `llms-full.txt`

## Merge Strategy

- Match existing cards by DOI first, then Scholar CID, citekey, and exact normalized title.
- Keep the original `source_kind` on an existing card so enrichment imports do not erase provenance.
- Prefer existing citekeys, summaries, notes, and discovered runs. Fill missing metadata from new imports.

## Rebuild Strategy

- Rebuild reads canonical paper cards plus run YAML files.
- Rebuild regenerates indexes, topic pages, LLM summaries, and export files.
- Rebuild intentionally does not require Obsidian, Zotero, or a database.
