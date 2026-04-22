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

## Canonical Data Model

- Canonical source record: `papers/<slug>.md`
- Scholar Labs provenance record: `runs/<date>_<prompt-slug>/index.md` and `index.yaml`
- Raw inputs: `raw/`
- Derived indexes and exports: `_indexes/`, `_exports/`, `llms.txt`, `llms-full.txt`

## Merge Strategy

- Match existing cards by DOI first, then Scholar CID, citekey, exact normalized title, and finally near-exact title similarity when appropriate.
- Keep the original `source_kind` on an existing card so enrichment imports do not erase provenance.
- Prefer existing citekeys, summaries, notes, and discovered runs. Fill missing metadata from new imports.

## Rebuild Strategy

- Rebuild reads canonical paper cards plus run YAML files.
- Rebuild regenerates indexes, topic pages, LLM summaries, and export files.
- Rebuild intentionally does not require Obsidian, Zotero, or a database.
